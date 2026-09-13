"""Pull new messages from the CRM dropbox mailbox (G6). No-op without IMAP_HOST."""
from ...management.tracked import TrackedCommand

from ...mailfetch import fetch


class Command(TrackedCommand):
    help = "Fetch and file incoming CRM emails."

    def handle(self, *args, **options):
        counts = fetch()
        self.stdout.write(" ".join("%s=%d" % kv for kv in sorted(counts.items())) or "nothing to fetch")
