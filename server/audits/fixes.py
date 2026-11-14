"""Audit fixes (KAP-37): turn the problems call audits found into draft workflow and agent changes.

A run (``AuditFixRun``) reads a pool of audits — one call's, or the last N of one agent version or workflow
revision — and asks Gemini for concrete fixes. Each fix must name the problems it addresses; the server then:

- validates it against the current draft with the same checks as "Suggest with AI" (``workflows/suggestions.py``,
  ``voiceagents/suggestions.py``) and drops it when it fails,
- links it to its supporting moments (call, line, quote). Purged audits count toward how often a problem appears,
  but their quotes are never sent to Gemini nor shown as evidence,
- ranks it by how many calls show the problem × how many overall points the problem's area cost those calls.

Generation runs in a background thread (the server has no worker queue). Accepting is ``apply.py``; with the
workspace's "Auto-apply audit fixes to draft" on, confident fixes seen in enough calls are accepted right away.
"""
import json
import logging
import threading
import time
from dataclasses import dataclass

from django.conf import settings
from django.db import close_old_connections, transaction
from django.utils import timezone

from voiceagents.suggestions import (
    SETTING_KEYS, current_settings, section, validate_knowledge, validate_script,
    validate_settings,
)
from voiceagents.tokens import BUILTIN_EXPRESSIONS
from workflows import suggest
from workflows.graph import DISPOSITIONS
from workflows.models import WorkflowSuggestion, WorkflowSuggestionSet
from workflows.suggestions import (
    MAX_ANSWERS_PER_STEP, Invalid, fingerprints, validate_answer, validate_expression, validate_prompt,
)

from .models import AgentSuggestion, AuditFixRun, CallAudit
from .rubric import AREA_KEYS, DEFAULT_WEIGHTS, LABELS

logger = logging.getLogger(__name__)

DEFAULT_POOL = 20
MAX_POOL = 50
MAX_PROBLEMS = 120  # problems sent to Gemini
MAX_FIXES = 10  # kept per run, best ranked first
MAX_EVIDENCE = 8  # supporting moments stored per fix
MAX_TITLE_CHARS = 90
LOW_SCORE = 3  # an area scoring this or less is a problem area
BUDGET_S = 75.0
CALL_TIMEOUT_S = 60.0
RETRY_MIN_LEFT_S = 15.0
STALE_AFTER_S = 150  # a run still "running" after this is stored as an error

ERROR_FAILED = "Couldn't suggest fixes. Try again."
ERROR_TOO_LONG = "Suggesting fixes took too long. Try again."
ERROR_NO_KEY = "Fixes aren't set up yet. Ask an admin to add a Google API key."

WORKFLOW_KINDS = (WorkflowSuggestion.ANSWER, WorkflowSuggestion.EXPRESSION, WorkflowSuggestion.PROMPT)
AGENT_KINDS = (AgentSuggestion.SCRIPT, AgentSuggestion.KNOWLEDGE, AgentSuggestion.SETTINGS)

SYSTEM = """You fix AI voice agents that make phone calls in India (Hindi, Hinglish and English). Call audits found
problems in the agent's calls. Propose concrete, ready-to-apply changes to the agent's workflow and script that
would stop these problems from happening again.

You get the agent's current draft (script sections, settings, knowledge titles), its workflow (steps, what the agent
says at each step and the paths out of each step), the rubric areas that scored low, and a list of problems, each
with an "id", the call it came from, the rubric "area", the workflow step it happened at and a note.

Group problems: when the same problem shows up in several calls (for example "the caller asks about the price at
step X and the agent loops"), propose ONE fix and list every problem id it addresses in "problem_ids". Only list ids
the fix really addresses. Never propose a fix without problem ids. Prefer few strong fixes over many weak ones: at
most 8.

Each fix has one "kind":
- "answer": add a missing answer out of a workflow step, so the caller's reply has somewhere to go (also the way to
  fix a loop or a dead end). Give "step_id", a short English "label" (at most 60 characters) and 2 to 5 "examples"
  of what callers say (each at most 40 characters, Hindi in Devanagari, Hinglish in Latin script). Prefer an
  existing step as "target_step_id"; never the start step, the step itself or a step it already goes to. Otherwise
  describe "new_step": type "prompt" with what the agent says and "then_step_id"/"then_label", or type "end" with an
  outcome.
- "expression": add expression tokens to a step's words. "after" is the step's words exactly as given, with only
  [[expr:name]] or [[expr:pause:0.6]] tokens added (allowed expressions only).
- "prompt": rewrite or shorten what the agent says at a step ("step_id", full new words in "after", at most 2000
  characters). Keep every {{lead.field}} variable it uses and add none. Keep it short and spoken.
- "script": rewrite one script section ("section_id", the full new section body in "after"). Change only what fixes
  the problem; keep the rest of the section as it is.
- "knowledge": add a short knowledge snippet for questions the agent couldn't answer ("knowledge_title" at most 120
  characters, "knowledge_body" at most 1500 characters). Never invent facts: only use facts found in the script,
  the knowledge or the workflow; if the facts aren't known, write what the agent should say instead (for example
  offer a call back) rather than inventing them.
- "settings": change the agent's "language", "persona_name", "name_pronunciation", "consent_line" or
  "mood_adaptation" (tone follows the caller's mood). Only include the settings you change.

For every fix also give a "title" (at most 90 characters, what changes, e.g. "Answer price questions at Explain the
plan"), the rubric "area" it improves, a "reason" of at most 140 characters written in lowercase, and a
"confidence" from 0 to 1 that the change fixes the problems without side effects. Write titles and reasons in
English. Don't repeat callers' personal details."""

_NEW_STEP = {
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
}
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "fixes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": list(WORKFLOW_KINDS + AGENT_KINDS)},
                    "title": {"type": "string"},
                    "area": {"type": "string", "enum": AREA_KEYS},
                    "problem_ids": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "reason": {"type": "string"},
                    "step_id": {"type": "string"},
                    "label": {"type": "string"},
                    "examples": {"type": "array", "items": {"type": "string"}},
                    "target_step_id": {"type": "string"},
                    "new_step": _NEW_STEP,
                    "after": {"type": "string"},
                    "section_id": {"type": "string"},
                    "knowledge_title": {"type": "string"},
                    "knowledge_body": {"type": "string"},
                    "settings": {
                        "type": "object",
                        "properties": {
                            "language": {"type": "string"},
                            "persona_name": {"type": "string"},
                            "name_pronunciation": {"type": "string"},
                            "consent_line": {"type": "string"},
                            "mood_adaptation": {"type": "boolean"},
                        },
                    },
                },
                "required": ["kind", "title", "area", "problem_ids", "confidence", "reason"],
            },
        },
    },
    "required": ["fixes"],
}


# -- the input pool ----------------------------------------------------------------------------------

def _ready():
    return CallAudit.objects.filter(is_current=True, status=CallAudit.READY).select_related("call")


def pool_for_version(version, limit: int) -> list[CallAudit]:
    """The last ``limit`` audited calls of exactly this agent version."""
    return list(_ready().filter(agent_version=version).order_by("-finished_at", "-id")[:limit])


def pool_for_revision(agent, revision, limit: int) -> list[CallAudit]:
    """The last ``limit`` audited calls of this agent that ran on exactly this workflow revision."""
    return list(_ready().filter(agent_version__agent=agent, workflow_revision=revision)
                .order_by("-finished_at", "-id")[:limit])


@dataclass
class Problem:
    id: str
    audit: CallAudit
    area: str
    line: int | None
    at: str
    at_s: float | None
    step_id: str
    step_name: str
    quote: str
    note: str
    event: str

    @property
    def purged(self) -> bool:
        return self.audit.quotes_purged

    def for_prompt(self, call_no: int) -> dict:
        out = {"id": self.id, "call": f"c{call_no}", "area": self.area, "step_id": self.step_id or None,
               "step_name": self.step_name or None, "note": self.note}
        if self.event:
            out["event"] = self.event
        if self.quote and not self.purged:
            out["quote"] = self.quote
        return out

    def evidence(self) -> dict:
        return {"call": self.audit.call.room, "audit_id": self.audit.id, "line": self.line, "at": self.at,
                "at_s": self.at_s, "area": self.area, "step_id": self.step_id, "step_name": self.step_name,
                "quote": self.quote, "note": self.note, "event": self.event}


def _str(v) -> str:
    return v if isinstance(v, str) else ""


def problems_of(audits: list[CallAudit]) -> list[Problem]:
    """Problem moments plus the problem evidence of low-scoring areas, one per (audit, line, area)."""
    out: list[Problem] = []
    for a in audits:
        scores = a.scores if isinstance(a.scores, dict) else {}
        raw = [m for m in (a.moments if isinstance(a.moments, list) else [])
               if isinstance(m, dict) and m.get("kind") == "problem"]
        for key in AREA_KEYS:
            s = scores.get(key) if isinstance(scores.get(key), dict) else {}
            if isinstance(s.get("score"), int) and s["score"] <= LOW_SCORE:
                raw += [{**e, "area": key} for e in s.get("evidence") or []
                        if isinstance(e, dict) and e.get("kind") == "problem"]
        seen = set()
        for m in raw:
            area = m.get("area") if m.get("area") in AREA_KEYS else None
            line = m.get("line") if isinstance(m.get("line"), int) and not isinstance(m.get("line"), bool) else None
            if area is None or (line is None and not m.get("event")):
                continue
            key = (line, _str(m.get("event")), area)
            if key in seen:
                continue
            seen.add(key)
            at_s = m.get("at_s")
            out.append(Problem(
                id="", audit=a, area=area, line=line, at=_str(m.get("at")),
                at_s=float(at_s) if isinstance(at_s, (int, float)) and not isinstance(at_s, bool) else None,
                step_id=_str(m.get("step_id")), step_name=_str(m.get("step_name")), quote=_str(m.get("quote")),
                note=_str(m.get("note"))[:300], event=_str(m.get("event")),
            ))
    out = out[:MAX_PROBLEMS]
    for i, p in enumerate(out, 1):
        p.id = f"m{i}"
    return out


def lost_points(audit: CallAudit, area: str) -> float:
    """Overall-score points (0–100) the area cost this call: its weight share × how far below 5 it scored."""
    weights = audit.weights if isinstance(audit.weights, dict) and audit.weights else DEFAULT_WEIGHTS
    scored = {k: v.get("score") for k, v in (audit.scores or {}).items()
              if isinstance(v, dict) and isinstance(v.get("score"), int)}
    total = sum(weights.get(k, 0) for k in scored)
    s = scored.get(area)
    if s is None or total <= 0:
        return 0.0
    return weights.get(area, 0) / total * (5 - s) / 4 * 100


def low_areas(audits: list[CallAudit]) -> list[dict]:
    out = []
    for key in AREA_KEYS:
        scores, summaries = [], []
        for a in audits:
            s = (a.scores or {}).get(key)
            if isinstance(s, dict) and isinstance(s.get("score"), int):
                scores.append(s["score"])
                if s["score"] <= LOW_SCORE and s.get("summary") and not a.quotes_purged and len(summaries) < 3:
                    summaries.append(_str(s["summary"])[:200])
        low = sum(1 for s in scores if s <= LOW_SCORE)
        if low:
            out.append({"area": key, "label": LABELS[key], "average": round(sum(scores) / len(scores), 1),
                        "calls_scoring_3_or_less": low, "summaries": summaries})
    return out


# -- prompt ------------------------------------------------------------------------------------------

def build_prompt(agent, graph, workflow_name: str, audits: list[CallAudit], problems: list[Problem]) -> str:
    call_no = {a.id: i for i, a in enumerate(audits, 1)}
    steps = suggest._steps(graph)
    names = {s["id"]: (s.get("name") or s["id"]) for s in steps}
    workflow = None
    if steps:
        workflow = {
            "name": workflow_name,
            "steps": [{
                "id": s["id"], "name": s.get("name") or "", "type": s.get("type"), "says": s.get("prompt") or "",
                "paths": [{"label": p.get("label") or "", "examples": p.get("examples") or [],
                           "goes_to": names.get(p.get("to"), "a missing step")}
                          for p in suggest._paths(graph) if p.get("from") == s["id"]],
            } for s in suggest.graph_order(graph)],
        }
    custom = agent.custom_expressions if isinstance(agent.custom_expressions, dict) else {}
    data = {
        "agent": {
            "name": agent.name,
            "settings": current_settings(agent),
            "script": [{"id": s.get("id"), "title": s.get("title") or "", "body": s.get("body") or ""}
                       for s in agent.script if isinstance(s, dict)] if isinstance(agent.script, list) else [],
            "knowledge": list(agent.knowledge.filter(archived=False).values_list("title", flat=True)),
        },
        "workflow": workflow,
        "allowed_expressions": {**BUILTIN_EXPRESSIONS, **custom},
        "end_outcomes": sorted(DISPOSITIONS),
        "calls_audited": len(audits),
        "low_scoring_areas": low_areas(audits),
        "problems": [p.for_prompt(call_no[p.audit.id]) for p in problems],
    }
    return "Suggest fixes for these audit problems.\n\n" + json.dumps(data, ensure_ascii=False, indent=1)


# -- Gemini ------------------------------------------------------------------------------------------

def call_gemini(prompt: str, timeout_s: float) -> tuple[dict, dict]:
    """(parsed JSON, usage). Raises on any failure; the caller retries once or stores an error."""
    from google import genai
    from google.genai import types

    model = settings.AUDIT_LLM_MODEL
    client = genai.Client(api_key=settings.GOOGLE_API_KEY,
                          http_options=types.HttpOptions(timeout=max(1000, int(timeout_s * 1000))))
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM,
        response_mime_type="application/json",
        response_json_schema=RESPONSE_SCHEMA,
        temperature=0.3,
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


def _ask(prompt: str, deadline: float) -> tuple[dict, dict]:
    try:
        return call_gemini(prompt, min(CALL_TIMEOUT_S, max(deadline - time.monotonic(), 1.0)))
    except Exception:
        left = deadline - time.monotonic()
        if left < RETRY_MIN_LEFT_S:
            raise
        logger.info("audit fixes: retrying with %.1f s left", left)
        return call_gemini(prompt, min(CALL_TIMEOUT_S, left))


# -- turning Gemini's output into fixes ----------------------------------------------------------------

@dataclass
class Fix:
    target: str  # "workflow" | "agent"
    kind: str
    step_id: str  # workflow fixes only
    payload: dict
    audit: dict  # see WorkflowSuggestion.audit

    @property
    def rank(self) -> float:
        return self.audit["rank_score"]


def _short(text, limit: int) -> str:
    text = " ".join(text.split()) if isinstance(text, str) else ""
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _payload(raw: dict, agent, graph, custom: dict, taken: dict[str, list[str]]) -> tuple[str, str, dict]:
    """(target, step_id, cleaned payload) for one raw fix, or Invalid."""
    kind = raw.get("kind")
    reason = _short(raw.get("reason"), 140)
    if kind in WORKFLOW_KINDS:
        if not graph.get("steps"):
            raise Invalid("The agent has no workflow.")
        sid = raw.get("step_id")
        if not isinstance(sid, str) or not sid:
            raise Invalid("No step.")
        if kind == WorkflowSuggestion.ANSWER:
            if len(taken.setdefault(sid, [])) >= MAX_ANSWERS_PER_STEP:
                raise Invalid("Too many answers for one step.")
            payload = validate_answer({**suggest.answer_payload(raw), "reason": reason}, graph, sid, custom, taken[sid])
            taken[sid].append(payload["label"])
            return "workflow", sid, payload
        step = next((s for s in suggest._steps(graph) if s["id"] == sid), None)
        if step is None:
            raise Invalid("The step this came from was removed.")
        body = {"before": step.get("prompt") or "", "after": raw.get("after"), "reason": reason}
        check = validate_expression if kind == WorkflowSuggestion.EXPRESSION else validate_prompt
        return "workflow", sid, check(body, graph, sid, custom)
    if kind == AgentSuggestion.SCRIPT:
        s = section(agent, raw.get("section_id"))
        body = {"section_id": raw.get("section_id"), "before": s["body"] if s else None, "after": raw.get("after"),
                "reason": reason}
        return "agent", "", validate_script(body, agent)
    if kind == AgentSuggestion.KNOWLEDGE:
        body = {"title": raw.get("knowledge_title"), "body": raw.get("knowledge_body"), "reason": reason}
        return "agent", "", validate_knowledge(body, agent)
    if kind == AgentSuggestion.SETTINGS:
        wanted = raw.get("settings") if isinstance(raw.get("settings"), dict) else {}
        changes = {k: v for k, v in wanted.items() if k in SETTING_KEYS and v is not None}
        current = current_settings(agent)
        return "agent", "", validate_settings(
            {"changes": changes, "before": {k: current[k] for k in changes}, "reason": reason}, agent)
    raise Invalid("Unknown kind.")


def _dedupe_key(fix: Fix):
    p = fix.payload
    if fix.kind == WorkflowSuggestion.ANSWER:
        return None  # labels are kept apart by validate_answer's taken labels
    if fix.kind in (WorkflowSuggestion.EXPRESSION, WorkflowSuggestion.PROMPT):
        return ("step", fix.step_id)  # one change to a step's words per run
    if fix.kind == AgentSuggestion.SCRIPT:
        return ("section", p["section_id"])
    if fix.kind == AgentSuggestion.KNOWLEDGE:
        return ("knowledge", p["title"].casefold())
    return ("settings",)


def fixes_from(data: dict, agent, graph, custom: dict, audits: list[CallAudit],
               problems: list[Problem]) -> tuple[list[Fix], int]:
    """(valid fixes ranked best first, how many were dropped)."""
    by_id = {p.id: p for p in problems}
    raws = data.get("fixes") if isinstance(data.get("fixes"), list) else []
    candidates: list[tuple[float, dict, list[Problem]]] = []
    dropped = 0
    for raw in raws:
        if not isinstance(raw, dict):
            dropped += 1
            continue
        ids = raw.get("problem_ids") if isinstance(raw.get("problem_ids"), list) else []
        support = list({i: by_id[i] for i in ids if isinstance(i, str) and i in by_id}.values())
        if not any(not p.purged for p in support):
            dropped += 1  # every fix links back to moments; purged quotes can't be that evidence
            continue
        area = raw.get("area") if raw.get("area") in AREA_KEYS else max(
            AREA_KEYS, key=lambda k: sum(1 for p in support if p.area == k))
        calls = {p.audit.id: p.audit for p in support}
        cost = sum(lost_points(a, area) for a in calls.values()) / len(calls)
        candidates.append((round(len(calls) * cost, 1), {**raw, "area": area}, support))
    candidates.sort(key=lambda c: -c[0])

    taken: dict[str, list[str]] = {}
    seen = set()
    out: list[Fix] = []
    for rank, raw, support in candidates:
        try:
            target, sid, payload = _payload(raw, agent, graph, custom, taken)
        except Invalid as e:
            logger.info("audit fixes: dropped a %s fix: %s", raw.get("kind"), e.reason)
            dropped += 1
            continue
        calls = {p.audit.id for p in support}
        conf = raw.get("confidence")
        fix = Fix(target=target, kind=raw["kind"], step_id=sid, payload=payload, audit={
            "title": _short(raw.get("title"), MAX_TITLE_CHARS) or LABELS[raw["area"]],
            "area": raw["area"],
            "calls": len(calls),
            "purged_calls": len({p.audit.id for p in support if p.purged}),
            "pool": len(audits),
            "score_cost": round(rank / len(calls), 1),
            "rank_score": rank,
            "confidence": round(max(0.0, min(1.0, float(conf))), 2)
            if isinstance(conf, (int, float)) and not isinstance(conf, bool) else 0.0,
            "evidence": [p.evidence() for p in support if not p.purged][:MAX_EVIDENCE],
        })
        key = _dedupe_key(fix)
        if key is not None and key in seen:
            dropped += 1
            continue
        if key is not None:
            seen.add(key)
        out.append(fix)
    if len(out) > MAX_FIXES:
        dropped += len(out) - MAX_FIXES
        out = out[:MAX_FIXES]
    return out, dropped


# -- the run -----------------------------------------------------------------------------------------

def _finish(run_id: int, status: str, error: str = "", fixes=(), workflow=None, base=None, dropped: int = 0,
            tokens=None) -> AuditFixRun | None:
    """Store the result unless the run timed out meanwhile. The stored run, or None."""
    tokens = tokens or {"input": 0, "output": 0}
    now = timezone.now()
    with transaction.atomic():
        run = AuditFixRun.objects.select_for_update().filter(pk=run_id).first()
        if run is None or run.status != AuditFixRun.RUNNING:
            return None
        wf_fixes = [f for f in fixes if f.target == "workflow"]
        if wf_fixes and workflow is not None and base is not None:
            sids = list(dict.fromkeys(f.step_id for f in wf_fixes))
            s = WorkflowSuggestionSet.objects.create(
                workflow=workflow, base_revision=base, scope=WorkflowSuggestionSet.WORKFLOW,
                source=WorkflowSuggestionSet.AUDIT, audit_run=run, status=WorkflowSuggestionSet.READY,
                kinds=sorted({f.kind for f in wf_fixes}), step_ids=sids, total_steps=len(sids),
                step_fingerprints=fingerprints(base.graph, sids), model=run.model, created_by=run.created_by,
                finished_at=now,
            )
            WorkflowSuggestion.objects.bulk_create([
                WorkflowSuggestion(suggestion_set=s, kind=f.kind, step_id=f.step_id, payload=f.payload, audit=f.audit)
                for f in wf_fixes])
        AgentSuggestion.objects.bulk_create([
            AgentSuggestion(run=run, agent_id=run.agent_id, kind=f.kind, payload=f.payload, audit=f.audit)
            for f in fixes if f.target == "agent"])
        run.status, run.error, run.dropped, run.finished_at = status, error, dropped, now
        run.tokens_in, run.tokens_out = tokens["input"], tokens["output"]
        run.save(update_fields=["status", "error", "dropped", "finished_at", "tokens_in", "tokens_out"])
    return run


def ranked_items(run: AuditFixRun) -> list:
    """The run's workflow and agent fixes, best ranked first."""
    items: list = list(AgentSuggestion.objects.filter(run=run))
    s = WorkflowSuggestionSet.objects.filter(audit_run=run).first()
    if s is not None:
        items += list(s.items.all())
    return sorted(items, key=lambda i: (-(i.audit or {}).get("rank_score", 0), i.id))


def auto_apply(run: AuditFixRun) -> int:
    """With "Auto-apply audit fixes to draft" on: accept the fixes that pass validation now and are confident
    enough and seen in enough calls. Draft only; publishing stays a person's step. How many were applied."""
    from .apply import ApplyError, apply_agent_item, apply_workflow_item

    if not run.workspace.audit_fix_auto_apply:
        return 0
    n = 0
    for item in ranked_items(run):
        meta = item.audit or {}
        if meta.get("confidence", 0) < settings.AUDIT_FIX_AUTO_MIN_CONFIDENCE \
                or meta.get("calls", 0) < settings.AUDIT_FIX_AUTO_MIN_CALLS:
            continue
        try:
            if isinstance(item, AgentSuggestion):
                apply_agent_item(item, None, auto=True)
            else:
                apply_workflow_item(item, None, auto=True)
            n += 1
        except ApplyError as e:
            logger.info("audit fixes: auto-apply skipped %s %s: %s", type(item).__name__, item.pk, e.reason)
    if n:
        AuditFixRun.objects.filter(pk=run.pk).update(auto_applied=n)
    return n


def generate(run_id: int) -> None:
    """Runs one audit-fix run to the end. Never raises: any failure becomes the run's error state."""
    began = time.monotonic()
    try:
        run = AuditFixRun.objects.select_related("agent__workflow", "workspace").get(pk=run_id)
        if not settings.GOOGLE_API_KEY:
            _finish(run_id, AuditFixRun.ERROR, ERROR_NO_KEY)
            return
        audits = list(CallAudit.objects.filter(pk__in=run.audit_ids, status=CallAudit.READY)
                      .select_related("call").order_by("-finished_at", "-id"))
        problems = problems_of(audits)
        if not problems:
            _finish(run_id, AuditFixRun.EMPTY)
            return
        agent = run.agent
        wf = agent.workflow if agent.workflow_id and not agent.workflow.archived else None
        base = wf.current if wf is not None else None
        graph = base.graph if base is not None and isinstance(base.graph, dict) else {"steps": [], "paths": []}
        custom = suggest.custom_expressions_for(wf) if wf is not None else {}
        if isinstance(agent.custom_expressions, dict):
            custom = {**custom, **agent.custom_expressions}
        prompt = build_prompt(agent, graph, wf.name if wf else "", audits, problems)
        data, usage = _ask(prompt, began + BUDGET_S)
        fixes, dropped = fixes_from(data, agent, graph, custom, audits, problems)
        status = AuditFixRun.READY if fixes else AuditFixRun.EMPTY
        stored = _finish(run_id, status, "", fixes, wf, base, dropped, usage)
        applied = auto_apply(stored) if stored is not None and fixes else 0
        logger.info("audit fixes: run %s %s in %.1f s, %d audits, %d problems, %d fixes, %d dropped, %d auto-applied,"
                    " tokens in=%d out=%d%s", run_id, status, time.monotonic() - began, len(audits), len(problems),
                    len(fixes), dropped, applied, usage.get("input", 0), usage.get("output", 0),
                    "" if stored else " (discarded: timed out)")
    except Exception:
        logger.exception("audit fixes: run %s failed", run_id)
        try:
            _finish(run_id, AuditFixRun.ERROR, ERROR_FAILED)
        except Exception:
            logger.exception("audit fixes: could not store the failure of run %s", run_id)


def _thread_main(run_id: int) -> None:
    close_old_connections()
    try:
        generate(run_id)
    finally:
        close_old_connections()


def start(run_id: int) -> None:
    """Starts generation in the background. Tests replace this to run ``generate`` inline."""
    threading.Thread(target=_thread_main, args=(run_id,), name=f"audit-fixes-{run_id}", daemon=True).start()


def expire_if_stuck(run: AuditFixRun) -> AuditFixRun:
    """A run still going after STALE_AFTER_S (lost to a restart, or just slow) is stored as an error."""
    if run.status == AuditFixRun.RUNNING and (timezone.now() - run.created_at).total_seconds() > STALE_AFTER_S:
        AuditFixRun.objects.filter(pk=run.pk, status=AuditFixRun.RUNNING).update(
            status=AuditFixRun.ERROR, error=ERROR_TOO_LONG, finished_at=timezone.now())
        run.refresh_from_db()
    return run


def runs_today(workspace) -> int:
    """Runs the workspace started today (TIME_ZONE); failed runs don't count."""
    return AuditFixRun.objects.filter(workspace=workspace, created_at__date=timezone.localdate()) \
        .exclude(status=AuditFixRun.ERROR).exclude(error__gt="").count()


def purge_fix_quotes(audit_ids) -> int:
    """Blank the quotes copied from these (just purged) audits into fix evidence. How many fixes changed."""
    ids = set(audit_ids)
    if not ids:
        return 0
    n = 0
    for model in (AgentSuggestion, WorkflowSuggestion):
        for item in model.objects.exclude(audit={}).only("id", "audit").iterator():
            evidence = (item.audit or {}).get("evidence") or []
            if any(isinstance(e, dict) and e.get("audit_id") in ids and e.get("quote") for e in evidence):
                item.audit["evidence"] = [{**e, "quote": ""} if isinstance(e, dict) and e.get("audit_id") in ids
                                          else e for e in evidence]
                model.objects.filter(pk=item.pk).update(audit=item.audit)
                n += 1
    return n
