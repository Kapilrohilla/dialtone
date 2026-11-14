from django.conf import settings
from django.db import models


DEFAULT_WORKSPACE_SLUG = "default"
DEFAULT_WORKSPACE_NAME = "Default workspace"


class Workspace(models.Model):
    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    # Account-wide switch for checking in on silent callers; off here wins over every agent and workflow.
    dead_air_enabled = models.BooleanField(default=True)
    # Record phone calls (the caller hears a consent line). Off until an owner or admin turns it on.
    recording_enabled = models.BooleanField(default=False)
    # Call audits (KAP-17): Gemini scores the AI side of finished calls. Off until an owner or admin turns it on.
    audit_enabled = models.BooleanField(default=False)
    audit_sample_pct = models.PositiveSmallIntegerField(default=100)  # 100, 50, 25 or 10
    audit_weights = models.JSONField(default=dict, blank=True)  # {area: 0-100}; missing areas use the defaults
    audit_instructions = models.TextField(blank=True, default="")  # extra notes for the rubric

    def __str__(self):
        return self.name

    @classmethod
    def ensure_default(cls):
        """Create the default workspace if there are no workspaces at all. Returns (workspace, created);
        workspace is the oldest one when some already exist."""
        existing = cls.objects.order_by("id").first()
        if existing is not None:
            return existing, False
        return cls.objects.get_or_create(slug=DEFAULT_WORKSPACE_SLUG, defaults={"name": DEFAULT_WORKSPACE_NAME})


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
