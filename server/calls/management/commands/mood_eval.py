from datetime import date, datetime, time

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from calls.evaluation import EMOTIONS, GATE_EMOTIONS, GATE_PRECISION, gate_passes, score
from calls.models import TurnLabel


class Command(BaseCommand):
    help = "Score the agent's mood readings against telecaller labels (go-live gate for MOOD_ENABLED)."

    def add_arguments(self, parser):
        parser.add_argument("--since", help="Only reports received on or after this date (YYYY-MM-DD, local time).")

    def handle(self, *args, since=None, **options):
        rows = TurnLabel.objects.exclude(label="")
        if since:
            try:
                day = date.fromisoformat(since)
            except ValueError as e:
                raise CommandError(f"--since must be YYYY-MM-DD: {e}") from e
            rows = rows.filter(report__received_at__gte=timezone.make_aware(datetime.combine(day, time.min)))

        pairs = list(rows.values_list("label", "predicted"))
        result = score(pairs)
        counted = sum(1 for label, _ in pairs if label != "unclear")
        out = self.stdout.write

        out(f"Accuracy: {result['accuracy']:.2f} ({counted} labelled turns, {len(pairs) - counted} unclear skipped)")
        out("")
        out(f"{'emotion':<12} {'precision':>9} {'recall':>7} {'support':>8}")
        for e in EMOTIONS:
            m = result["per_emotion"][e]
            out(f"{e:<12} {m['precision']:>9.2f} {m['recall']:>7.2f} {m['support']:>8}")

        out("")
        out("Confusion (rows = label, columns = predicted):")
        out(" " * 12 + "".join(f"{e[:6]:>7}" for e in EMOTIONS))
        for label in EMOTIONS:
            row = result["confusion"].get(label, {})
            out(f"{label:<12}" + "".join(f"{row.get(p, 0):>7}" for p in EMOTIONS))

        out("")
        gate = ", ".join(f"{e} {result['per_emotion'][e]['precision']:.2f}" for e in GATE_EMOTIONS)
        verdict = "PASS" if gate_passes(result) else "FAIL"
        out(f"{verdict}: go-live gate needs precision >= {GATE_PRECISION} for {', '.join(GATE_EMOTIONS)} ({gate})")
