"""Keeps only the parts of Gemini's scorecard that can be trusted.

* Every quote must be a verbatim part of a transcript line (whitespace and case aside). A quote that names the
  wrong line is moved to the line that really has it; one no line has is dropped.
* Score evidence must quote an agent line or name a call signal (dead air, interruption, ...). An area left
  with no evidence keeps no score: a score with no evidence is not shown.
* Times and steps always come from the transcript, never from the model.
"""
import re

from .build import AuditInput, Line
from .rubric import AREA_KEYS, EVENTS, overall

MAX_EVIDENCE = 3
MAX_MOMENTS_PER_KIND = 3
MAX_QUOTE_CHARS = 300
MAX_NOTE_CHARS = 200
MAX_SUMMARY_CHARS = 600
MIN_SCORED_AREAS = 4
KINDS = ("good", "problem")
STRIP = " \t\n\"'“”‘’«»…."


class Invalid(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _short(text, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip() if isinstance(text, str) else ""
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def step_context(lines: list[Line]) -> dict[int, tuple[str, str]]:
    """{line index: (step_id, step_name)}; a caller line belongs to the step the agent was last in."""
    out, cur = {}, ("", "")
    for ln in lines:
        if ln.speaker == "agent" and ln.step_id:
            cur = (ln.step_id, ln.step_name)
        out[ln.i] = (ln.step_id, ln.step_name) if ln.step_id else cur
    return out


def find_quote(raw_quote, line_no, lines: list[Line], speakers) -> tuple[Line, str] | None:
    """(the line holding the quote, the quote as it appears there) or None."""
    if not isinstance(raw_quote, str):
        return None
    quote = raw_quote.strip(STRIP)
    q = norm(quote)
    if len(q) < 2 or len(quote) > MAX_QUOTE_CHARS:
        return None
    candidates = [ln for ln in lines if ln.speaker in speakers and q in norm(ln.text)]
    if not candidates:
        return None
    named = next((ln for ln in candidates if ln.i == line_no), None)
    if named is None:  # snap to the nearest line that has it
        ref = line_no if isinstance(line_no, int) and not isinstance(line_no, bool) else 0
        named = min(candidates, key=lambda ln: abs(ln.i - ref))
    return named, re.sub(r"\s+", " ", quote).strip()


def _anchor(line: Line, steps: dict[int, tuple[str, str]]) -> dict:
    step_id, step_name = steps.get(line.i, ("", ""))
    return {"line": line.i, "at": line.at.isoformat() if line.at else None, "at_s": line.at_s,
            "step_id": step_id, "step_name": step_name, "speaker": line.speaker}


def evidence_of(raw_items, inp: AuditInput, steps) -> list[dict]:
    out: list[dict] = []
    for raw in raw_items if isinstance(raw_items, list) else []:
        if not isinstance(raw, dict) or len(out) >= MAX_EVIDENCE:
            continue
        kind = raw.get("kind") if raw.get("kind") in KINDS else "problem"
        note = _short(raw.get("note"), MAX_NOTE_CHARS)
        event = raw.get("event") if raw.get("event") in EVENTS else ""
        found = find_quote(raw.get("quote"), _int(raw.get("line")), inp.lines, ("agent",))
        if found is not None:
            line, quote = found
            out.append({**_anchor(line, steps), "quote": quote, "event": event, "kind": kind, "note": note})
        elif event and note:
            out.append({"line": None, "at": None, "at_s": None, "step_id": "", "step_name": "", "speaker": "",
                        "quote": "", "event": event, "kind": kind, "note": note})
    return out


def moments_of(raw_items, inp: AuditInput, steps) -> list[dict]:
    counts = dict.fromkeys(KINDS, 0)
    out: list[dict] = []
    seen: set[tuple[int, str]] = set()
    for raw in raw_items if isinstance(raw_items, list) else []:
        if not isinstance(raw, dict) or raw.get("kind") not in KINDS or counts[raw["kind"]] >= MAX_MOMENTS_PER_KIND:
            continue
        found = find_quote(raw.get("quote"), _int(raw.get("line")), inp.lines, ("agent", "caller"))
        if found is None:
            continue
        line, quote = found
        if (line.i, raw["kind"]) in seen:
            continue
        seen.add((line.i, raw["kind"]))
        counts[raw["kind"]] += 1
        out.append({**_anchor(line, steps), "kind": raw["kind"],
                    "area": raw.get("area") if raw.get("area") in AREA_KEYS else "",
                    "quote": quote, "note": _short(raw.get("note"), MAX_NOTE_CHARS)})
    out.sort(key=lambda m: (m["line"], m["kind"]))
    return out


def scorecard(data, inp: AuditInput, weights: dict[str, int]) -> dict:
    """{"scores", "overall_score", "summary", "moments"} from Gemini's output; raises Invalid when too little of
    it holds up to give an overall score."""
    if not isinstance(data, dict):
        raise Invalid("not an object")
    steps = step_context(inp.lines)
    raw_scores = data.get("scores") if isinstance(data.get("scores"), dict) else {}
    scores: dict[str, dict] = {}
    for key in AREA_KEYS:
        raw = raw_scores.get(key) if isinstance(raw_scores.get(key), dict) else {}
        score = _int(raw.get("score"))
        evidence = evidence_of(raw.get("evidence"), inp, steps)
        valid = score is not None and 1 <= score <= 5 and bool(evidence)
        scores[key] = {"score": score if valid else None, "summary": _short(raw.get("summary"), MAX_NOTE_CHARS),
                       "evidence": evidence}
    scored = sum(1 for s in scores.values() if s["score"] is not None)
    if scored < MIN_SCORED_AREAS:
        raise Invalid(f"only {scored} areas have a score with evidence")
    return {
        "scores": scores,
        "overall_score": overall({k: v["score"] for k, v in scores.items()}, weights),
        "summary": _short(data.get("summary"), MAX_SUMMARY_CHARS),
        "moments": moments_of(data.get("moments"), inp, steps),
    }
