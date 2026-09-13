"""Evaluate automation rules (H2).

Idempotent — safe to run every few minutes from the worker. Does nothing until an
admin turns automations on in Settings -> Automatika.
"""
from ...management.tracked import TrackedCommand

from ...automation import run_all


class Command(TrackedCommand):
    help = "Run active CRM automation rules."

    def handle(self, *args, **options):
        self.stdout.write("automation actions: %d" % run_all())
