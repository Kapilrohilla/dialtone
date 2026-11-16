"""Give every existing workspace today's 14 codes as a "Driver hiring" list, attached to all of its agents,
so live agents keep capturing dispositions after lists became per agent (KAP-46)."""
import json
from pathlib import Path

from django.db import migrations

# The same built-in codes that agents published before KAP-46 run with (dispositions.lists.LEGACY).
DEFAULT = json.loads((Path(__file__).resolve().parent.parent / "default_list.json").read_text())


def seed(apps, schema_editor):
    Workspace = apps.get_model("workspaces", "Workspace")
    DispositionList = apps.get_model("dispositions", "DispositionList")
    Agent = apps.get_model("voiceagents", "Agent")
    for ws in Workspace.objects.all():
        lst = DispositionList.objects.create(
            workspace=ws, name=DEFAULT["name"], items=DEFAULT["items"], fallback_code=DEFAULT["fallback_code"]
        )
        # .update() leaves updated_at alone, so agents don't look edited.
        Agent.objects.filter(workspace=ws, disposition_list__isnull=True).update(disposition_list=lst)


class Migration(migrations.Migration):
    dependencies = [
        ("dispositions", "0001_initial"),
        ("voiceagents", "0004_agent_disposition_list"),
    ]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
