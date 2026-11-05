"""Copy the dashboard's old SQLite database into the current (PostgreSQL) one.

    python manage.py copy_from_sqlite --path /data/dashboard.sqlite3 [--force]

Copies auth groups and users, calls, call reports and turn labels in one
transaction, keeping primary keys, then resets the id sequences. The SQLite
file is opened read-only and never modified. Refuses to run when the target
already has calls, unless --force (rows with the same id are then overwritten).
"""

import json
import logging
import sqlite3
from datetime import timezone as dt_timezone
from pathlib import Path

from django.contrib.auth.models import Group, Permission, User
from django.core.management.base import BaseCommand, CommandError
from django.core.management.color import no_style
from django.db import connection, models, transaction
from django.utils import timezone

from calls.models import Call, CallReport, TurnLabel

MARKER = ".copied-to-postgres"
logger = logging.getLogger(__name__)

# Parents before children.
MODELS = [Group, User, Call, CallReport, TurnLabel]
LABELS = {Group: "groups", User: "users", Call: "calls", CallReport: "reports", TurnLabel: "turn labels"}


def _convert(field: models.Field, value):
    if value is None:
        return None
    if isinstance(field, models.JSONField):
        return json.loads(value) if isinstance(value, (str, bytes)) else value
    value = field.to_python(value)
    if isinstance(field, models.DateTimeField) and timezone.is_naive(value):
        value = timezone.make_aware(value, dt_timezone.utc)
    return value


def _perm_key(row) -> tuple:
    return (row["app_label"], row["model"], row["codename"])


class Command(BaseCommand):
    help = "Copy calls, reports, turn labels, users and groups from the old SQLite file into the current database."

    def add_arguments(self, parser):
        parser.add_argument("--path", default="/data/dashboard.sqlite3", help="old SQLite file")
        parser.add_argument("--force", action="store_true", help="copy even if the target already has calls")
        parser.add_argument("--dry-run", action="store_true", help="do the whole copy, print counts, then roll back")
        parser.add_argument(
            "--if-needed", action="store_true",
            help="startup mode: copy only if the file exists, no marker is present and the target has no calls; "
                 "then write the marker. Never overwrites; skips with a warning instead.",
        )

    def handle(self, *args, path, force, dry_run, if_needed, **options):
        marker = Path(path).parent / MARKER
        if if_needed:
            if not Path(path).is_file() or marker.exists():
                return
            if Call.objects.exists():
                logger.warning(
                    "copy_from_sqlite: %s exists but PostgreSQL already has calls and no %s marker; "
                    "skipping the copy. Compare both and run `copy_from_sqlite` by hand if needed.", path, marker.name)
                self.stderr.write("WARNING: SQLite history not copied (PostgreSQL already has calls)")
                return
        if not Path(path).is_file():
            raise CommandError(f"{path} not found")
        if Call.objects.exists() and not force:
            raise CommandError("the target database already has calls; use --force to copy anyway")

        src = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        src.row_factory = sqlite3.Row
        counts = {}
        try:
            with transaction.atomic():
                for model in MODELS:
                    counts[model] = self._copy_model(src, model)
                self._copy_relations(src)
                self._reset_sequences()
                if dry_run:
                    transaction.set_rollback(True)
        finally:
            src.close()
        for model in MODELS:
            self.stdout.write(f"{LABELS[model]}: {counts[model]}")
        if dry_run:
            self.stdout.write("dry run: nothing was written")
        elif if_needed:
            marker.write_text("copied from dashboard.sqlite3\n")

    def _copy_model(self, src, model) -> int:
        table = model._meta.db_table
        rows = src.execute(f'SELECT * FROM "{table}"').fetchall()
        if not rows:
            return 0
        fields = [f for f in model._meta.concrete_fields if f.column in rows[0].keys()]
        objs = [model(**{f.attname: _convert(f, row[f.column]) for f in fields}) for row in rows]
        update = [f.name for f in fields if not f.primary_key]
        model.objects.bulk_create(objs, update_conflicts=True, unique_fields=["id"], update_fields=update)
        return len(objs)

    def _copy_relations(self, src):
        """Group membership and permissions; permissions are matched by (app, model, codename), not id."""
        perms = {(p.content_type.app_label, p.content_type.model, p.codename): p.id
                 for p in Permission.objects.select_related("content_type")}
        perm_sql = (
            'SELECT x.{owner}_id AS owner, ct.app_label, ct.model, p.codename FROM {table} x '
            "JOIN auth_permission p ON p.id = x.permission_id "
            "JOIN django_content_type ct ON ct.id = p.content_type_id"
        )
        for through, owner, table in (
            (Group.permissions.through, "group", "auth_group_permissions"),
            (User.user_permissions.through, "user", "auth_user_user_permissions"),
        ):
            field = f"{owner}_id"
            through.objects.filter(**{f"{field}__in": [r[0] for r in src.execute(f"SELECT DISTINCT {owner}_id FROM {table}")]}).delete()
            through.objects.bulk_create(
                through(**{field: r["owner"], "permission_id": perms[_perm_key(r)]})
                for r in src.execute(perm_sql.format(owner=owner, table=table))
                if _perm_key(r) in perms
            )
        through = User.groups.through
        rows = src.execute("SELECT user_id, group_id FROM auth_user_groups").fetchall()
        through.objects.filter(user_id__in=[r["user_id"] for r in rows]).delete()
        through.objects.bulk_create(through(user_id=r["user_id"], group_id=r["group_id"]) for r in rows)

    def _reset_sequences(self):
        tables = MODELS + [Group.permissions.through, User.user_permissions.through, User.groups.through]
        with connection.cursor() as cursor:
            for sql in connection.ops.sequence_reset_sql(no_style(), tables):
                cursor.execute(sql)
