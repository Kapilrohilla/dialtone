from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("instance", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="instancesettings",
            name="theme",
            field=models.CharField(
                choices=[("saffron", "Saffron"), ("ocean", "Ocean"), ("forest", "Forest")], default="saffron", db_default="saffron", max_length=16
            ),
        ),
        migrations.AddField(
            model_name="instancesettings",
            name="logo",
            field=models.BinaryField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="instancesettings",
            name="logo_content_type",
            field=models.CharField(blank=True, db_default="", default="", editable=False, max_length=32),
        ),
        migrations.AddField(
            model_name="instancesettings",
            name="logo_version",
            field=models.CharField(blank=True, db_default="", default="", editable=False, max_length=16),
        ),
    ]
