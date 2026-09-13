"""Switch off accounts unused for longer than Settings -> Prisijungimas allows.

Idempotent — safe to run from the worker loop. Does nothing while the setting is 0.
"""
from ...management.tracked import TrackedCommand

from ...accounts import deactivate_inactive


class Command(TrackedCommand):
    help = "Deactivate CRM accounts that have not signed in for the configured number of days."

    def handle(self, *args, **options):
        done = deactivate_inactive()
        self.stdout.write("deactivated %d inactive account(s)%s" % (len(done), (": " + ", ".join(done)) if done else ""))
