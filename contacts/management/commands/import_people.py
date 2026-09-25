"""Load people from a CSV export of another system, in batches (bulk_import.py).

    python manage.py import_people regitra.csv --source regitra
    docker compose exec -T crm-worker python manage.py import_people - --source regitra < regitra.csv

Run it again with a newer export to update: rows are matched on
(--source, external_id). --dry-run checks the whole file without writing.
"""
import io
import sys

from django.core.management.base import BaseCommand, CommandError

from ...audit import log as audit_log
from ...bulk_import import import_people
from ...models import AuditLog
from ... import identity


class Command(BaseCommand):
    help = "Import or update people from a CSV file keyed on external_id."

    def add_arguments(self, parser):
        parser.add_argument("file", help="CSV file, or - for standard input")
        parser.add_argument("--source", required=True, help='system the ids belong to, e.g. "regitra"')
        parser.add_argument("--batch", type=int, default=2000)
        parser.add_argument("--delimiter", default=",")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        source = options["source"].strip()[:32]
        if not source:
            raise CommandError("--source is required")
        if options["file"] == "-":
            stream = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8-sig")
        else:
            try:
                stream = open(options["file"], encoding="utf-8-sig", newline="")
            except OSError as error:
                raise CommandError(str(error)) from None
        with stream:
            header = stream.readline()
            if "personal_code" in header.lower() and not identity.available():
                raise CommandError("the file has personal codes but CRM_SECRETS_KEY is not set")
            try:
                summary = import_people(_Rewound(header, stream), source=source, batch_size=max(options["batch"], 1),
                                        dry_run=options["dry_run"], delimiter=options["delimiter"])
            except ValueError as error:
                raise CommandError(str(error)) from None
        for line, message in summary["errors"][:50]:
            self.stderr.write("line %d: %s" % (line, message))
        if len(summary["errors"]) > 50:
            self.stderr.write("... and %d more errors" % (len(summary["errors"]) - 50))
        verb = "would create" if options["dry_run"] else "created"
        self.stdout.write("%s=%d updated=%d unchanged=%d errors=%d in %ss" % (
            verb, summary["created"], summary["updated"], summary["unchanged"], len(summary["errors"]),
            summary["seconds"]))
        if not options["dry_run"]:
            audit_log(AuditLog.IMPORT, target_type="person", target_label=source,
                      new="created=%d updated=%d errors=%d" % (summary["created"], summary["updated"],
                                                              len(summary["errors"])))


class _Rewound:
    """The file with its already-read header line put back in front."""

    def __init__(self, header, stream):
        self._lines = iter([header])
        self._stream = stream

    def __iter__(self):
        yield from self._lines
        yield from self._stream
