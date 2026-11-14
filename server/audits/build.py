"""Turns a finished call into what Gemini scores: the transcript with each line tagged by the workflow step that
said it, the call's signals (mood, dead air, latency, interruptions, outcome) and the workflow the call ran.

Report data and event payloads come from the agent and are never validated, so every read is defensive. The
server must not import agent code; nothing here does.
"""
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from calls.models import CallEvent, CallReport

MAX_TRANSCRIPT_CHARS = 36_000  # about 12k tokens; longer calls are trimmed in the middle
KEEP_HEAD_SHARE = 0.4  # of the budget, for the start of the call; the rest goes to the end
MAX_LINE_CHARS = 1_200
MAX_SCRIPT_CHARS = 4_000
MAX_KNOWLEDGE_CHARS = 4_000
MAX_MOOD_POINTS = 40
MIN_AGENT_TURNS = 2


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _list(value) -> list:
    return value if isinstance(value, list) else []


def _str(value) -> str:
    return value if isinstance(value, str) else ""


def _num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


@dataclass
class Line:
    i: int
    speaker: str  # "agent" | "caller"
    text: str
    at: datetime | None
    at_s: float | None
    step_id: str = ""
    step_name: str = ""


@dataclass
class AuditInput:
    lines: list[Line]
    signals: dict
    workflow: dict
    omitted: tuple[int, int] | None = None  # (first omitted line index, how many) when trimmed
    steps: dict = field(default_factory=dict)  # {step_id: name} of the workflow the call ran

    @property
    def agent_turns(self) -> int:
        return sum(1 for ln in self.lines if ln.speaker == "agent")


def _report(call):
    try:
        return call.report
    except CallReport.DoesNotExist:
        return None


def call_start(call, events) -> datetime | None:
    """Time zero for `at_s`: when the caller answered, else when the call started, else the first event."""
    if call.answered_at or call.started_at:
        return call.answered_at or call.started_at
    return events[0].at if events else None


def lines_from_events(events, t0) -> list[Line]:
    out: list[Line] = []
    step_id = step_name = ""
    for e in events:
        p = _dict(e.payload)
        if e.type == CallEvent.STEP_ENTERED:
            step_id, step_name = _str(p.get("step_id")), _str(p.get("step_name"))
        elif e.type == CallEvent.TURN:
            text = _str(p.get("text")).strip()
            speaker = _str(p.get("speaker"))
            if not text or speaker not in ("agent", "caller"):
                continue
            at_s = round(max(0.0, (e.at - t0).total_seconds()), 1) if t0 else None
            out.append(Line(len(out), speaker, text[:MAX_LINE_CHARS], e.at, at_s,
                            step_id if speaker == "agent" else "", step_name if speaker == "agent" else ""))
    return out


def lines_from_report(report, t0) -> list[Line]:
    """Fallback when the call has no turn events: the report's `turns` (sent only with mood-eval capture)."""
    out: list[Line] = []
    for t in _list(_dict(report.data if report else None).get("turns")):
        t = _dict(t)
        role, text, at_s = _str(t.get("role")), _str(t.get("text")).strip(), _num(t.get("at_s"))
        speaker = {"assistant": "agent", "user": "caller"}.get(role)
        if not speaker or not text:
            continue
        at = t0 + timedelta(seconds=at_s) if t0 and at_s is not None else None
        out.append(Line(len(out), speaker, text[:MAX_LINE_CHARS], at,
                        round(at_s, 1) if at_s is not None else None))
    return out


def trim(lines: list[Line], budget: int = MAX_TRANSCRIPT_CHARS) -> tuple[list[Line], tuple[int, int] | None]:
    """Keep the start and the end of a long call; (kept lines, (first omitted index, count) or None)."""
    if sum(len(ln.text) for ln in lines) <= budget:
        return lines, None
    head_budget = int(budget * KEEP_HEAD_SHARE)
    head, used = [], 0
    for ln in lines:
        if used + len(ln.text) > head_budget:
            break
        head.append(ln)
        used += len(ln.text)
    tail, used = [], 0
    for ln in reversed(lines[len(head):]):
        if used + len(ln.text) > budget - head_budget:
            break
        tail.append(ln)
        used += len(ln.text)
    tail.reverse()
    omitted = len(lines) - len(head) - len(tail)
    return head + tail, ((len(head), omitted) if omitted else None)


def _latency(latency: dict) -> dict:
    out = {}
    for key in ("eou", "llm_ttft", "tts_ttfb"):
        d = _dict(latency.get(key))
        vals = {k: d[k] for k in ("p50_ms", "p90_ms", "p95_ms", "n") if _num(d.get(k)) is not None}
        if vals:
            out[key] = vals
    return out


def _response_gap(gap: dict) -> dict:
    """The agent's measured reply gaps (caller stops -> agent heard), without the per-reply list."""
    out = {}
    for key in ("system", "perceived"):
        d = _dict(gap.get(key))
        vals = {k: d[k] for k in ("avg_ms", "p50_ms", "p95_ms", "max_ms") if _num(d.get(k)) is not None}
        if vals:
            out[key] = vals
    for key in ("n", "slow_replies", "slow_threshold_ms", "agent_cut_ins"):
        if _num(gap.get(key)) is not None:
            out[key] = gap[key]
    return out


def signals_of(call, report) -> dict:
    data = _dict(report.data if report else None)
    mood = _dict(data.get("mood"))
    outcome = _dict(data.get("outcome"))
    timeline = [
        {"at_s": _num(p.get("at_s")), "emotion": _str(p.get("emotion"))}
        for p in (_dict(x) for x in _list(data.get("timeline"))) if _str(p.get("emotion"))
    ][:MAX_MOOD_POINTS]
    dead_air = [
        {"action": _str(d.get("action")), "silence_s": _num(d.get("silence_s"))}
        for d in (_dict(x) for x in _list(data.get("dead_air"))) if _str(d.get("action"))
    ]
    behavior = {k: v for k, v in _dict(data.get("behavior")).items() if _num(v) is not None}
    captured = {k: v for k, v in _dict(data.get("captured")).items() if isinstance(k, str) and isinstance(v, str)}
    duration = None
    if call.ended_at and (call.answered_at or call.started_at):
        duration = max(0, int((call.ended_at - (call.answered_at or call.started_at)).total_seconds()))
    return {
        "disposition": _str(data.get("disposition")) or _str(outcome.get("disposition")),
        "outcome_summary": _str(outcome.get("summary"))[:600],
        "end_reason": call.end_reason or "",
        "duration_s": duration,
        "mood": {"final": _str(mood.get("final")), "worst": _str(mood.get("worst")),
                 "avg_sentiment": _num(mood.get("avg_sentiment")), "timeline": timeline},
        "dead_air": dead_air,
        "latency": _latency(_dict(data.get("latency"))),
        # Measured on every pipeline; prefer it to latency["llm_ttft"], which Gemini Live reports near zero.
        "response_gap": _response_gap(_dict(data.get("response_gap"))),
        "behavior": behavior,
        "captured": captured,
        "step_path": [s for s in _list(data.get("step_path")) if isinstance(s, str)],
    }


def workflow_of(version) -> tuple[dict, dict]:
    """(what the agent was set up to do, {step_id: step name}) from the call's agent version snapshot."""
    snap = _dict(version.snapshot if version else None)
    graph = _dict(_dict(snap.get("workflow")).get("graph"))
    steps = [_dict(s) for s in _list(graph.get("steps")) if isinstance(_dict(s).get("id"), str)]
    names = {s["id"]: _str(s.get("name")) or s["id"] for s in steps}
    knowledge, left = [], MAX_KNOWLEDGE_CHARS
    for doc in (_dict(d) for d in _list(snap.get("knowledge"))):
        body = (_str(doc.get("body_rendered")) or _str(doc.get("body_md")))[:left]
        if not body:
            continue
        knowledge.append({"title": _str(doc.get("title")), "body": body})
        left -= len(body)
        if left <= 0:
            break
    out = {
        "agent": _str(snap.get("name")),
        "persona": _str(snap.get("persona_name")),
        "language": _str(snap.get("language")),
        "script": _str(snap.get("script"))[:MAX_SCRIPT_CHARS],
        "knowledge": knowledge,
        "steps": [
            {"id": s["id"], "name": names[s["id"]], "type": _str(s.get("type")),
             "says": _str(s.get("prompt"))[:MAX_LINE_CHARS],
             **({"saves_answer_as": _str(s.get("field"))} if s.get("type") == "collect" else {}),
             **({"outcome": _str(s.get("outcome"))} if s.get("type") == "end" else {})}
            for s in steps
        ],
        "paths": [
            {"from": _str(p.get("from")), "to": _str(p.get("to")), "label": _str(p.get("label"))}
            for p in (_dict(x) for x in _list(graph.get("paths")))
        ],
    }
    return out, names


def build(call) -> AuditInput:
    events = list(CallEvent.objects.filter(call=call, type__in=[CallEvent.TURN, CallEvent.STEP_ENTERED])
                  .order_by("seq"))
    report = _report(call)
    t0 = call_start(call, events)
    lines = lines_from_events(events, t0) or lines_from_report(report, t0)
    workflow, names = workflow_of(call.agent_version)
    for ln in lines:  # the snapshot's name wins over the live event's (same thing, but one source)
        if ln.step_id and ln.step_id in names:
            ln.step_name = names[ln.step_id]
    kept, omitted = trim(lines)
    return AuditInput(kept, signals_of(call, report), workflow, omitted, names)


def prompt_for(inp: AuditInput, instructions: str = "") -> str:
    transcript = []
    for ln in inp.lines:
        if inp.omitted and ln.i == inp.omitted[0] + inp.omitted[1]:
            transcript.append({"note": f"{inp.omitted[1]} lines from the middle of the call are left out"})
        row = {"line": ln.i, "speaker": ln.speaker, "at_s": ln.at_s, "text": ln.text}
        if ln.step_id:
            row["step_id"] = ln.step_id
        transcript.append(row)
    data = {
        "agent_setup": inp.workflow,
        "call_signals": inp.signals,
        "transcript": transcript,
    }
    text = "Audit this call.\n\n" + json.dumps(data, ensure_ascii=False, indent=1, default=str)
    if instructions.strip():
        text += "\n\nExtra instructions from this team (follow them unless they contradict the rules):\n" + \
                instructions.strip()[:1000]
    return text
