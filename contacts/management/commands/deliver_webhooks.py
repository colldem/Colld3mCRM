"""Deliver queued webhooks (H4). Run from the worker loop."""
from ...management.tracked import TrackedCommand

from ...webhooks import deliver_pending


class Command(TrackedCommand):
    help = "POST pending webhook deliveries."

    def handle(self, *args, **options):
        self.stdout.write("webhooks delivered: %d" % deliver_pending())
