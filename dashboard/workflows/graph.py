"""Workflow graph validation. Returns human-readable errors; never raises on malformed input."""
import re
from collections import deque

from voiceagents.tokens import long_pause_errors, unknown_expressions

DISPOSITIONS = {
    "INTERESTED", "NI", "NE", "CBR", "CDRP", "ISUDO", "ISUID", "HND", "WRGN",
    "OWNVA", "ABULR", "LANGUAGE_BARRIER", "NOT_CONNECTED", "UNRESOLVED",
}
STEP_TYPES = {"start", "prompt", "collect", "knowledge", "transfer", "end"}
FIELD_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
MAX_LABEL_CHARS = 60
MAX_EXAMPLES = 5
MAX_EXAMPLE_CHARS = 40


def example_errors(examples) -> list[str]:
    """Problems with a path's optional caller phrases (``examples``); empty when they are fine."""
    if examples is None:
        return []
    if not isinstance(examples, list) or not all(isinstance(e, str) for e in examples):
        return ["Caller phrases must be a list of text."]
    errors: list[str] = []
    if len(examples) > MAX_EXAMPLES:
        errors.append(f"Use at most {MAX_EXAMPLES} caller phrases.")
    if any(not e.strip() for e in examples):
        errors.append("A caller phrase is empty.")
    if any(len(e.strip()) > MAX_EXAMPLE_CHARS for e in examples):
        errors.append(f"Keep each caller phrase to {MAX_EXAMPLE_CHARS} characters.")
    return errors


def _label(step: dict) -> str:
    name = step.get("name")
    return name if isinstance(name, str) and name.strip() else str(step.get("id"))


def validate(graph, knowledge_ids: set[int], custom_expressions: dict[str, str] | None = None) -> list[str]:
    custom = custom_expressions or {}
    if not isinstance(graph, dict):
        return ["The workflow graph must be an object with steps and paths."]
    steps, paths = graph.get("steps"), graph.get("paths")
    if not isinstance(steps, list):
        return ["The workflow graph must have a list of steps."]
    if paths is None:
        paths = []
    if not isinstance(paths, list):
        return ["The workflow graph must have a list of paths."]

    errors: list[str] = []
    good: list[dict] = []  # steps with a usable id and type
    by_id: dict[str, dict] = {}
    for s in steps:
        if not isinstance(s, dict):
            errors.append("Every step must be an object.")
            continue
        sid = s.get("id")
        if not isinstance(sid, str) or not sid:
            errors.append("A step is missing its id.")
            continue
        if sid in by_id:
            errors.append(f'Two steps share the id "{sid}". Step ids must be unique.')
            continue
        if not isinstance(s.get("type"), str) or s["type"] not in STEP_TYPES:
            errors.append(f'Step "{_label(s)}" has an unknown type "{s.get("type")}".')
            continue
        by_id[sid] = s
        good.append(s)

    starts = [s for s in good if s["type"] == "start"]
    if len(starts) != 1:
        errors.append(f"A workflow needs exactly one start step; found {len(starts)}.")

    out: dict[str, list[dict]] = {sid: [] for sid in by_id}
    for p in paths:
        if not isinstance(p, dict):
            errors.append("Every path must be an object.")
            continue
        src, dst = p.get("from"), p.get("to")
        label = p.get("label") if isinstance(p.get("label"), str) else ""
        if not isinstance(src, str) or src not in by_id:
            errors.append(f'The path "{label.strip()}" starts at a step that does not exist.')
            continue
        if not isinstance(dst, str) or dst not in by_id:
            errors.append(f'The path "{label.strip()}" leaving "{_label(by_id[src])}" points to a step that does not exist.')
            continue
        out[src].append(p)

    for s in good:
        name, kind, sid = _label(s), s["type"], s["id"]
        outcome = s.get("outcome")
        if kind == "end":
            if not outcome:
                errors.append(f'End step "{name}" needs an outcome.')
            elif not isinstance(outcome, str) or outcome not in DISPOSITIONS:
                errors.append(f'End step "{name}" has an unknown outcome "{outcome}".')
            if out[sid]:
                errors.append(f'End step "{name}" cannot have paths leaving it.')
        else:
            if kind == "transfer" and outcome and (not isinstance(outcome, str) or outcome not in DISPOSITIONS):
                errors.append(f'Step "{name}" has an unknown outcome "{outcome}".')
            if kind != "transfer" and not out[sid]:
                errors.append(f'Step "{name}" has no way out. Add a path or make it an end step.')
        if kind == "collect":
            field = s.get("field")
            if not isinstance(field, str) or not FIELD_RE.match(field):
                errors.append(
                    f'Step "{name}" needs a field name: lowercase letters, digits and underscores, '
                    "starting with a letter (up to 32 characters)."
                )
        if kind == "knowledge":
            kid = s.get("knowledge_id")
            if kid is None:
                errors.append(f'Step "{name}" needs a knowledge document.')
            elif not isinstance(kid, int) or isinstance(kid, bool) or kid not in knowledge_ids:
                errors.append(f'Step "{name}" refers to a knowledge document that does not exist.')
        prompt = s.get("prompt")
        if isinstance(prompt, str) and prompt:
            for expr in unknown_expressions(prompt, custom):
                errors.append(f'Step "{name}" uses an unknown expression "{expr}".')
            for msg in long_pause_errors(prompt):
                errors.append(f'Step "{name}": {msg}')
        seen: set[str] = set()
        reported: set[str] = set()
        for p in out[sid]:
            lab = p.get("label")
            lab = lab.strip() if isinstance(lab, str) else ""
            if not lab:
                errors.append(f'A path leaving "{name}" has no label.')
            elif lab in seen and lab not in reported:
                reported.add(lab)
                errors.append(f'Step "{name}" has two paths labelled "{lab}". Labels must be different.')
            seen.add(lab)
            for msg in example_errors(p.get("examples")):
                errors.append(f'Path "{lab or "(no label)"}" leaving "{name}": {msg}')

    if len(starts) == 1:
        reached = {starts[0]["id"]}
        queue = deque(reached)
        while queue:
            for p in out[queue.popleft()]:
                if p["to"] not in reached:
                    reached.add(p["to"])
                    queue.append(p["to"])
        for s in good:
            if s["id"] not in reached:
                errors.append(f'Step "{_label(s)}" can never be reached from the start step.')
    return errors
