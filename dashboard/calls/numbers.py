"""Phone-number helpers shared by calls and runtime (no model imports, so no import cycles)."""

import re


def digits(value) -> str:
    """Digits only; leading zeros are trunk/international prefixes ("0", "00"), not part of the number."""
    return re.sub(r"\D", "", str(value or "")).lstrip("0")


def same_number(a, b) -> bool:
    """Digits-only match; the Indian country code "91" is optional on either side."""
    a, b = digits(a), digits(b)
    if not a or not b:
        return False
    return a == b or a == "91" + b or b == "91" + a


def strip_nul(value):
    """Remove NUL characters from every string (keys too), recursively; Postgres text/jsonb rejects them."""
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {strip_nul(k): strip_nul(v) for k, v in value.items()}
    if isinstance(value, list):
        return [strip_nul(v) for v in value]
    return value
