from django.db import migrations


def create_carrum(apps, schema_editor):
    Workspace = apps.get_model("workspaces", "Workspace")
    Workspace.objects.get_or_create(slug="carrum", defaults={"name": "Carrum Mobility"})


class Migration(migrations.Migration):
    dependencies = [("workspaces", "0001_initial")]
    operations = [migrations.RunPython(create_carrum, migrations.RunPython.noop)]
