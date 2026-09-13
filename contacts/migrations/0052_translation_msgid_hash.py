"""Move Translation uniqueness from the unbounded msgid text to its SHA-256.

See the note in 0037. Existing PostgreSQL databases still carry the unique
constraint (and its pattern index) 0037 used to create; it is dropped here.
"""
import hashlib

from django.db import migrations, models


def fill_hashes(apps, schema_editor):
    Translation = apps.get_model("contacts", "Translation")
    for row in Translation.objects.all():
        row.msgid_hash = hashlib.sha256(row.msgid.encode("utf-8")).hexdigest()
        row.save(update_fields=["msgid_hash"])


def drop_old_unique(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("""
            SELECT conname FROM pg_constraint
            WHERE conrelid = 'contacts_translation'::regclass AND contype = 'u'
              AND conkey = ARRAY[(SELECT attnum FROM pg_attribute
                                  WHERE attrelid = 'contacts_translation'::regclass AND attname = 'msgid')]::smallint[]""")
        for (name,) in cursor.fetchall():
            cursor.execute('ALTER TABLE contacts_translation DROP CONSTRAINT "%s"' % name)
        cursor.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'contacts_translation' "
                       "AND indexname LIKE 'contacts_translation_msgid%%_like'")
        for (name,) in cursor.fetchall():
            cursor.execute('DROP INDEX IF EXISTS "%s"' % name)


class Migration(migrations.Migration):
    dependencies = [("contacts", "0051_reporting_views")]
    operations = [
        migrations.AddField(model_name="translation", name="msgid_hash",
                            field=models.CharField(max_length=64, null=True, editable=False)),
        migrations.RunPython(fill_hashes, migrations.RunPython.noop),
        migrations.AlterField(model_name="translation", name="msgid_hash",
                              field=models.CharField(max_length=64, unique=True, editable=False)),
        migrations.AlterModelOptions(name="translation", options={"ordering": ["id"]}),
        migrations.RunPython(drop_old_unique, migrations.RunPython.noop),
    ]
