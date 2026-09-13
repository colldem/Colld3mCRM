"""Purge audit rows past the retention set in Settings -> Žurnalas.

Idempotent — safe to run from the worker loop. Does nothing while retention is 0.
"""
from django.core.management.base import BaseCommand

from ...audit import purge_expired


class Command(BaseCommand):
    help = "Delete audit log rows older than the configured retention."

    def handle(self, *args, **options):
        self.stdout.write("purged %d audit row(s)" % purge_expired())
