"""Generation for "Suggest with AI": asks Gemini for other caller answers and for expressions, one run at a time.

A run is a ``WorkflowSuggestionSet``. The view creates it and calls ``start(set_id)``, which generates in a background
thread (the dashboard has no worker queue). Everything Gemini returns is validated (``suggestions.py``) and stored as
pending drafts; the workflow itself is never touched here.
"""
import json
import logging
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.db import close_old_connections, transaction
from django.utils import timezone

from voiceagents.tokens import BUILTIN_EXPRESSIONS

from .graph import DISPOSITIONS
from .models import WorkflowSuggestion, WorkflowSuggestionSet
from .suggestions import (
    ANSWER_STEP_TYPES, MAX_ANSWERS_PER_STEP, MAX_EXAMPLE_CHARS, MAX_EXAMPLES, MAX_REASON_CHARS, Invalid,
    validate_answer, validate_expression,
)

logger = logging.getLogger(__name__)

MAX_STEPS = 20  # "Whole workflow" looks at this many steps at most
BATCH_SIZE = 5
MAX_CONCURRENT = 4
BUDGET_S = 30.0
CALL_TIMEOUT_S = 20.0
RETRY_MIN_LEFT_S = 8.0
STALE_AFTER_S = 45  # a run still "running" after this is reported (and stored) as an error

ERROR_FAILED = "Couldn't get suggestions."
ERROR_TOO_LONG = "Took too long."
ERROR_NO_KEY = "Suggestions aren't set up yet. Ask an admin to add a Google API key."

SYSTEM = """You help people improve voice-agent workflows for phone calls in India (Hindi, Hinglish and English).
A workflow is a graph of steps. At each step the agent says something, then picks one path out of the step by its
name and example caller phrases. If no path fits what the caller said, the call gets stuck, so every step must
cover the answers callers really give.

You get some steps of one workflow. For each step, do only what its "suggest" list asks:

"answers": propose other answers callers give that no existing path out of the step covers yet.
- Write caller phrases the way callers actually speak: Hindi in Devanagari, Hinglish in Latin script, short and
  natural ("पता नहीं", "apply किया है", "पहले job बताओ"). 2 to 5 phrases per answer, each at most 40 characters.
- The path name (label) is a short description of the answer, at most 60 characters, in English.
- Do not repeat an answer an existing path already covers.
- Prefer an existing step as the target (target_step_id). Never target the start step, the step itself, or a step
  the step already goes to. Only when no step fits, describe a new step (new_step): type "prompt" with what the
  agent says and where to go after it (then_step_id, then_label), or type "end" with an outcome.
- At most 5 answers per step.

"expressions": suggest where expression tokens would make the agent's words sound more human.
- Return the step's words in "after" exactly as given, only with tokens added: [[expr:name]] or [[expr:pause:0.6]]
  (pause seconds between 0.2 and 10). Never change, add, remove or reorder a word, a variable or an existing token.
- Use only the allowed expressions. Use them sparingly: one or two per step.

Give a reason of at most 140 characters for each suggestion, written in lowercase like "callers often don't know
their licence type.". Return nothing for a step rather than filler."""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "answers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "step_id": {"type": "string"},
                    "label": {"type": "string"},
                    "examples": {"type": "array", "items": {"type": "string"}},
                    "reason": {"type": "string"},
                    "target_step_id": {"type": "string"},
                    "new_step": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "type": {"type": "string", "enum": ["prompt", "end"]},
                            "prompt": {"type": "string"},
                            "outcome": {"type": "string", "enum": sorted(DISPOSITIONS)},
                            "then_step_id": {"type": "string"},
                            "then_label": {"type": "string"},
                        },
                        "required": ["name", "type", "prompt"],
                    },
                },
                "required": ["step_id", "label", "examples", "reason"],
            },
        },
        "expressions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"step_id": {"type": "string"}, "after": {"type": "string"},
                               "reason": {"type": "string"}},
                "required": ["step_id", "after", "reason"],
            },
        },
    },
    "required": ["answers", "expressions"],
}


# -- what to look at ---------------------------------------------------------------------------------

def _steps(graph) -> list[dict]:
    steps = graph.get("steps") if isinstance(graph, dict) else None
    out, seen = [], set()
    for s in steps if isinstance(steps, list) else []:
        if isinstance(s, dict) and isinstance(s.get("id"), str) and s["id"] not in seen:
            seen.add(s["id"])
            out.append(s)
    return out


def _paths(graph) -> list[dict]:
    paths = graph.get("paths") if isinstance(graph, dict) else None
    return [p for p in paths if isinstance(p, dict)] if isinstance(paths, list) else []


def wants(step: dict, kinds) -> list[str]:
    """What can be suggested for a step: answers for question-like steps, expressions for steps that say something."""
    out = []
    if "answers" in kinds and step.get("type") in ANSWER_STEP_TYPES:
        out.append("answers")
    if "expressions" in kinds and isinstance(step.get("prompt"), str) and step["prompt"].strip():
        out.append("expressions")
    return out


def graph_order(graph) -> list[dict]:
    """Steps from the start step outwards (breadth first), then any the start doesn't reach, in list order."""
    steps = _steps(graph)
    by_id = {s["id"]: s for s in steps}
    out: dict[str, list[str]] = {}
    for p in _paths(graph):
        if isinstance(p.get("from"), str) and isinstance(p.get("to"), str) and p["to"] in by_id:
            out.setdefault(p["from"], []).append(p["to"])
    order: list[str] = []
    seen: set[str] = set()
    queue = deque(s["id"] for s in steps if s.get("type") == "start")
    while queue:
        sid = queue.popleft()
        if sid in seen:
            continue
        seen.add(sid)
        order.append(sid)
        queue.extend(out.get(sid, []))
    order += [s["id"] for s in steps if s["id"] not in seen]
    return [by_id[sid] for sid in order]


def steps_to_check(graph, scope: str, step_id: str | None, kinds) -> tuple[list[str], int]:
    """(step ids to send, how many could have been sent)."""
    if scope == WorkflowSuggestionSet.STEP:
        step = next((s for s in _steps(graph) if s["id"] == step_id), None)
        return ([step_id], 1) if step is not None and wants(step, kinds) else ([], 1)
    eligible = [s["id"] for s in graph_order(graph) if wants(s, kinds)]
    return eligible[:MAX_STEPS], len(eligible)


def custom_expressions_for(workflow) -> dict[str, str]:
    """Custom expressions of the agents using this workflow (they decide what a token means at call time)."""
    out: dict[str, str] = {}
    for agent in workflow.agents.exclude(status="archived"):
        if isinstance(agent.custom_expressions, dict):
            out.update({k: v for k, v in agent.custom_expressions.items() if isinstance(k, str) and isinstance(v, str)})
    return out


def language_for(workflow) -> str:
    agent = workflow.agents.exclude(status="archived").order_by("-status", "-updated_at").first()
    return agent.language if agent else "Hindi + Hinglish"


# -- prompt ------------------------------------------------------------------------------------------

def build_prompt(graph, workflow_name: str, batch: list[str], kinds, custom: dict[str, str], language: str) -> str:
    steps = {s["id"]: s for s in _steps(graph)}
    names = {sid: (s.get("name") or sid) for sid, s in steps.items()}
    looked_at = []
    for sid in batch:
        s = steps.get(sid)
        if s is None:
            continue
        looked_at.append({
            "id": sid,
            "name": s.get("name") or "",
            "type": s.get("type"),
            "says": s.get("prompt") or "",
            "saves_answer_as": s.get("field") if s.get("type") == "collect" else None,
            "paths": [
                {"label": p.get("label") or "", "examples": p.get("examples") or [],
                 "goes_to": names.get(p.get("to"), "a missing step")}
                for p in _paths(graph) if p.get("from") == sid
            ],
            "suggest": wants(s, kinds),
        })
    data = {
        "workflow": workflow_name,
        "language": language,
        "all_steps": [{"id": sid, "name": names[sid], "type": s.get("type")} for sid, s in steps.items()],
        "allowed_expressions": {**{n: h for n, h in BUILTIN_EXPRESSIONS.items()}, **custom},
        "end_outcomes": sorted(DISPOSITIONS),
        "steps_to_improve": looked_at,
    }
    return "Improve these workflow steps.\n\n" + json.dumps(data, ensure_ascii=False, indent=1)


# -- Gemini ------------------------------------------------------------------------------------------

def call_gemini(prompt: str, timeout_s: float) -> tuple[dict, dict]:
    """(parsed JSON, usage). Raises on any failure; the caller retries or drops the batch."""
    from google import genai
    from google.genai import types

    model = settings.SUGGEST_LLM_MODEL
    client = genai.Client(api_key=settings.GOOGLE_API_KEY,
                          http_options=types.HttpOptions(timeout=max(1000, int(timeout_s * 1000))))
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM,
        response_mime_type="application/json",
        response_json_schema=RESPONSE_SCHEMA,
        temperature=0.4,
    )
    # Keep a run well inside the 30 s budget: with default thinking a batch can take longer than the whole run.
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


def _call_with_budget(prompt: str, deadline: float) -> tuple[dict, dict]:
    left = deadline - time.monotonic()
    try:
        return call_gemini(prompt, min(CALL_TIMEOUT_S, max(left, 1.0)))
    except Exception:
        left = deadline - time.monotonic()
        if left < RETRY_MIN_LEFT_S:
            raise
        logger.info("suggest: retrying a batch with %.1f s left", left)
        return call_gemini(prompt, min(CALL_TIMEOUT_S, left))


# -- turning Gemini's output into drafts ---------------------------------------------------------------

def _lenient_examples(value) -> list[str]:
    out: list[str] = []
    for e in value if isinstance(value, list) else []:
        if isinstance(e, str):
            e = e.strip()
            if e and len(e) <= MAX_EXAMPLE_CHARS and e not in out:
                out.append(e)
    return out[:MAX_EXAMPLES]


def _short(text) -> str:
    text = text.strip() if isinstance(text, str) else ""
    return text if len(text) <= MAX_REASON_CHARS else text[: MAX_REASON_CHARS - 1].rstrip() + "…"


def answer_payload(raw: dict) -> dict:
    """Gemini's flat answer as a stored payload (see the PRD), before validation."""
    target: dict
    if isinstance(raw.get("target_step_id"), str) and raw["target_step_id"]:
        target = {"step_id": raw["target_step_id"]}
    else:
        new = raw.get("new_step") if isinstance(raw.get("new_step"), dict) else {}
        target = {"new_step": {"name": new.get("name"), "type": new.get("type"), "prompt": new.get("prompt") or ""}}
        if new.get("type") == "end":
            target["new_step"]["outcome"] = new.get("outcome")
        else:
            target["new_step"]["then"] = {"step_id": new.get("then_step_id"), "label": new.get("then_label")}
    label = raw.get("label")
    return {"label": label.strip() if isinstance(label, str) else label,
            "examples": _lenient_examples(raw.get("examples")), "reason": _short(raw.get("reason")), "target": target}


def drafts_from(data: dict, graph, batch: list[str], kinds, custom: dict[str, str],
                taken: dict[str, list[str]], new_names: set[str]) -> list[tuple[str, str, dict]]:
    """Valid (kind, step_id, payload) drafts from one batch's output; invalid ones are dropped and logged.

    ``taken`` (labels per step) and ``new_names`` (new step names) carry across batches of the same run.
    """
    steps = {s["id"]: s for s in _steps(graph)}
    out: list[tuple[str, str, dict]] = []
    dropped = 0
    answers = data.get("answers") if isinstance(data.get("answers"), list) else []
    for raw in answers:
        sid = raw.get("step_id") if isinstance(raw, dict) else None
        if sid not in batch or "answers" not in wants(steps.get(sid, {}), kinds):
            dropped += 1
            continue
        if len(taken.setdefault(sid, [])) >= MAX_ANSWERS_PER_STEP:
            dropped += 1
            continue
        try:
            payload = validate_answer(answer_payload(raw), graph, sid, custom, taken[sid])
        except Invalid as e:
            logger.info("suggest: dropped an answer for %s: %s", sid, e.reason)
            dropped += 1
            continue
        new = payload["target"].get("new_step")
        if new is not None:
            if new["name"].casefold() in new_names:
                dropped += 1
                continue
            new_names.add(new["name"].casefold())
        taken[sid].append(payload["label"])
        out.append((WorkflowSuggestion.ANSWER, sid, payload))
    expressions = data.get("expressions") if isinstance(data.get("expressions"), list) else []
    done: set[str] = set()
    for raw in expressions:
        sid = raw.get("step_id") if isinstance(raw, dict) else None
        if sid not in batch or sid in done or "expressions" not in wants(steps.get(sid, {}), kinds):
            dropped += 1
            continue
        payload = {"before": steps[sid].get("prompt") or "", "after": raw.get("after"), "reason": _short(raw.get("reason"))}
        try:
            payload = validate_expression(payload, graph, sid, custom)
        except Invalid as e:
            logger.info("suggest: dropped an expression for %s: %s", sid, e.reason)
            dropped += 1
            continue
        done.add(sid)
        out.append((WorkflowSuggestion.EXPRESSION, sid, payload))
    if dropped:
        logger.info("suggest: dropped %d invalid suggestions", dropped)
    return out


# -- the run -----------------------------------------------------------------------------------------

def _finish(set_id: int, status: str, error: str = "", items=(), failed=()) -> bool:
    """Stores the result unless the run was closed or timed out meanwhile. True when stored."""
    with transaction.atomic():
        s = WorkflowSuggestionSet.objects.select_for_update().filter(pk=set_id).first()
        if s is None or s.status != WorkflowSuggestionSet.RUNNING:
            return False
        WorkflowSuggestion.objects.bulk_create(
            [WorkflowSuggestion(suggestion_set=s, kind=k, step_id=sid, payload=p) for k, sid, p in items])
        s.status, s.error, s.failed_step_ids, s.finished_at = status, error, list(failed), timezone.now()
        s.save(update_fields=["status", "error", "failed_step_ids", "finished_at"])
    return True


def generate(set_id: int) -> None:
    """Runs one suggestion set to the end. Never raises: any failure becomes the set's error state."""
    began = time.monotonic()
    deadline = began + BUDGET_S
    try:
        s = WorkflowSuggestionSet.objects.select_related("workflow", "base_revision").get(pk=set_id)
        if not settings.GOOGLE_API_KEY:
            _finish(set_id, WorkflowSuggestionSet.ERROR, ERROR_NO_KEY)
            return
        graph = s.base_revision.graph
        custom = custom_expressions_for(s.workflow)
        language = language_for(s.workflow)
        batches = [s.step_ids[i:i + BATCH_SIZE] for i in range(0, len(s.step_ids), BATCH_SIZE)]
        prompts = [build_prompt(graph, s.workflow.name, b, s.kinds, custom, language) for b in batches]

        def run(prompt):
            try:
                return _call_with_budget(prompt, deadline)
            except Exception as e:  # noqa: BLE001 - a failed batch is dropped, never fatal
                logger.warning("suggest: a batch failed: %s: %.300s", type(e).__name__, e)
                return None

        if prompts:
            with ThreadPoolExecutor(max_workers=MAX_CONCURRENT) as pool:
                results = list(pool.map(run, prompts))
        else:
            results = []
        items: list[tuple[str, str, dict]] = []
        failed: list[str] = []
        taken: dict[str, list[str]] = {}
        new_names: set[str] = set()
        tokens = {"input": 0, "output": 0}
        for batch, result in zip(batches, results):
            if result is None:
                failed += batch
                continue
            data, usage = result
            tokens = {k: tokens[k] + usage.get(k, 0) for k in tokens}
            items += drafts_from(data, graph, batch, s.kinds, custom, taken, new_names)
        if batches and len(failed) == len(s.step_ids):
            status, error = WorkflowSuggestionSet.ERROR, ERROR_FAILED
        else:
            status, error = (WorkflowSuggestionSet.READY if items else WorkflowSuggestionSet.EMPTY), ""
        stored = _finish(set_id, status, error, items, failed)
        logger.info(
            "suggest: set %s %s in %.1f s, %d steps, %d failed, %d items, tokens in=%d out=%d%s",
            set_id, status, time.monotonic() - began, len(s.step_ids), len(failed), len(items),
            tokens["input"], tokens["output"], "" if stored else " (discarded: closed or timed out)",
        )
    except Exception:
        logger.exception("suggest: set %s failed", set_id)
        try:
            _finish(set_id, WorkflowSuggestionSet.ERROR, ERROR_FAILED)
        except Exception:
            logger.exception("suggest: could not store the failure of set %s", set_id)


def _thread_main(set_id: int) -> None:
    close_old_connections()
    try:
        generate(set_id)
    finally:
        close_old_connections()


def start(set_id: int) -> None:
    """Starts generation in the background. Tests replace this to run ``generate`` inline."""
    threading.Thread(target=_thread_main, args=(set_id,), name=f"suggest-{set_id}", daemon=True).start()


def expire_if_stuck(s: WorkflowSuggestionSet) -> WorkflowSuggestionSet:
    """A run still going after 45 s (lost to a restart, or just slow) is stored as an error."""
    if s.status == WorkflowSuggestionSet.RUNNING and \
            (timezone.now() - s.created_at).total_seconds() > STALE_AFTER_S:
        WorkflowSuggestionSet.objects.filter(pk=s.pk, status=WorkflowSuggestionSet.RUNNING).update(
            status=WorkflowSuggestionSet.ERROR, error=ERROR_TOO_LONG, finished_at=timezone.now())
        s.refresh_from_db()
    return s
