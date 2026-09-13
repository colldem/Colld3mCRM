"""Print the data dictionary (docs/paketas/04-duomenu-zodynas.md) generated from the models."""
from django.core.management.base import BaseCommand, CommandError

from ...data_dictionary import render, unclassified


class Command(BaseCommand):
    help = "Render the data dictionary as Markdown."

    def handle(self, *args, **options):
        missing = unclassified()
        if missing:
            raise CommandError("Classify in contacts/data_dictionary.py first: %s" % ", ".join(missing))
        self.stdout.write(render(), ending="")
