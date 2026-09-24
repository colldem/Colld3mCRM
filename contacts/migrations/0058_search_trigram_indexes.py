"""Trigram indexes for the list and global search (PostgreSQL only).

Search is "contains" (``icontains`` → ``UPPER(col::text) LIKE UPPER('%term%')``),
which no ordinary index can serve; pg_trgm GIN indexes on exactly that
expression can. SQLite and Oracle keep working without them, only slower.

pg_trgm is a trusted extension (PostgreSQL 13+): the database owner may create
it. Where that is not allowed, the migration says so and leaves search on
sequential scans instead of failing the deployment.
"""
from django.db import migrations, transaction

COLUMNS = {
    "contacts_person": ("first_name", "last_name", "job_title"),
    "contacts_phonenumber": ("number",),
    "contacts_emailaddress": ("email",),
    "contacts_postaladdress": ("address",),
    "contacts_weblink": ("url",),
    "contacts_customvalue": ("value",),
    "contacts_company": ("name", "company_code", "vat_code", "address", "phone", "email", "url"),
    # Global search also looks through the history and reminder texts.
    "contacts_activity": ("text",),
    "contacts_reminder": ("text",),
}


def _name(table, column):
    return "%s_%s_trgm" % (table.removeprefix("contacts_"), column)


def create(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    try:
        with transaction.atomic():
            schema_editor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    except Exception as error:  # noqa: BLE001 - reported, search still works without the indexes
        print("\n  pg_trgm unavailable (%s); search stays unindexed." % error)
        return
    for table, columns in COLUMNS.items():
        for column in columns:
            schema_editor.execute('CREATE INDEX IF NOT EXISTS %s ON %s USING gin (UPPER(%s::text) gin_trgm_ops)'
                                  % (_name(table, column), table, column))


def drop(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for table, columns in COLUMNS.items():
        for column in columns:
            schema_editor.execute("DROP INDEX IF EXISTS %s" % _name(table, column))


class Migration(migrations.Migration):
    dependencies = [("contacts", "0057_duplicate_candidates")]

    operations = [migrations.RunPython(create, drop)]
