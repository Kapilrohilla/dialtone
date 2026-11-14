"""Validation for agent fixes from call audits (KAP-37). Pure functions over the agent's draft; never raise on
malformed input except ``Invalid``.

Like ``workflows/suggestions.py``, the same checks run on Gemini's output (bad fixes are dropped), on an editor's edit
(400 with the reason) and on every read against the current draft (``invalid_reason``).
"""
from workflows.suggestions import MAX_REASON_CHARS, Invalid, _text

from .serializers import TEXT_SETTINGS
from .tokens import long_pause_errors, short_pause_errors, unknown_expressions, variables

MAX_SECTION_CHARS = 4000
MAX_KNOWLEDGE_TITLE_CHARS = 120
MAX_KNOWLEDGE_CHARS = 1500
MAX_LANGUAGE_CHARS = 60
MAX_PERSONA_CHARS = 60

# The settings an audit fix may change, and what "the current value" is for each.
SETTING_KEYS = ("language", "persona_name", "name_pronunciation", "consent_line", "mood_adaptation")

__all__ = ["Invalid", "validate_script", "validate_knowledge", "validate_settings", "validate_agent_item",
           "current_settings", "section"]


def _custom(agent) -> dict[str, str]:
    return agent.custom_expressions if isinstance(agent.custom_expressions, dict) else {}


def _token_errors(text: str, custom: dict[str, str]) -> list[str]:
    errors = [f'Unknown expression "{n}".' for n in unknown_expressions(text, custom)]
    return errors + long_pause_errors(text) + short_pause_errors(text)


def section(agent, section_id) -> dict | None:
    for s in agent.script if isinstance(agent.script, list) else []:
        if isinstance(s, dict) and s.get("id") == section_id and isinstance(s.get("body"), str):
            return s
    return None


def current_settings(agent) -> dict:
    st = agent.settings if isinstance(agent.settings, dict) else {}
    return {
        "language": agent.language or "",
        "persona_name": agent.persona_name or "",
        "name_pronunciation": st.get("name_pronunciation") or "",
        "consent_line": st.get("consent_line") or "",
        "mood_adaptation": bool(st.get("mood_adaptation", True)),
    }


def _reason(payload) -> str:
    return _text(payload.get("reason"), "reason", MAX_REASON_CHARS, "Reason", required=False)


# -- script ------------------------------------------------------------------------------------------

def validate_script(payload, agent) -> dict:
    """A rewrite of one script section's body: {"section_id", "title", "before", "after", "reason"}."""
    if not isinstance(payload, dict):
        raise Invalid("This suggestion is malformed.")
    sid = payload.get("section_id")
    s = section(agent, sid) if isinstance(sid, str) else None
    if s is None:
        raise Invalid("The script section this changes was removed.")
    before = payload.get("before")
    if not isinstance(before, str) or before != s["body"]:
        raise Invalid("This script section has changed since.")
    after = _text(payload.get("after"), "after", MAX_SECTION_CHARS, "The section")
    if after == before.strip():
        raise Invalid("This doesn't change the section.", "after")
    new_vars = [v for v in variables(after) if v not in variables(before)]
    if new_vars:
        raise Invalid(f'"{{{{{new_vars[0]}}}}}" isn\'t used by this section yet. Keep to the details it already uses.',
                      "after")
    errors = _token_errors(after, _custom(agent))
    if errors:
        raise Invalid(errors[0], "after")
    title = s.get("title") if isinstance(s.get("title"), str) else ""
    return {"section_id": sid, "title": title, "before": before, "after": after, "reason": _reason(payload)}


# -- knowledge ---------------------------------------------------------------------------------------

def validate_knowledge(payload, agent) -> dict:
    """A new knowledge snippet for questions the agent couldn't answer: {"title", "body", "reason"}. Accepting
    creates a knowledge document and links it to the agent."""
    from knowledge.models import KnowledgeDocument

    if not isinstance(payload, dict):
        raise Invalid("This suggestion is malformed.")
    title = _text(payload.get("title"), "title", MAX_KNOWLEDGE_TITLE_CHARS, "Title")
    body = _text(payload.get("body"), "body", MAX_KNOWLEDGE_CHARS, "The snippet")
    taken = KnowledgeDocument.objects.filter(workspace_id=agent.workspace_id, archived=False, title__iexact=title)
    if taken.exists():
        raise Invalid("A knowledge document with this title already exists. Rename it to accept.", "title")
    errors = _token_errors(body, _custom(agent))
    if errors:
        raise Invalid(errors[0], "body")
    return {"title": title, "body": body, "reason": _reason(payload)}


# -- settings ----------------------------------------------------------------------------------------

def _setting(key: str, value):
    if key == "mood_adaptation":
        if not isinstance(value, bool):
            raise Invalid("Mood adaptation must be on or off.", "changes")
        return value
    limit = {"language": MAX_LANGUAGE_CHARS, "persona_name": MAX_PERSONA_CHARS}.get(key) or TEXT_SETTINGS[key]
    what = {"language": "Language", "persona_name": "Persona name", "name_pronunciation": "Name pronunciation",
            "consent_line": "Consent line"}[key]
    return _text(value, "changes", limit, what, required=key == "language")


def validate_settings(payload, agent) -> dict:
    """Changed settings: {"changes": {key: value}, "before": {key: value}, "reason"}. ``before`` must still be the
    agent's current value for every changed key."""
    if not isinstance(payload, dict):
        raise Invalid("This suggestion is malformed.")
    changes, before = payload.get("changes"), payload.get("before")
    if not isinstance(changes, dict) or not changes or not isinstance(before, dict):
        raise Invalid("This suggestion is malformed.", "changes")
    current = current_settings(agent)
    clean, was = {}, {}
    for key, value in changes.items():
        if key not in SETTING_KEYS:
            raise Invalid(f'"{key}" can\'t be changed by a fix.', "changes")
        if key not in before or before[key] != current[key]:
            raise Invalid("The agent's settings have changed since.")
        value = _setting(key, value)
        if value == current[key]:
            continue
        clean[key], was[key] = value, current[key]
    if not clean:
        raise Invalid("This doesn't change any setting.", "changes")
    return {"changes": clean, "before": was, "reason": _reason(payload)}


def validate_agent_item(kind: str, payload, agent) -> dict:
    if kind == "script":
        return validate_script(payload, agent)
    if kind == "knowledge":
        return validate_knowledge(payload, agent)
    if kind == "settings":
        return validate_settings(payload, agent)
    raise Invalid("This suggestion is malformed.")

