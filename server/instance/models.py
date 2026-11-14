import os

from django.conf import settings
from django.core.validators import MinLengthValidator
from django.db import models

DEFAULT_PROJECT_NAME = "Dialtone"
PROJECT_NAME_MAX = 60

THEME_CHOICES = [("saffron", "Saffron"), ("ocean", "Ocean"), ("forest", "Forest")]
DEFAULT_THEME = "saffron"


def initial_project_name():
    """`DIALTONE_PROJECT_NAME` (trimmed, at most 60 characters), else "Dialtone"."""
    name = os.environ.get("DIALTONE_PROJECT_NAME", "").strip()
    return name if name and len(name) <= PROJECT_NAME_MAX else DEFAULT_PROJECT_NAME


class InstanceSettings(models.Model):
    """Settings for the whole install (not a workspace). Exactly one row, pk=1; use `load()`."""

    SINGLETON_PK = 1

    project_name = models.CharField(
        max_length=PROJECT_NAME_MAX, default=DEFAULT_PROJECT_NAME, validators=[MinLengthValidator(1)]
    )
    # The console palette for everyone; light / dark stays each user's own choice.
    theme = models.CharField(max_length=16, choices=THEME_CHOICES, default=DEFAULT_THEME, db_default=DEFAULT_THEME)
    # The logo is small (1 MB at most) and there is one, so it lives in the row: no media volume to back up.
    logo = models.BinaryField(null=True, blank=True, editable=False)
    logo_content_type = models.CharField(max_length=32, blank=True, default="", db_default="", editable=False)
    # Changes with every upload; part of the logo URL so browsers fetch the new one.
    logo_version = models.CharField(max_length=16, blank=True, default="", db_default="", editable=False)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "instance settings"
        verbose_name_plural = "instance settings"
        constraints = [models.CheckConstraint(condition=models.Q(pk=1), name="instance_settings_singleton")]

    def __str__(self):
        return self.project_name

    def save(self, *args, **kwargs):
        self.pk = self.SINGLETON_PK
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise models.ProtectedError("The instance settings row can't be deleted.", [self])

    @classmethod
    def load(cls, with_logo=False):
        """The row. The logo bytes are only read when `with_logo` (the settings JSON doesn't need them)."""
        qs = cls.objects.all() if with_logo else cls.objects.defer("logo")
        obj = qs.filter(pk=cls.SINGLETON_PK).first()
        if obj is None:
            obj, _ = cls.objects.get_or_create(pk=cls.SINGLETON_PK, defaults={"project_name": initial_project_name()})
        return obj

    @property
    def logo_url(self):
        return f"/api/instance/logo?v={self.logo_version}" if self.logo_version else None
