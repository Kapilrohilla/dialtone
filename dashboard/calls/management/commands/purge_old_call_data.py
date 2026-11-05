from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models.functions import Coalesce
from django.utils import timezone

from calls.models import CallEvent, CallReport, TurnLabel


class Command(BaseCommand):
    help = (
        "Delete transcripts older than --days: turn events and report `turns`, and blank the caller's words "
        "on TurnLabel rows (telecaller labels stay). Dispositions, summaries, answers and metrics stay."
    )

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=90)
        parser.add_argument("--dry-run", action="store_true")

    @transaction.atomic
    def handle(self, *args, days, dry_run, **options):
        cutoff = timezone.now() - timedelta(days=days)
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
