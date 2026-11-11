from django.core.management.base import BaseCommand

from workspaces.models import Workspace


class Command(BaseCommand):
    help = "Create the default workspace if none exists (run at startup, after migrate). Idempotent."

    def handle(self, *args, **options):
        ws, created = Workspace.ensure_default()
        if created:
            self.stdout.write(f"Created the default workspace '{ws.name}' (slug '{ws.slug}').")
        else:
            self.stdout.write(f"Workspace already present: '{ws.name}' (slug '{ws.slug}').")
