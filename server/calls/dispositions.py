"""Setting a call's disposition (KAP-46): from the agent's report (AI or system) or by a person.

The list a call is judged against is the one its agent version was published with (older versions: the
built-in driver-hiring codes). Voice tests run a draft, which has no saved version, so the report carries
the list the draft ran with. No list means no disposition: the call shows "No disposition".
"""
from django.db import transaction
from django.utils import timezone

from dispositions import lists as disposition_lists

from .models import Call, DispositionChange
from .outcomes import normalise

FIELD_VALUE_MAX = 200


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def list_for_call(call: Call, report_data: dict | None = None) -> dict | None:
    """The disposition list (snapshot form) that applies to `call`, or None when its agent had none."""
    if call.agent_version_id:
        return disposition_lists.from_snapshot(call.agent_version.snapshot)
    if report_data is None:
        try:
            report_data = call.report.data
        except Call.report.RelatedObjectDoesNotExist:
            report_data = None
    data = _dict(report_data)
    if "dispositions" in data:
        lst = data["dispositions"]
        if isinstance(lst, dict) and isinstance(lst.get("items"), list) and lst["items"]:
            items, errors = disposition_lists.clean_items(lst["items"])
            fallback = normalise(lst.get("fallback"))
            if not errors and disposition_lists.find(items, fallback):
                return {"id": lst.get("id"), "name": str(lst.get("name") or ""), "items": items,
                        **disposition_lists.system_codes(items, fallback)}
        return None
    # Calls from before lists existed (or before their report arrived) ran with the built-in codes.
    return disposition_lists.legacy_snapshot() if call.disposition_code or report_data is not None else None


def _capture(item: dict, values: dict) -> dict:
    """The item's capture fields that have a value, as {key: text}."""
    out = {}
    for f in item.get("fields") or []:
        value = values.get(f["key"])
        if value is None or isinstance(value, (dict, list)):
            continue
        text = str(value).strip()[:FIELD_VALUE_MAX]
        if text:
            out[f["key"]] = text
    return out


def set_disposition(call: Call, item: dict, source: str, *, fields: dict | None = None, note: str = "",
                    user=None) -> DispositionChange:
    """Make `item` the call's current disposition, keep the change in its history and send the webhook.
    Caller holds a transaction."""
    now = timezone.now()
    previous = call.disposition_code
    call.disposition_code = item["code"]
    call.disposition_name = item["name"][:60]
    call.disposition_group = item["group"]
    call.disposition_fields = fields or {}
    call.disposition_reason = note
    call.disposition_source = source
    call.disposition_set_at = now
    call.disposition_set_by = user
    call.save(update_fields=["disposition_code", "disposition_name", "disposition_group", "disposition_fields",
                             "disposition_reason", "disposition_source", "disposition_set_at",
                             "disposition_set_by"])
    change = DispositionChange.objects.create(
        call=call, code=item["code"], name=item["name"][:60], group=item["group"], fields=fields or {},
        source=source, note=note, changed_by=user, created_at=now,
    )
    from .webhooks import queue_disposition_event

    transaction.on_commit(lambda: queue_disposition_event(call.pk, change.pk, previous))
    return change


def apply_report(call: Call, report: dict) -> None:
    """Set the disposition the agent recorded. A code outside the list becomes the list's fallback (set by
    the system). A person's change is never overwritten by a re-sent report. Caller holds a transaction."""
    lst = list_for_call(call, report)
    if lst is None or call.disposition_source == DispositionChange.USER:
        return
    outcome = _dict(report.get("outcome"))
    picked = normalise(report.get("disposition") or outcome.get("disposition"))
    source = DispositionChange.SYSTEM if outcome.get("set_by") == "system" else DispositionChange.AI
    note = str(outcome.get("reason") or "").strip()
    item = disposition_lists.find(lst["items"], picked)
    if item is None:
        item = disposition_lists.find(lst["items"], lst["fallback"])
        source = DispositionChange.SYSTEM
        note = (f"The AI picked {picked}, which isn't in the list." if picked
                else note or "No disposition was recorded.")
    fields = _capture(item, {**outcome, **_dict(outcome.get("fields"))})
    if (call.disposition_code, call.disposition_fields, call.disposition_source) == (item["code"], fields, source):
        return  # the same report sent again
    set_disposition(call, item, source, fields=fields, note=note)


class ChangeError(Exception):
    def __init__(self, errors: dict):
        super().__init__(str(errors))
        self.errors = errors


def change_by_user(call: Call, code, fields, note, user) -> DispositionChange:
    """A person sets the disposition from the call detail; checked against the call's list."""
    lst = list_for_call(call)
    if lst is None:
        raise ChangeError({"detail": "This call's agent has no disposition list."})
    item = disposition_lists.find(lst["items"], code)
    if item is None:
        raise ChangeError({"code": [f"Choose a disposition from the list \"{lst['name']}\"."]})
    values = _dict(fields)
    missing = {f["key"]: "Required." for f in item.get("fields") or []
               if f.get("required") and not str(values.get(f["key"]) or "").strip()}
    if missing:
        raise ChangeError({"fields": missing})
    for f in item.get("fields") or []:
        value = str(values.get(f["key"]) or "").strip()
        if value and f.get("type") == "number":
            try:
                float(value)
            except ValueError:
                raise ChangeError({"fields": {f["key"]: "Enter a number."}}) from None
    note = str(note or "").strip()[:500]
    with transaction.atomic():
        locked = Call.objects.select_for_update().get(pk=call.pk)
        return set_disposition(locked, item, DispositionChange.USER, fields=_capture(item, values), note=note,
                               user=user)
