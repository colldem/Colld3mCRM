"""Rebuild the duplicate review list (Dublikatai) in the background.

The worker loop runs it every cycle; the page itself only reads the stored
pairs, so opening it costs the same with 5,000 or 800,000 contacts."""
from ...management.tracked import TrackedCommand

from ...duplicates import scan_duplicates


class Command(TrackedCommand):
    help = "Find duplicate contacts and companies for the review list."

    def handle(self, *args, **options):
        summary = scan_duplicates()
        if summary is None:
            self.stdout.write("duplicates: checking is switched off")
            return
        self.stdout.write("duplicates: " + "; ".join(
            "%s pairs=%d added=%d removed=%d skipped_groups=%d" % (kind, s["pairs"], s["added"], s["removed"], s["skipped_groups"])
            for kind, s in summary.items()))
