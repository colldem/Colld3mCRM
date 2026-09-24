"""Recount the heavy analytics numbers for everyone who sees every record.

The worker loop runs it every cycle; it does work only when the stored numbers
are older than analytics_views.SNAPSHOT_REFRESH_AFTER, so admins and managers
open Analitika without waiting for millions of rows to be counted. Old
per-user snapshots are dropped."""
from datetime import timedelta

from django.utils import timezone

from ...analytics_views import (DEFAULT_PERIOD, SNAPSHOT_REFRESH_AFTER, _communication_numbers,
                                _overview_numbers, _snapshot_key)
from ...management.tracked import TrackedCommand
from ...models import AnalyticsSnapshot

PAGES = {"overview": _overview_numbers, "communication": _communication_numbers}


class Command(TrackedCommand):
    help = "Refresh the precomputed analytics numbers."

    def handle(self, *args, **options):
        now = timezone.now()
        days = DEFAULT_PERIOD
        refreshed = []
        for name, compute in PAGES.items():
            key = _snapshot_key(name, days, None)
            if AnalyticsSnapshot.objects.filter(key=key, computed_at__gte=now - SNAPSHOT_REFRESH_AFTER).exists():
                continue
            AnalyticsSnapshot.objects.update_or_create(key=key, defaults={"payload": compute(None, days),
                                                                          "computed_at": timezone.now()})
            refreshed.append(name)
        dropped, _ = AnalyticsSnapshot.objects.filter(computed_at__lt=now - timedelta(days=1)).delete()
        self.stdout.write("analytics: refreshed=%s dropped=%d" % (",".join(refreshed) or "-", dropped))
