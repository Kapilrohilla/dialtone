import os

from django.conf import settings
from django.core.validators import MinLengthValidator
from django.db import models

DEFAULT_PROJECT_NAME = "Dialtone"
PROJECT_NAME_MAX = 60


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
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=cls.SINGLETON_PK, defaults={"project_name": initial_project_name()})
        return obj
