from getpass import getpass

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from workspaces.models import Membership, UserPreference, Workspace


class Command(BaseCommand):
    help = "Create a console user and add them to a workspace (prompts for a password)."

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("--name", default="")
        parser.add_argument("--role", default=Membership.EDITOR, choices=[r for r, _ in Membership.ROLES])
        parser.add_argument("--workspace", default="carrum")

    def handle(self, *args, email, name, role, workspace, **opts):
        User = get_user_model()
        try:
            ws = Workspace.objects.get(slug=workspace)
        except Workspace.DoesNotExist:
            raise CommandError(f"No workspace with slug '{workspace}'.")
        if User.objects.filter(email__iexact=email).exists():
            raise CommandError(f"A user with email {email} already exists.")
        password = getpass("Password: ")
        if password != getpass("Password (again): "):
            raise CommandError("Passwords did not match.")
        user = User(username=email, email=email, first_name=name)
        try:
            validate_password(password, user)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages))
        user.set_password(password)
        user.save()
        Membership.objects.create(user=user, workspace=ws, role=role)
        UserPreference.objects.get_or_create(user=user)
        self.stdout.write(self.style.SUCCESS(f"Created {email} as {role} in {ws.name}."))
