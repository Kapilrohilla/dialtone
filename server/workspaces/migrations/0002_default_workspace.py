from django.db import migrations


class Migration(migrations.Migration):
    """Formerly created a hard-coded workspace. Workspaces are now seeded by the
    `ensure_default_workspace` management command (run at server startup), so this
    is a no-op kept for the migration graph. `replaces` makes databases that applied
    the old name treat this one as applied too."""

    replaces = [("workspaces", "0002_carrum_workspace")]
    dependencies = [("workspaces", "0001_initial")]
    operations = []
