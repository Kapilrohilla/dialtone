"""Disposition lists: the outcomes the AI may pick from at the end of a call (KAP-46).

A list is a name, an ordered set of items and a fallback code. Each item is a code, a name, a description
the AI reads, a report group (one of the five in calls.outcomes) and up to five fields to capture with it.

The published agent snapshot carries the list under "dispositions" (see `snapshot`). Snapshots from before
lists existed have no such key: those agents keep the 14 built-in driver-hiring codes (`LEGACY`), which is
also the list existing workspaces were given by migration. An explicit `None` means "no list attached",
and then no disposition is captured.
"""
import copy
import json
import re
from pathlib import Path

from calls.outcomes import DROPPED, GROUPS, NOT_REACHED

CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,31}$")
FIELD_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
FIELD_TYPES = ("text", "datetime", "number")
MAX_ITEMS, MAX_FIELDS = 30, 5
NAME_MAX, ITEM_NAME_MAX, DESCRIPTION_MAX, LABEL_MAX = 80, 60, 300, 40

LEGACY: dict = json.loads((Path(__file__).with_name("default_list.json")).read_text())


def clean_items(items) -> tuple[list[dict], list[str]]:
    """Validate and normalise a list's items; returns (items, errors)."""
    errors: list[str] = []
    if not isinstance(items, list) or not items:
        return [], ["Add at least one disposition."]
    if len(items) > MAX_ITEMS:
        return [], [f"A list can have at most {MAX_ITEMS} dispositions."]
    out, seen, dupes = [], set(), []
    for n, raw in enumerate(items, 1):
        if not isinstance(raw, dict):
            errors.append(f"Disposition {n} is not valid.")
            continue
        code = str(raw.get("code") or "").strip().upper()
        label = code or f"Disposition {n}"
        if not CODE_RE.match(code):
            errors.append(f"{label}: a code is 1-32 capital letters, digits or _, starting with a letter.")
        elif code in seen:
            dupes.append(code)
        seen.add(code)
        name = str(raw.get("name") or "").strip()
        if not name or len(name) > ITEM_NAME_MAX:
            errors.append(f"{label}: a name is required (at most {ITEM_NAME_MAX} characters).")
        description = str(raw.get("description") or "").strip()
        if len(description) > DESCRIPTION_MAX:
            errors.append(f"{label}: the description can be at most {DESCRIPTION_MAX} characters.")
        group = raw.get("group")
        if group not in GROUPS:
            errors.append(f"{label}: choose a report group ({', '.join(GROUPS)}).")
        fields, field_errors = _clean_fields(raw.get("fields", []), label)
        errors.extend(field_errors)
        out.append({"code": code, "name": name, "description": description, "group": group, "fields": fields})
    if dupes:
        errors.append(f"Codes must be unique: {', '.join(sorted(set(dupes)))}.")
    return out, errors


def _clean_fields(fields, label: str) -> tuple[list[dict], list[str]]:
    if fields is None:
        return [], []
    if not isinstance(fields, list):
        return [], [f"{label}: capture fields must be a list."]
    if len(fields) > MAX_FIELDS:
        return [], [f"{label}: at most {MAX_FIELDS} capture fields."]
    out, errors, keys = [], [], set()
    for raw in fields:
        if not isinstance(raw, dict):
            errors.append(f"{label}: a capture field is not valid.")
            continue
        key = str(raw.get("key") or "").strip()
        flabel = str(raw.get("label") or "").strip()
        ftype = raw.get("type") or "text"
        if not FIELD_KEY_RE.match(key):
            errors.append(f"{label}: a field key is lowercase letters, digits or _, starting with a letter.")
        elif key in keys:
            errors.append(f'{label}: two capture fields use the key "{key}".')
        keys.add(key)
        if not flabel or len(flabel) > LABEL_MAX:
            errors.append(f"{label}: every capture field needs a label (at most {LABEL_MAX} characters).")
        if ftype not in FIELD_TYPES:
            errors.append(f"{label}: a field type is text, datetime or number.")
        out.append({"key": key, "label": flabel, "type": ftype, "required": raw.get("required") is True})
    return out, errors


def find(items: list[dict], code) -> dict | None:
    code = str(code or "").strip().upper()
    return next((i for i in items if i.get("code") == code), None) if code else None


def system_codes(items: list[dict], fallback: str) -> dict:
    """The codes the system sets on its own: not reached (no answer, voicemail, silence), dropped (the line
    dropped mid-call) and the fallback (no clear outcome, or the AI picked a code outside the list)."""
    not_reached = next((i["code"] for i in items if i.get("group") == NOT_REACHED), fallback)
    dropped = next((i["code"] for i in items if i.get("group") == DROPPED and i["code"] != fallback), fallback)
    return {"fallback": fallback, "not_reached": not_reached, "dropped": dropped}


def snapshot(lst) -> dict | None:
    """What the runtime gets for a DispositionList (or None for no list)."""
    if lst is None:
        return None
    items = copy.deepcopy(lst.items)
    return {"id": lst.id, "name": lst.name, "items": items, **system_codes(items, lst.fallback_code)}


def legacy_snapshot() -> dict:
    items = copy.deepcopy(LEGACY["items"])
    return {"id": None, "name": LEGACY["name"], "items": items, **system_codes(items, LEGACY["fallback_code"])}


def from_snapshot(snap: dict | None) -> dict | None:
    """The list a published version runs with: its own, none, or (older snapshots) the legacy 14 codes."""
    if not isinstance(snap, dict) or "dispositions" not in snap:
        return legacy_snapshot()
    lst = snap["dispositions"]
    return lst if isinstance(lst, dict) and isinstance(lst.get("items"), list) else None


def fingerprint(lst: dict | None):
    """The part of a list that changes what the AI does; ids and list names are left out so the migrated
    "Driver hiring" list matches the built-in codes older snapshots ran with."""
    if lst is None:
        return None
    return {"items": lst.get("items"), "fallback": lst.get("fallback")}
