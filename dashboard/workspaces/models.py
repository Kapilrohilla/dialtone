from django.conf import settings
from django.db import models


class Workspace(models.Model):
    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    # Account-wide switch for checking in on silent callers; off here wins over every agent and workflow.
    dead_air_enabled = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Membership(models.Model):
    OWNER, ADMIN, EDITOR, VIEWER = "owner", "admin", "editor", "viewer"
    ROLES = [(OWNER, "Owner"), (ADMIN, "Admin"), (EDITOR, "Editor"), (VIEWER, "Viewer")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=10, choices=ROLES, default=VIEWER)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "workspace"], name="unique_membership")]

    def __str__(self):
        return f"{self.user} @ {self.workspace} ({self.role})"


class UserPreference(models.Model):
    APPEARANCES = [("light", "Light"), ("dark", "Dark"), ("system", "System")]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="preference")
    appearance = models.CharField(max_length=10, choices=APPEARANCES, default="system")
    notify_needs_person = models.BooleanField(default=True)
    notify_daily_summary = models.BooleanField(default=False)
    time_zone = models.CharField(max_length=64, default="Asia/Kolkata")
    phone = models.CharField(max_length=32, blank=True)


class IntegrationRequest(models.Model):
    """A member asking for a tool integration the console doesn't offer yet."""

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="integration_requests")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="integration_requests"
    )
    tool = models.CharField(max_length=100)
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
