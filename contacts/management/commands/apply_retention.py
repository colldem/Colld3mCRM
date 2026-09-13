"""Delete archived records and incoming mail past the retention set in
Settings -> Duomenų apsauga. Idempotent; does nothing while both are 0."""
from ...management.tracked import TrackedCommand

from ...privacy import apply_retention


class Command(TrackedCommand):
    help = "Apply the personal data retention periods."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Only report what would be deleted.")

    def handle(self, *args, **options):
        if options["dry_run"]:
            from ...privacy import retention_candidates

            counts = {key: queryset.count() for key, queryset in retention_candidates().items()}
            self.stdout.write("would delete: " + ", ".join("%s=%d" % item for item in counts.items()))
            return
        done = apply_retention()
        self.stdout.write("retention: " + ", ".join("%s=%d" % item for item in done.items()))
