"""Show the event kind and its end in the reporting view.

Migration 0054 turned a reminder into a calendar event: it can now be a call, a
meeting or a plain reminder, and it can span a period. The reporting view still
described the old shape, so every event in the warehouse looked like a reminder
with no end — a report counting meetings could not be written at all.

``description`` and ``meeting_url`` stay out: 0051 keeps free text out of this
schema by design, and lifting that is the data protection officer's call, not a
side effect of this fix.
"""
from django.db import migrations

REMINDERS = """SELECT id, person_id, company_id, kind, due_at, end_at, completed_at, priority,
                      created_by_id, assigned_to_id, created_at, deleted_at AS archived_at
               FROM contacts_reminder"""

PREVIOUS = """SELECT id, person_id, company_id, due_at, completed_at, priority, created_by_id, assigned_to_id,
                     created_at, deleted_at AS archived_at
              FROM contacts_reminder"""


def _replace(schema_editor, query):
    if schema_editor.connection.vendor != "postgresql":
        return
    # The column list changes, and CREATE OR REPLACE VIEW cannot do that.
    schema_editor.execute("DROP VIEW IF EXISTS reporting.reminders", params=None)
    schema_editor.execute("CREATE VIEW reporting.reminders AS %s" % query, params=None)


def forwards(apps, schema_editor):
    _replace(schema_editor, REMINDERS)


def backwards(apps, schema_editor):
    _replace(schema_editor, PREVIOUS)


class Migration(migrations.Migration):
    dependencies = [("contacts", "0054_event_kind")]
    operations = [migrations.RunPython(forwards, backwards)]
