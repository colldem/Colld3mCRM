"""Roll every recurring reminder's materialised horizon forward (G3).

Idempotent. Occurrences reach ~400 days ahead, so monthly is plenty; it also
runs at the top of send_notifications.
"""
from django.core.management.base import BaseCommand

from ...recurrence import extend_all


class Command(BaseCommand):
    help = "Materialise upcoming occurrences of recurring reminders."

    def handle(self, *args, **options):
        self.stdout.write("added %d" % extend_all())
