"""The disposition list a call runs with (KAP-46): the codes record_outcome accepts and the lines the AI reads.

The console's snapshot carries the agent's list under "dispositions":
    {"id", "name", "items": [{"code", "name", "description", "group", "fields": [{"key", "label", "type",
     "required"}]}], "fallback", "not_reached", "dropped"}
`None` there means the agent has no list: no disposition is captured. Snapshots from before lists existed, and
the built-in agent (no console config), use the 14 driver-hiring codes in default_dispositions.json (the same
file the server seeds workspaces with).
"""
import copy
import json
import re
from pathlib import Path

NOT_REACHED, DROPPED = "Not reached", "Dropped"

_RAW = json.loads(Path(__file__).with_name("default_dispositions.json").read_text())


def _with_system_codes(name: str, items: list[dict], fallback: str, list_id=None) -> dict:
    not_reached = next((i["code"] for i in items if i.get("group") == NOT_REACHED), fallback)
    dropped = next((i["code"] for i in items if i.get("group") == DROPPED and i["code"] != fallback), fallback)
    return {"id": list_id, "name": name, "items": items, "fallback": fallback, "not_reached": not_reached,
            "dropped": dropped}


LEGACY: dict = _with_system_codes(_RAW["name"], _RAW["items"], _RAW["fallback_code"])

# The 14 built-in codes, in their usual order (kept for code that predates lists).
LEGACY_CODES = tuple(i["code"] for i in LEGACY["items"])


def for_snapshot(snapshot: dict | None) -> dict | None:
    """The list a call uses: the snapshot's, none, or (built-in agent, older snapshots) the built-in codes."""
    if not isinstance(snapshot, dict) or "dispositions" not in snapshot:
        return copy.deepcopy(LEGACY)
    lst = snapshot["dispositions"]
    if not isinstance(lst, dict) or not isinstance(lst.get("items"), list) or not lst["items"]:
        return None
    items = [i for i in lst["items"] if isinstance(i, dict) and isinstance(i.get("code"), str) and i["code"]]
    fallback = lst.get("fallback") if isinstance(lst.get("fallback"), str) else ""
    if not items:
        return None
    if fallback not in {i["code"] for i in items}:
        fallback = items[-1]["code"]
    out = _with_system_codes(str(lst.get("name") or ""), items, fallback, lst.get("id"))
    for key in ("not_reached", "dropped"):
        if isinstance(lst.get(key), str) and lst[key] in {i["code"] for i in items}:
            out[key] = lst[key]
    return out


def codes(lst: dict | None) -> list[str]:
    return [i["code"] for i in lst["items"]] if lst else []


def find(lst: dict | None, code) -> dict | None:
    code = str(code or "").strip().upper()
    return next((i for i in lst["items"] if i["code"] == code), None) if lst and code else None


def system_code(lst: dict | None, kind: str) -> str:
    """The code the system sets by itself: "not_reached", "dropped" or "fallback"; "" with no list."""
    return lst.get(kind) or lst["fallback"] if lst else ""


def parse_fields(text) -> dict:
    """record_outcome's `fields`: a JSON object, or "key=value; key=value" / "key: value" lines."""
    if isinstance(text, dict):
        raw = text
    else:
        text = str(text or "").strip()
        raw = {}
        if text.startswith("{"):
            try:
                loaded = json.loads(text)
                raw = loaded if isinstance(loaded, dict) else {}
            except ValueError:
                raw = {}
        if not raw:
            for part in re.split(r"[;\n]", text):
                key, sep, value = part.partition("=") if "=" in part else part.partition(":")
                if sep:
                    raw[key.strip()] = value.strip()
    return {str(k).strip(): str(v).strip() for k, v in raw.items()
            if str(k).strip() and v is not None and not isinstance(v, (dict, list)) and str(v).strip()}


def captured(item: dict, values: dict) -> dict:
    """{key: value} for the item's capture fields that have a value in `values`."""
    out = {}
    for f in item.get("fields") or []:
        value = values.get(f.get("key"))
        if value not in (None, "") and not isinstance(value, (dict, list)) and str(value).strip():
            out[f["key"]] = str(value).strip()
    return out


def missing_fields(item: dict, values: dict) -> list[dict]:
    have = captured(item, values)
    return [f for f in item.get("fields") or [] if f.get("required") and f.get("key") not in have]


def block(lst: dict | None) -> str:
    """What the AI reads about dispositions: one line per code, or that there is no list."""
    if lst is None:
        return ("Dispositions: this agent records none. When you call record_outcome, leave `disposition` "
                "empty; still give the reason and summary.")
    lines = ["Dispositions (record_outcome's `disposition`; use only these codes):"]
    for item in lst["items"]:
        line = f"- {item['code']}: {item.get('name', '').strip()}."
        if (description := str(item.get("description") or "").strip()):
            line += f" {description}"
        fields = item.get("fields") or []
        if fields:
            wanted = ", ".join(
                f"{f.get('label') or f['key']} as `{f['key']}`{' (required)' if f.get('required') else ''}"
                for f in fields)
            line += f" Capture in `fields`: {wanted}."
        lines.append(line)
    return "\n".join(lines)


def refusal(lst: dict | None, disposition, values: dict) -> str | None:
    """Why record_outcome can't take this disposition (told to the AI), or None. With no list, any code is
    ignored rather than refused."""
    if lst is None:
        return None
    item = find(lst, disposition)
    if item is None:
        picked = str(disposition or "").strip() or "An empty disposition"
        return f"{picked} isn't one of your dispositions. Use one of: {', '.join(codes(lst))}."
    missing = missing_fields(item, values)
    if missing:
        wanted = ", ".join(f"{f.get('label') or f['key']} (`{f['key']}`)" for f in missing)
        return (f"{item['code']} needs {wanted}. Ask the driver if you don't know it, then call record_outcome "
                "again with it in `fields`.")
    return None
