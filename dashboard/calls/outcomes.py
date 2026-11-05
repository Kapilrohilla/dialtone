"""The 14 fixed call dispositions and the five groups the console shows them in."""

INTERESTED, CALL_BACK, NOT_INTERESTED, DROPPED, NOT_REACHED = (
    "Interested", "Call back", "Not interested", "Dropped", "Not reached",
)
GROUPS = [INTERESTED, CALL_BACK, NOT_INTERESTED, DROPPED, NOT_REACHED]

DISPLAY_OUTCOME: dict[str, str] = {
    "INTERESTED": INTERESTED,
    "CBR": CALL_BACK,
    "NI": NOT_INTERESTED,
    "NE": NOT_INTERESTED,
    "ISUDO": NOT_INTERESTED,
    "ISUID": NOT_INTERESTED,
    "OWNVA": NOT_INTERESTED,
    "ABULR": NOT_INTERESTED,
    "WRGN": NOT_INTERESTED,
    "LANGUAGE_BARRIER": NOT_INTERESTED,
    "HND": NOT_INTERESTED,
    "CDRP": DROPPED,
    "UNRESOLVED": DROPPED,
    "NOT_CONNECTED": NOT_REACHED,
}


def normalise(code) -> str:
    return str(code or "").strip().upper()


def display_outcome(code) -> str:
    """The display group for a disposition code: "" when blank, "Dropped" for codes outside the 14."""
    code = normalise(code)
    if not code:
        return ""
    return DISPLAY_OUTCOME.get(code, DROPPED)


def codes_for(group: str) -> list[str]:
    return [code for code, g in DISPLAY_OUTCOME.items() if g == group]
