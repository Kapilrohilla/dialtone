"""Validation for "Suggest with AI" drafts. Pure functions: no database, never raise on malformed input.

Every rule returns a short, user-facing reason. The same checks run on Gemini's output (bad items are dropped), on an
author's edit (400 with the reason), and on every read against the current revision (``invalid_reason``).
"""
import hashlib
import json
import re

from voiceagents.tokens import (
    ExprToken, long_pause_errors, parse, short_pause_errors, unknown_expressions, variables,
)

from .graph import DISPOSITIONS, MAX_EXAMPLE_CHARS, MAX_EXAMPLES, MAX_LABEL_CHARS

ANSWER_STEP_TYPES = {"start", "prompt", "collect", "knowledge"}
MAX_ANSWERS_PER_STEP = 5
MAX_REASON_CHARS = 140
MAX_STEP_NAME_CHARS = 60
MAX_PROMPT_CHARS = 2000

_EXPR_RE = re.compile(r"\[\[expr:[a-z_]+(?::\d+(?:\.\d+)?)?\]\]")


class Invalid(Exception):
    """A suggestion that breaks a rule. ``field`` names the payload field for 400 responses."""

    def __init__(self, reason: str, field: str = "non_field_errors"):
        super().__init__(reason)
        self.reason = reason
        self.field = field


# -- graph helpers ---------------------------------------------------------------------------------

def _steps(graph) -> dict[str, dict]:
    steps = graph.get("steps") if isinstance(graph, dict) else None
    out: dict[str, dict] = {}
    for s in steps if isinstance(steps, list) else []:
        if isinstance(s, dict) and isinstance(s.get("id"), str) and s["id"] not in out:
            out[s["id"]] = s
    return out


def _paths(graph) -> list[dict]:
    paths = graph.get("paths") if isinstance(graph, dict) else None
    return [p for p in paths if isinstance(p, dict)] if isinstance(paths, list) else []


def _norm(text) -> str:
    return " ".join(text.split()).casefold() if isinstance(text, str) else ""


def fingerprint(graph, step_id: str) -> str:
    """Hash of a step's type, name, prompt and outgoing paths. A change marks its suggestions out of date."""
    step = _steps(graph).get(step_id)
    if step is None:
        return ""
    out = [[p.get("label"), p.get("to"), p.get("examples")] for p in _paths(graph) if p.get("from") == step_id]
    data = [step.get("type"), step.get("name"), step.get("prompt"), out]
    return hashlib.sha1(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def fingerprints(graph, step_ids) -> dict[str, str]:
    return {sid: fingerprint(graph, sid) for sid in step_ids}


def strip_expressions(text: str) -> str:
    """The words alone: every ``[[expr:…]]`` token removed, whitespace normalised."""
    return " ".join(_EXPR_RE.sub(" ", text or "").split())


# -- field checks ----------------------------------------------------------------------------------

def _text(value, field: str, limit: int, what: str, required: bool = True) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise Invalid(f"{what} must be text.", field)
    value = value.strip()
    if required and not value:
        raise Invalid(f"{what} can't be empty.", field)
    if len(value) > limit:
        raise Invalid(f"Keep {what.lower()} to {limit} characters.", field)
    return value


def _examples(value) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(e, str) for e in value):
        raise Invalid("Caller phrases must be a list of text.", "examples")
    out: list[str] = []
    for e in value:
        e = e.strip()
        if not e:
            raise Invalid("A caller phrase is empty.", "examples")
        if len(e) > MAX_EXAMPLE_CHARS:
            raise Invalid(f"Keep each caller phrase to {MAX_EXAMPLE_CHARS} characters.", "examples")
        if e.casefold() not in {x.casefold() for x in out}:
            out.append(e)
    if not out:
        raise Invalid("Add at least one thing the caller might say.", "examples")
    if len(out) > MAX_EXAMPLES:
        raise Invalid(f"Use at most {MAX_EXAMPLES} caller phrases.", "examples")
    return out


def _expression_errors(text: str, custom: dict[str, str]) -> list[str]:
    errors = [f'Unknown expression "{n}".' for n in unknown_expressions(text, custom)]
    return errors + long_pause_errors(text) + short_pause_errors(text)


# -- answers -----------------------------------------------------------------------------------------

def validate_answer(payload, graph, step_id: str, custom: dict[str, str] | None = None,
                    taken_labels=()) -> dict:
    """The cleaned answer payload, or Invalid. ``taken_labels``: labels of other pending suggestions from the step."""
    custom = custom or {}
    if not isinstance(payload, dict):
        raise Invalid("This suggestion is malformed.")
    steps = _steps(graph)
    source = steps.get(step_id)
    if source is None:
        raise Invalid("The step this came from was removed.")
    if source.get("type") not in ANSWER_STEP_TYPES:
        raise Invalid("Paths can't leave this kind of step.")

    label = _text(payload.get("label"), "label", MAX_LABEL_CHARS, "Path name")
    out_paths = [p for p in _paths(graph) if p.get("from") == step_id]
    labels = {_norm(p.get("label")) for p in out_paths} | {_norm(x) for x in taken_labels}
    if _norm(label) in labels:
        raise Invalid("A path with this name already exists. Rename it to accept.", "label")
    examples = _examples(payload.get("examples"))
    reason = _text(payload.get("reason"), "reason", MAX_REASON_CHARS, "Reason", required=False)

    target = payload.get("target")
    if not isinstance(target, dict):
        raise Invalid("Choose where this path goes.", "target")
    if "new_step" in target and target.get("new_step") is not None:
        clean_target = {"new_step": _new_step(target["new_step"], steps, custom)}
    else:
        to = target.get("step_id")
        if not isinstance(to, str) or not to:
            raise Invalid("Choose where this path goes.", "target")
        if to not in steps:
            raise Invalid("The step this pointed to was removed.", "target")
        if to == step_id:
            raise Invalid("A path can't lead back to its own step.", "target")
        if steps[to].get("type") == "start":
            raise Invalid("A path can't lead to the start step.", "target")
        if any(p.get("to") == to for p in out_paths):
            raise Invalid("This step already goes there. Add the phrases to that path instead.", "target")
        clean_target = {"step_id": to}
    return {"label": label, "examples": examples, "reason": reason, "target": clean_target}


def _new_step(new, steps: dict[str, dict], custom: dict[str, str]) -> dict:
    if not isinstance(new, dict):
        raise Invalid("The new step is malformed.", "target")
    name = _text(new.get("name"), "target", MAX_STEP_NAME_CHARS, "New step name")
    if _norm(name) in {_norm(s.get("name")) for s in steps.values()}:
        raise Invalid("A step with this name already exists. Rename the new step.", "target")
    kind = new.get("type")
    prompt = _text(new.get("prompt"), "target", MAX_PROMPT_CHARS, "What the agent says", required=False)
    errors = _expression_errors(prompt, custom)
    if errors:
        raise Invalid(errors[0], "target")
    if kind == "prompt":
        then = new.get("then")
        if not isinstance(then, dict):
            raise Invalid("Choose where to go after the new step.", "target")
        to = then.get("step_id")
        if not isinstance(to, str) or to not in steps:
            raise Invalid("The step after the new step was removed.", "target")
        if steps[to].get("type") == "start":
            raise Invalid("A path can't lead to the start step.", "target")
        label = _text(then.get("label"), "target", MAX_LABEL_CHARS, "The next path's name")
        return {"name": name, "type": "prompt", "prompt": prompt, "then": {"step_id": to, "label": label}}
    if kind == "end":
        outcome = new.get("outcome")
        if not isinstance(outcome, str) or outcome not in DISPOSITIONS:
            raise Invalid("Choose an outcome for the new end step.", "target")
        return {"name": name, "type": "end", "prompt": prompt, "outcome": outcome}
    raise Invalid("A new step must say something or end the call.", "target")


# -- expressions -------------------------------------------------------------------------------------

def _expr_tokens(text: str) -> list[ExprToken]:
    return [t for t in parse(text) if isinstance(t, ExprToken)]


def validate_expression(payload, graph, step_id: str, custom: dict[str, str] | None = None) -> dict:
    """The cleaned expression payload, or Invalid. Expressions may only be added: the words never change."""
    custom = custom or {}
    if not isinstance(payload, dict):
        raise Invalid("This suggestion is malformed.")
    step = _steps(graph).get(step_id)
    if step is None:
        raise Invalid("The step this came from was removed.")
    before, after = payload.get("before"), payload.get("after")
    if not isinstance(before, str) or not isinstance(after, str):
        raise Invalid("This suggestion is malformed.", "after")
    prompt = step.get("prompt") if isinstance(step.get("prompt"), str) else ""
    if prompt != before:
        raise Invalid("The agent's words for this step have changed.")
    after = after.strip()
    if len(after) > MAX_PROMPT_CHARS:
        raise Invalid(f"Keep what the agent says to {MAX_PROMPT_CHARS} characters.", "after")
    if strip_expressions(after) != strip_expressions(before):
        raise Invalid("This would change the agent's words.", "after")
    old, new = _expr_tokens(before), iter(_expr_tokens(after))
    if not all(any(t == n for n in new) for t in old):  # the existing expressions stay, in order
        raise Invalid("This would remove an expression the step already has.", "after")
    errors = _expression_errors(after, custom)
    if errors:
        raise Invalid(errors[0], "after")
    if after == before.strip():
        raise Invalid("This adds no expressions.", "after")
    reason = _text(payload.get("reason"), "reason", MAX_REASON_CHARS, "Reason", required=False)
    return {"before": before, "after": after, "reason": reason}


# -- step words (audit fixes) --------------------------------------------------------------------------

def validate_prompt(payload, graph, step_id: str, custom: dict[str, str] | None = None) -> dict:
    """The cleaned rewrite of a step's words, or Invalid. Used by audit fixes to shorten or rewrite a step prompt.
    The rewrite may not bring in a lead variable the step didn't already use."""
    custom = custom or {}
    if not isinstance(payload, dict):
        raise Invalid("This suggestion is malformed.")
    step = _steps(graph).get(step_id)
    if step is None:
        raise Invalid("The step this came from was removed.")
    before, after = payload.get("before"), payload.get("after")
    if not isinstance(before, str):
        raise Invalid("This suggestion is malformed.", "after")
    prompt = step.get("prompt") if isinstance(step.get("prompt"), str) else ""
    if prompt != before:
        raise Invalid("The agent's words for this step have changed.")
    after = _text(after, "after", MAX_PROMPT_CHARS, "What the agent says")
    if after == before.strip():
        raise Invalid("This doesn't change the agent's words.", "after")
    new_vars = [v for v in variables(after) if v not in variables(before)]
    if new_vars:
        raise Invalid(f'"{{{{{new_vars[0]}}}}}" isn\'t used by this step yet. Keep to the details it already uses.',
                      "after")
    errors = _expression_errors(after, custom)
    if errors:
        raise Invalid(errors[0], "after")
    reason = _text(payload.get("reason"), "reason", MAX_REASON_CHARS, "Reason", required=False)
    return {"before": before, "after": after, "reason": reason}


def validate_item(kind: str, payload, graph, step_id: str, custom=None, taken_labels=()) -> dict:
    if kind == "answer":
        return validate_answer(payload, graph, step_id, custom, taken_labels)
    if kind == "prompt":
        return validate_prompt(payload, graph, step_id, custom)
    return validate_expression(payload, graph, step_id, custom)
