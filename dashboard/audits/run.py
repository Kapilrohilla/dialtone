"""Running call audits: queue one when a call report arrives (or an editor asks), score it with Gemini in a
background thread (the dashboard has no worker queue), and re-run audits a restart left stuck.

Nothing here may break report ingest: ``queue_after_report`` runs after the report's transaction commits and
swallows every error.
"""
import hashlib
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from django.conf import settings
from django.db import close_old_connections, transaction
from django.db.models import F
from django.utils import timezone

from calls.models import Call

from . import build as build_mod
from .models import CallAudit
from .rubric import AREA_KEYS, EVENTS, RUBRIC_VERSION, rubric_text, weights_for
from .validate import Invalid, scorecard

logger = logging.getLogger(__name__)

BUDGET_S = 100.0
CALL_TIMEOUT_S = 60.0
RETRY_MIN_LEFT_S = 20.0
STALE_QUEUED = timedelta(minutes=5)  # waiting in the pool this long: lost to a restart
STALE_RUNNING = timedelta(minutes=3)  # well past BUDGET_S
MAX_ATTEMPTS = 3
SWEEP_BATCH = 20

ERROR_FAILED = "Couldn't audit this call. Try again."
ERROR_TOO_LONG = "The audit took too long. Try again."
ERROR_NO_KEY = "Audits aren't set up yet. Ask an admin to add a Google API key."
ERROR_MODEL = "The audit model isn't available. Ask an admin to check AUDIT_LLM_MODEL."

SYSTEM = f"""You audit phone calls made by an AI voice agent in India (Hindi, Hinglish and English). The goal is
to make the agent sound like a good human telecaller. Score only the AI agent's side of the call, never the caller.

Judge the language the way an Indian telecaller would: Hinglish written in Latin script and mixing Hindi and
English are normal, not defects. Short spoken sentences, "जी", "अच्छा", "ठीक है" and similar acknowledgements are
natural. Lines that read like a form, a written letter or a script read aloud are not.

Score each area from 1 to 5 using these levels:
{rubric_text()}

For every area:
- "summary": one short sentence (at most 200 characters) on why it got that score.
- "evidence": 1 to 3 items. Each item quotes a short, exact part of one AGENT line ("quote", copied character
  for character from the transcript "text", at most 150 characters) with its "line" number, says whether it is
  "good" or a "problem", and has a short "note". When the evidence is a call signal rather than words (dead air,
  interruptions, latency, mood, how the call ended), set "event" to one of {", ".join(EVENTS)}, explain it in
  "note" and leave "quote" empty. Never invent quotes, lines or numbers.

Also give:
- "summary": 2 or 3 sentences on how the agent did and the most important thing to fix.
- "moments": the top 3 good moments and the top 3 problems of the call (fewer if there aren't that many), each
  with the "line" number, an exact "quote" from that line, the rubric "area" and a short "note" saying what was
  good or wrong. A moment may quote a caller line when the problem is how the agent handled it (for example the
  agent replied to a background voice, a line clearly said to someone else near the phone).

Notes and summaries describe the agent's behaviour; don't repeat the caller's personal details. Write in English."""

_EVIDENCE = {
    "type": "object",
    "properties": {
        "line": {"type": "integer"},
        "quote": {"type": "string"},
        "kind": {"type": "string", "enum": ["good", "problem"]},
        "event": {"type": "string"},
        "note": {"type": "string"},
    },
    "required": ["line", "quote", "kind", "note"],
}
_AREA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer", "minimum": 1, "maximum": 5},
        "summary": {"type": "string"},
        "evidence": {"type": "array", "items": _EVIDENCE},
    },
    "required": ["score", "summary", "evidence"],
}
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "scores": {"type": "object", "properties": {k: _AREA for k in AREA_KEYS}, "required": AREA_KEYS},
        "moments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "line": {"type": "integer"},
                    "kind": {"type": "string", "enum": ["good", "problem"]},
                    "area": {"type": "string", "enum": AREA_KEYS},
                    "quote": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["line", "kind", "area", "quote", "note"],
            },
        },
    },
    "required": ["summary", "scores", "moments"],
}


# -- Gemini ------------------------------------------------------------------------------------------

def call_gemini(prompt: str, timeout_s: float) -> tuple[dict, dict]:
    """(parsed JSON, usage). Raises on any failure; the caller retries or stores an error."""
    from google import genai
    from google.genai import types

    model = settings.AUDIT_LLM_MODEL
    client = genai.Client(api_key=settings.GOOGLE_API_KEY,
                          http_options=types.HttpOptions(timeout=max(1000, int(timeout_s * 1000))))
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM,
        response_mime_type="application/json",
        response_json_schema=RESPONSE_SCHEMA,
        temperature=0.2,
    )
    if "flash" in model and "2.5" in model:
        config.thinking_config = types.ThinkingConfig(thinking_budget=0)
    elif model.startswith("gemini-3"):
        config.thinking_config = types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW)
    resp = client.models.generate_content(model=model, contents=prompt, config=config)
    data = json.loads(resp.text or "{}")
    if not isinstance(data, dict):
        raise ValueError("Gemini returned something other than an object")
    u = resp.usage_metadata
    usage = {"input": getattr(u, "prompt_token_count", 0) or 0, "output": getattr(u, "candidates_token_count", 0) or 0}
    return data, usage


def _transient(e: Exception) -> bool:
    """Gemini overloaded, rate limited or timed out: worth trying again later."""
    text = f"{type(e).__name__} {e}".lower()
    return any(s in text for s in ("503", "unavailable", "429", "resource_exhausted", "timeout", "timed out",
                                   "deadline"))


def _model_missing(e: Exception) -> bool:
    text = str(e).lower()
    return ("404" in text or "not_found" in text or "not found" in text) and "model" in text


# -- queueing ----------------------------------------------------------------------------------------

class Busy(Exception):
    """The call already has an audit queued or running."""


def sampled(room: str, pct: int) -> bool:
    """Whether a call is in the workspace's sample. Stable per call, so a re-sent report decides the same way."""
    if pct >= 100:
        return True
    return int(hashlib.sha1(room.encode()).hexdigest(), 16) % 100 < max(0, pct)


def _workflow_revision(version):
    from workflows.models import WorkflowRevision

    wf = (version.snapshot or {}).get("workflow") if version and isinstance(version.snapshot, dict) else None
    if not isinstance(wf, dict) or not isinstance(wf.get("id"), int) or not isinstance(wf.get("revision"), int):
        return None
    return WorkflowRevision.objects.filter(workflow_id=wf["id"], number=wf["revision"]).first()


def create(call: Call, user=None) -> CallAudit:
    """A new current audit for the call, queued (not started). Raises Busy while one is queued or running."""
    with transaction.atomic():
        call = Call.objects.select_for_update().get(pk=call.pk)
        current = CallAudit.objects.filter(call=call, is_current=True).first()
        if current is not None and current.status in CallAudit.ACTIVE:
            raise Busy()
        CallAudit.objects.filter(call=call, is_current=True).update(is_current=False)
        return CallAudit.objects.create(
            call=call, workspace_id=call.workspace_id, agent_version=call.agent_version,
            workflow_revision=_workflow_revision(call.agent_version), created_by=user,
            rubric_version=RUBRIC_VERSION, model=settings.AUDIT_LLM_MODEL,
        )


def queue_after_report(call_id: int) -> None:
    """After a report is stored: queue an audit if the workspace has audits on and the call is in the sample.
    A re-sent report never adds a second audit. Never raises."""
    try:
        call = Call.objects.select_related("workspace").filter(pk=call_id).first()
        if call is None or call.workspace is None or not call.workspace.audit_enabled:
            return
        if CallAudit.objects.filter(call=call).exists():
            return
        if not sampled(call.room, call.workspace.audit_sample_pct):
            return
        try:
            audit = create(call)
        except Busy:
            return
        start(audit.pk)
        sweep()
    except Exception:
        logger.exception("audit: could not queue an audit for call %s", call_id)


# -- the run -----------------------------------------------------------------------------------------

def _claim(audit_id: int) -> int | None:
    """QUEUED -> RUNNING; the attempt number this run owns, or None if another run has it."""
    now = timezone.now()
    n = CallAudit.objects.filter(pk=audit_id, status=CallAudit.QUEUED).update(
        status=CallAudit.RUNNING, attempts=F("attempts") + 1, started_at=now, updated_at=now)
    if not n:
        return None
    return CallAudit.objects.values_list("attempts", flat=True).get(pk=audit_id)


def _finish(audit_id: int, attempt: int, **fields) -> bool:
    """Store the result unless the sweep took the audit over meanwhile. True when stored."""
    with transaction.atomic():
        a = CallAudit.objects.select_for_update().filter(pk=audit_id).first()
        if a is None or a.status != CallAudit.RUNNING or a.attempts != attempt:
            return False
        for k, v in fields.items():
            setattr(a, k, v)
        a.finished_at = None if a.status in CallAudit.ACTIVE else timezone.now()
        a.save()
    return True


def _ask(prompt: str, inp, weights, deadline: float) -> tuple[dict, dict]:
    """(scorecard, usage). One retry when the call fails or its output doesn't hold up, if time allows."""
    tokens = {"input": 0, "output": 0}
    last: Exception | None = None
    for _ in range(2):
        left = deadline - time.monotonic()
        if last is not None and left < RETRY_MIN_LEFT_S:
            break
        try:
            data, usage = call_gemini(prompt, min(CALL_TIMEOUT_S, max(left, 1.0)))
            tokens = {k: tokens[k] + usage.get(k, 0) for k in tokens}
            return scorecard(data, inp, weights), tokens
        except Exception as e:  # noqa: BLE001 - retried once, then stored as the audit's error
            last = e
            if _model_missing(e):
                break
            logger.info("audit: attempt failed (%s: %.300s)", type(e).__name__, e)
    assert last is not None
    raise last


def run(audit_id: int) -> None:
    """Runs one audit to the end. Never raises: any failure becomes the audit's error state."""
    attempt = _claim(audit_id)
    if attempt is None:
        return
    began = time.monotonic()
    try:
        audit = CallAudit.objects.select_related("call__agent_version", "call__workspace", "workspace").get(pk=audit_id)
        inp = build_mod.build(audit.call)
        if not inp.lines:
            _finish(audit_id, attempt, status=CallAudit.SKIPPED, skipped_reason=CallAudit.NO_TRANSCRIPT)
            return
        if inp.agent_turns < build_mod.MIN_AGENT_TURNS:
            _finish(audit_id, attempt, status=CallAudit.SKIPPED, skipped_reason=CallAudit.TOO_SHORT)
            return
        if not settings.GOOGLE_API_KEY:
            _finish(audit_id, attempt, status=CallAudit.ERROR, error=ERROR_NO_KEY)
            return
        weights = weights_for(audit.workspace)
        prompt = build_mod.prompt_for(inp, audit.workspace.audit_instructions)
        card, tokens = _ask(prompt, inp, weights, began + BUDGET_S)
        stored = _finish(
            audit_id, attempt, status=CallAudit.READY, error="", weights=weights, model=settings.AUDIT_LLM_MODEL,
            tokens_in=tokens["input"], tokens_out=tokens["output"], **card,
        )
        logger.info("audit: %s ready in %.1f s, score %s, tokens in=%d out=%d%s", audit_id,
                    time.monotonic() - began, card["overall_score"], tokens["input"], tokens["output"],
                    "" if stored else " (discarded: taken over by the sweep)")
    except Exception as e:
        if isinstance(e, Invalid):
            logger.warning("audit: %s output didn't hold up: %s", audit_id, e.reason)
        else:
            logger.exception("audit: %s failed", audit_id)
        try:
            if _transient(e) and attempt < MAX_ATTEMPTS:
                # Gemini busy or slow: back in the queue; the sweep runs it again once STALE_QUEUED has passed.
                _finish(audit_id, attempt, status=CallAudit.QUEUED, error="")
            else:
                _finish(audit_id, attempt, status=CallAudit.ERROR,
                        error=ERROR_MODEL if _model_missing(e) else ERROR_FAILED)
        except Exception:
            logger.exception("audit: could not store the failure of %s", audit_id)


def _thread_main(audit_id: int) -> None:
    close_old_connections()
    try:
        run(audit_id)
    finally:
        close_old_connections()


_pool: ThreadPoolExecutor | None = None
_pool_lock = threading.Lock()


def _executor() -> ThreadPoolExecutor:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=max(1, settings.AUDIT_MAX_CONCURRENT), thread_name_prefix="audit")
        return _pool


def start(audit_id: int) -> None:
    """Runs the audit in the background pool. Tests replace this to run ``run`` inline."""
    _executor().submit(_thread_main, audit_id)


# -- stuck audits ------------------------------------------------------------------------------------

def revive(audit: CallAudit, now=None) -> bool:
    """An audit a restart (or a crash) left queued or running: queue it again, or give up after MAX_ATTEMPTS.
    True when it was changed."""
    now = now or timezone.now()
    limit = STALE_QUEUED if audit.status == CallAudit.QUEUED else STALE_RUNNING
    if audit.status not in CallAudit.ACTIVE or now - audit.updated_at < limit:
        return False
    same = CallAudit.objects.filter(pk=audit.pk, status=audit.status, updated_at=audit.updated_at)
    if audit.attempts >= MAX_ATTEMPTS:
        return bool(same.update(status=CallAudit.ERROR, error=ERROR_TOO_LONG, finished_at=now, updated_at=now))
    if not same.update(status=CallAudit.QUEUED, updated_at=now):
        return False
    start(audit.pk)
    return True


def sweep(limit: int = SWEEP_BATCH) -> int:
    """Revive stuck audits; how many were changed."""
    now = timezone.now()
    stuck = CallAudit.objects.filter(status__in=CallAudit.ACTIVE, updated_at__lt=now - min(STALE_QUEUED, STALE_RUNNING))
    return sum(1 for a in stuck.order_by("updated_at")[:limit] if revive(a, now))
