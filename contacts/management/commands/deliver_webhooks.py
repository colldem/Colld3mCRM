"""Deliver queued webhooks (H4). Run from the worker loop."""
from django.core.management.base import BaseCommand

from ...webhooks import deliver_pending


class Command(BaseCommand):
    help = "POST pending webhook deliveries."

    def handle(self, *args, **options):
        self.stdout.write("webhooks delivered: %d" % deliver_pending())
