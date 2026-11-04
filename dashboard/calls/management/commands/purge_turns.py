from django.core.management.base import BaseCommand
from django.db import transaction

from calls.models import CallReport, TurnLabel


class Command(BaseCommand):
    help = "Delete all labelled caller turns and strip caller speech (`turns`) from stored reports."

    @transaction.atomic
    def handle(self, *args, **options):
        labels, _ = TurnLabel.objects.all().delete()
        stripped = 0
        for report in CallReport.objects.filter(data__has_key="turns"):
            report.data.pop("turns", None)
            report.save(update_fields=["data"])
            stripped += 1
        self.stdout.write(f"Deleted {labels} turn labels; removed turns from {stripped} reports.")
