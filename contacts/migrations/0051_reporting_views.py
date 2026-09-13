"""A read-only ``reporting`` schema for data warehouses and BI tools (PostgreSQL).

Other systems must not read the application tables: those hold password hashes,
sessions, API token hashes, encrypted integration secrets and free text. These
views expose the structured part of the CRM — ids, names, codes, owners, links,
types and dates — and nothing else. ``manage.py create_reporting_role`` creates
the login role that can read only this schema.

Free text (descriptions, activity and reminder texts, e-mails, phones, addresses)
is deliberately left out; add a view in a new migration if a report needs it and
the data protection officer agrees.
"""
from django.db import migrations

VIEWS = {
    "people": """SELECT id, first_name, last_name, job_title, favourite, owner_id, created_by_id,
                        created_at, updated_at, deleted_at AS archived_at
                 FROM contacts_person WHERE merged_into_id IS NULL""",
    "companies": """SELECT id, name, company_code, vat_code, city, owner_id, created_by_id,
                           created_at, updated_at, deleted_at AS archived_at
                    FROM contacts_company WHERE merged_into_id IS NULL""",
    "person_companies": "SELECT person_id, company_id, role, is_primary FROM contacts_personcompanylink",
    "activities": """SELECT id, person_id, company_id, activity_type, created_by_id, created_at, deleted_at AS archived_at
                     FROM contacts_activity""",
    "reminders": """SELECT id, person_id, company_id, due_at, completed_at, priority, created_by_id, assigned_to_id,
                           created_at, deleted_at AS archived_at
                    FROM contacts_reminder""",
    "tags": "SELECT id, name FROM contacts_tag",
    "person_tags": "SELECT person_id, tag_id FROM contacts_person_tags",
    "company_tags": "SELECT company_id, tag_id FROM contacts_company_tags",
    "categories": "SELECT id, name FROM contacts_category",
    "person_categories": "SELECT person_id, category_id FROM contacts_person_categories",
    "company_categories": "SELECT company_id, category_id FROM contacts_company_categories",
    "users": """SELECT u.id, u.username, u.first_name, u.last_name, u.is_active, p.role
                FROM auth_user u LEFT JOIN contacts_userprofile p ON p.user_id = u.id""",
    "teams": "SELECT id, name FROM contacts_team",
    "team_members": "SELECT team_id, user_id FROM contacts_team_members",
}


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("CREATE SCHEMA IF NOT EXISTS reporting", params=None)
    for name, query in VIEWS.items():
        schema_editor.execute("CREATE OR REPLACE VIEW reporting.%s AS %s" % (name, query), params=None)


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("DROP SCHEMA IF EXISTS reporting CASCADE", params=None)


class Migration(migrations.Migration):
    dependencies = [("contacts", "0050_job_heartbeat")]
    operations = [migrations.RunPython(forwards, backwards)]
