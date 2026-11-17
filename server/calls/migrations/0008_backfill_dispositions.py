"""Copy each existing report's disposition onto its call as the current disposition, with an "ai" history
row, so the calls list, filters and history work for calls taken before KAP-46."""
import json
from pathlib import Path

from django.db import migrations

DEFAULT = json.loads((Path(__file__).resolve().parents[2] / "dispositions" / "default_list.json").read_text())
ITEMS = {i["code"]: i for i in DEFAULT["items"]}
BATCH = 500


def _dict(value):
    return value if isinstance(value, dict) else {}


def backfill(apps, schema_editor):
    Call = apps.get_model("calls", "Call")
    CallReport = apps.get_model("calls", "CallReport")
    DispositionChange = apps.get_model("calls", "DispositionChange")
    calls, changes = [], []

    def flush():
        Call.objects.bulk_update(calls, ["disposition_code", "disposition_name", "disposition_group",
                                         "disposition_fields", "disposition_reason", "disposition_source",
                                         "disposition_set_at"])
        DispositionChange.objects.bulk_create(changes)
        calls.clear()
        changes.clear()

    reports = CallReport.objects.exclude(disposition="").select_related("call").order_by("pk")
    for report in reports.iterator(chunk_size=BATCH):
        code = report.disposition.strip().upper()[:32]
        if not code:
            continue
        item = ITEMS.get(code) or {"name": code, "group": "Dropped", "fields": []}
        outcome = _dict(_dict(report.data).get("outcome"))
        fields = {f["key"]: str(outcome[f["key"]]) for f in item["fields"] if outcome.get(f["key"])}
        reason = str(outcome.get("reason") or "")
        call = report.call
        call.disposition_code, call.disposition_name, call.disposition_group = code, item["name"][:60], item["group"]
        call.disposition_fields, call.disposition_reason, call.disposition_source = fields, reason, "ai"
        call.disposition_set_at = report.received_at
        calls.append(call)
        changes.append(DispositionChange(call=call, code=code, name=item["name"][:60], group=item["group"],
                                         fields=fields, source="ai", note=reason, created_at=report.received_at))
        if len(calls) >= BATCH:
            flush()
    flush()


class Migration(migrations.Migration):
    dependencies = [("calls", "0007_call_disposition")]

    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
