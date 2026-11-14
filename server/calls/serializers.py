"""Turn Call rows (+ report and events) into the console's JSON shapes.

Report data and event payloads are written by the agent and never validated, so every read here is
defensive: anything of the wrong type is treated as missing rather than raising.
"""

from urllib.parse import quote

from .models import CallEvent, CallReport, Recording
from .outcomes import display_outcome

# The report outcome keys that answer qualification questions (agent.py record_outcome); the rest
# (disposition, reason, summary, interest_strength, telecaller_followup_agreed, do_not_call) are not answers.
ANSWER_FIELDS = ("callback_time", "city", "licence", "experience", "uber_id", "preferred_plan", "main_question")
EMPTY = (None, "", [], {})


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _text(value) -> str:
    return value if isinstance(value, str) else ""


def report_of(call):
    try:
        return call.report
    except CallReport.DoesNotExist:
        return None


def recording_of(call):
    try:
        return call.recording
    except Recording.DoesNotExist:
        return None


# Recording.status -> what the console shows. starting/recording read as "processing".
RECORDING_STATUS = {
    Recording.STARTING: "processing",
    Recording.RECORDING: "processing",
    Recording.COMPLETE: "complete",
    Recording.FAILED: "failed",
    Recording.PURGED: "purged",
}


def recording_fields(call) -> dict:
    """recording_url/status/duration/started_at for the call detail. Stats the file once."""
    rec = recording_of(call)
    if rec is not None:
        rec.reconcile()
    status = RECORDING_STATUS.get(rec.status, "none") if rec else "none"
    url = None
    if status == "complete":
        if rec.file() is not None:
            url = f"/api/calls/{quote(call.room, safe='')}/recording"
        else:
            status = "failed"
    return {
        "recording_url": url,
        "recording_status": status,
        "recording_duration_s": round(rec.duration_ms / 1000, 1) if url and rec.duration_ms else None,
        "recording_started_at": rec.started_at if url else None,
    }


def outcome_data(call) -> dict:
    report = report_of(call)
    return _dict(_dict(report.data if report else None).get("outcome"))


def duration_s(call):
    """ended − answered when both exist, else ended − started, else None (whole seconds, never negative)."""
    start = call.answered_at if call.answered_at and call.ended_at else call.started_at
    if not (start and call.ended_at):
        return None
    return max(0, int((call.ended_at - start).total_seconds()))


def agent_name(call):
    version = call.agent_version
    if version is None:
        return None
    name = _dict(version.snapshot).get("name")
    return name if isinstance(name, str) and name else None


def call_row(call) -> dict:
    """One row of the calls list. Needs `report`, `recording` and `agent_version` loaded (select_related)."""
    report = report_of(call)
    rec = recording_of(call)
    code = report.disposition if report else ""
    return {
        "room": call.room,
        "started_at": call.started_at,
        "caller": call.caller,
        "agent_name": agent_name(call),
        "outcome": display_outcome(code),
        "outcome_code": code,
        "mood": report.final_mood if report else "",
        "duration_s": duration_s(call),
        "summary": _text(outcome_data(call).get("summary")),
        "has_recording": rec is not None and rec.status == Recording.COMPLETE,
        # No file check here (one per row would be slow); the detail view checks the file.
        "recording_status": RECORDING_STATUS.get(rec.status, "none") if rec else "none",
        # The current audit's overall score (0–100); querysets annotate it (calls.api.with_audit_score).
        "audit_score": getattr(call, "audit_score", None),
    }


def turn_row(event):
    """A transcript line from a `turn` event, or None when the payload has no text."""
    p = _dict(event.payload)
    text = p.get("text")
    if not isinstance(text, str) or not text:
        return None
    expressions = p.get("expressions")
    return {
        "speaker": _text(p.get("speaker")),
        "text": text,
        "expressions": [e for e in expressions if isinstance(e, str)] if isinstance(expressions, list) else [],
        "at": event.at,
    }


def transcript(events) -> list[dict]:
    rows = (turn_row(e) for e in events if e.type == CallEvent.TURN)
    return [r for r in rows if r is not None]


def captured_fields(events) -> dict:
    """{field: value} from field_captured events in seq order (a later capture wins)."""
    out = {}
    for e in events:
        if e.type != CallEvent.FIELD_CAPTURED:
            continue
        p = _dict(e.payload)
        field = p.get("field")
        if isinstance(field, str) and field and p.get("value") not in EMPTY:
            out[field] = p["value"]
    return out


def report_captured(report) -> dict:
    """{field: value} the agent's workflow captured, from report.data["captured"]; non-empty strings only."""
    captured = _dict(_dict(report.data if report else None).get("captured"))
    return {k: v for k, v in captured.items() if isinstance(k, str) and k and isinstance(v, str) and v}


def latest(events, type_, key) -> str:
    """The `key` string of the newest `type_` event that has one, else ""."""
    for e in reversed(events):
        if e.type == type_:
            value = _dict(e.payload).get(key)
            if isinstance(value, str) and value:
                return value
    return ""


def call_detail(call, events) -> dict:
    """`events`: the call's CallEvents in seq order."""
    outcome = outcome_data(call)
    report = report_of(call)
    answers = {k: outcome[k] for k in ANSWER_FIELDS if outcome.get(k) not in EMPTY}
    answers.update(report_captured(report))  # the workflow's captures, sent with the report
    answers.update(captured_fields(events))  # live captures win; they may add workflow-defined fields
    step_path = _dict(report.data if report else None).get("step_path")
    if isinstance(step_path, list):
        step_path = [s for s in step_path if isinstance(s, str)]
    else:
        step_path = [
            name for e in events if e.type == CallEvent.STEP_ENTERED
            for name in [_dict(e.payload).get("step_name")] if isinstance(name, str) and name
        ]
    return {
        **call_row(call),
        "reason": _text(outcome.get("reason")),
        "answers": answers,
        "step_path": step_path,
        "transcript": transcript(events),
        "response_gap": response_gap_of(report),
        **recording_fields(call),
    }


def response_gap_of(report) -> dict | None:
    """The agent's response-gap summary (agent/response_gap.py), or None for calls from before it existed."""
    gap = _dict(report.data if report else None).get("response_gap")
    return gap if isinstance(gap, dict) and gap.get("n") is not None else None
