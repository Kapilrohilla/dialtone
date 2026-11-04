"""Copy call history from the aiohttp dashboard's SQLite file into Django.

    python manage.py import_legacy_calls --path /data/calls.db

Safe to re-run: rows are matched on `room`, so a second run creates nothing new.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from calls.models import DATETIME_FIELDS, TEXT_FIELDS, Call


class Command(BaseCommand):
    help = "Import calls from the old aiohttp dashboard database (calls.db)."

    def add_arguments(self, parser):
        parser.add_argument("--path", default="/data/calls.db", help="old SQLite file (default: /data/calls.db)")

    def handle(self, *args, path, **options):
        if not Path(path).is_file():
            raise CommandError(f"{path} not found")
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT * FROM calls").fetchall()
        finally:
            conn.close()

        created = 0
        with transaction.atomic():
            for row in rows:
                defaults = {k: _dt(row[k]) for k in DATETIME_FIELDS}
                defaults.update({k: row[k] or "" for k in TEXT_FIELDS})
                _, was_created = Call.objects.update_or_create(room=row["room"], defaults=defaults)
                created += was_created
        self.stdout.write(f"imported {len(rows)} calls ({created} new, {len(rows) - created} updated)")


def _dt(epoch: int | None) -> datetime | None:
    return datetime.fromtimestamp(epoch, timezone.utc) if epoch else None
