"""Evaluate automation rules (H2).

Idempotent — safe to run every few minutes from the worker. Does nothing until an
admin turns automations on in Settings -> Automatika.
"""
from django.core.management.base import BaseCommand

from ...automation import run_all


class Command(BaseCommand):
    help = "Run active CRM automation rules."

    def handle(self, *args, **options):
        self.stdout.write("automation actions: %d" % run_all())
