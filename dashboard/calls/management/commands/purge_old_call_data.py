import os
import time
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models.functions import Coalesce
from django.utils import timezone

from calls.models import CallEvent, CallReport, Recording, TurnLabel, recording_relpath

# Files under RECORDINGS_DIR with no recording row are deleted once they are this old (crashed egress).
ORPHAN_AGE_S = 24 * 3600


class Command(BaseCommand):
    help = (
        "Delete transcripts older than --days: turn events and report `turns`, and blank the caller's words "
        "on TurnLabel rows (telecaller labels stay). Dispositions, summaries, answers and metrics stay. "
        "Also deletes call recordings older than --days (the row stays, marked purged) and recording files "
        "older than a day that no recording row points at."
    )

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=90)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, days, dry_run, **options):
        cutoff = timezone.now() - timedelta(days=days)
        self.transcripts(cutoff, days, dry_run)
        self.recordings(cutoff, days, dry_run)

    def recordings(self, cutoff, days, dry_run):
        old = (
            Recording.objects.exclude(status=Recording.PURGED)
            .annotate(age_at=Coalesce("call__started_at", "started_at", "updated_at"))
            .filter(age_at__lt=cutoff)
        )
        n_files = n_bytes = 0
        for rec in old:
            path = rec.file()
            if path is not None:
                n_files += 1
                n_bytes += path.stat().st_size
            if dry_run:
                continue
            if path is not None:
                path.unlink(missing_ok=True)
            rec.status, rec.path = Recording.PURGED, ""
            rec.save(update_fields=["status", "path", "updated_at"])
        o_files, o_bytes = self.orphans(dry_run)
        verb = "Would delete" if dry_run else "Deleted"
        self.stdout.write(
            f"{verb} {n_files} recordings ({n_bytes / 2**20:.1f} MB) older than {days} days; "
            f"{verb.lower()} {o_files} orphaned recording files ({o_bytes / 2**20:.1f} MB)."
        )

    def orphans(self, dry_run):
        root = Path(settings.RECORDINGS_DIR)
        if not root.is_dir():
            return 0, 0
        known = {
            recording_relpath(p)
            for p in Recording.objects.exclude(path="").values_list("path", flat=True)
        }
        too_old = time.time() - ORPHAN_AGE_S
        n = size = 0
        for dirpath, _dirs, files in os.walk(root):
            for name in files:
                path = Path(dirpath) / name
                try:
                    st = path.lstat()
                except OSError:
                    continue
                if st.st_mtime >= too_old or str(path.relative_to(root)) in known:
                    continue
                n += 1
                size += st.st_size
                if not dry_run:
                    path.unlink(missing_ok=True)
        return n, size

    @transaction.atomic
    def transcripts(self, cutoff, days, dry_run):
        events = CallEvent.objects.filter(type=CallEvent.TURN, at__lt=cutoff)
        # A report's age is its call's start; fall back to when the report arrived.
        old_reports = CallReport.objects.annotate(age_at=Coalesce("call__started_at", "received_at")).filter(
            age_at__lt=cutoff
        )
        labels = TurnLabel.objects.filter(report__in=old_reports).exclude(caller_text="")
        with_turns = old_reports.filter(data__has_key="turns")
        n_events, n_labels, n_reports = events.count(), labels.count(), with_turns.count()
        if not dry_run:
            events.delete()
            labels.update(caller_text="")  # keep the row so the telecaller's label survives
            for report in with_turns:
                report.data.pop("turns", None)
                # queryset update so received_at (auto_now) is not bumped
                CallReport.objects.filter(pk=report.pk).update(data=report.data)
        prefix = "Would delete" if dry_run else "Deleted"
        self.stdout.write(
            f"{prefix} {n_events} turn events; {'would blank' if dry_run else 'blanked'} the caller text "
            f"on {n_labels} turn labels; "
            f"{'would remove' if dry_run else 'removed'} turns from {n_reports} reports (older than {days} days)."
        )
