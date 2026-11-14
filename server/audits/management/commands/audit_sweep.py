from django.core.management.base import BaseCommand

from audits import run


class Command(BaseCommand):
    help = (
        "Re-queue call audits a restart left queued or running (gives up after a few attempts). Audits run in "
        "this process's background threads, so the command waits for them before it exits."
    )

    def handle(self, *args, **options):
        n = run.sweep(limit=1000)
        if run._pool is not None:
            run._pool.shutdown(wait=True)
        self.stdout.write(f"Revived {n} stuck audits.")
