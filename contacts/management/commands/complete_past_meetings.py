"""Close meetings whose slot has passed.

Calls and plain reminders stay open until somebody ticks them off; a meeting is
over when it is over. The lists already hide these (`reminder_queries.open_q`);
this writes the fact down so exports and analytics agree. Idempotent.
"""
from ...management.tracked import TrackedCommand

from ...reminder_queries import autocomplete_past_meetings


class Command(TrackedCommand):
    help = "Mark meetings that have already finished as completed."

    def handle(self, *args, **options):
        self.stdout.write("completed %d" % autocomplete_past_meetings())
