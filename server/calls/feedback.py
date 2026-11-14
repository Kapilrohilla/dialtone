"""People's own ratings of a call (CallFeedback): validation and the API shape."""

from rest_framework.exceptions import ValidationError

MAX_REMARKS = 2000


def area_keys() -> list[str]:
    from audits.rubric import AREAS

    return [key for key, *_ in AREAS]


def _rating(value, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
        raise ValidationError({name: ["Rate from 1 to 5."]})
    return value


def clean(data) -> dict:
    """{"ratings", "overall", "remarks"} from a request body; raises ValidationError."""
    if not isinstance(data, dict):
        raise ValidationError({"detail": "Send a JSON object."})
    raw = data.get("ratings") or {}
    if not isinstance(raw, dict):
        raise ValidationError({"ratings": ["Send ratings as {area: 1-5}."]})
    known = area_keys()
    unknown = sorted(k for k in raw if k not in known)
    if unknown:
        raise ValidationError({"ratings": [f"Unknown area: {', '.join(map(str, unknown))}."]})
    ratings = {k: _rating(v, f"ratings.{k}") for k, v in raw.items() if v is not None}
    overall = data.get("overall")
    overall = None if overall is None else _rating(overall, "overall")
    remarks = data.get("remarks") or ""
    if not isinstance(remarks, str):
        raise ValidationError({"remarks": ["Must be text."]})
    remarks = remarks.replace("\x00", "").strip()
    if len(remarks) > MAX_REMARKS:
        raise ValidationError({"remarks": [f"Keep remarks to {MAX_REMARKS} characters."]})
    if not ratings and overall is None and not remarks:
        raise ValidationError({"detail": "Add a rating or a remark."})
    return {"ratings": ratings, "overall": overall, "remarks": remarks}


def as_dict(fb, user) -> dict:
    from voiceagents.serializers import display_name

    return {
        "id": fb.id,
        "author": display_name(fb.author),
        "mine": fb.author_id == user.id,
        "ratings": {k: v for k, v in (fb.ratings or {}).items() if k in area_keys()},
        "overall": fb.overall,
        "remarks": fb.remarks,
        "updated_at": fb.updated_at,
    }
