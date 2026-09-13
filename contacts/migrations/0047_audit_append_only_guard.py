"""Append-only audit log in the database itself (PostgreSQL).

The application already refuses to change audit rows; this makes an accidental
or malicious UPDATE/DELETE through the application's database role fail too.
Allowed: the retention purge (contacts.audit.purge_expired sets
``crm.audit_purge`` for its own transaction) and detaching a deleted user
(actor_id -> NULL with every other column unchanged). SQLite, used only for
local development and tests, relies on the application-level guard.
"""
from django.db import migrations

# One statement per execute: psycopg sends parameterised queries one at a time.
CREATE = ["""
CREATE OR REPLACE FUNCTION crm_audit_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF current_setting('crm.audit_purge', true) = 'on' THEN
      RETURN OLD;
    END IF;
    RAISE EXCEPTION 'audit log is append-only';
  END IF;
  IF NEW.actor_id IS NULL AND OLD.actor_id IS NOT NULL
     AND (NEW.id, NEW.actor_label, NEW.action, NEW.target_type, NEW.target_id, NEW.target_label, NEW.field,
          NEW.old_value, NEW.new_value, NEW.detail::text, NEW.ip, NEW.created_at)
         IS NOT DISTINCT FROM
         (OLD.id, OLD.actor_label, OLD.action, OLD.target_type, OLD.target_id, OLD.target_label, OLD.field,
          OLD.old_value, OLD.new_value, OLD.detail::text, OLD.ip, OLD.created_at) THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'audit log is append-only';
END
$$ LANGUAGE plpgsql
""", """
DROP TRIGGER IF EXISTS contacts_auditlog_guard ON contacts_auditlog
""", """
CREATE TRIGGER contacts_auditlog_guard BEFORE UPDATE OR DELETE ON contacts_auditlog
  FOR EACH ROW EXECUTE FUNCTION crm_audit_guard()
"""]

DROP = [
    "DROP TRIGGER IF EXISTS contacts_auditlog_guard ON contacts_auditlog",
    "DROP FUNCTION IF EXISTS crm_audit_guard()",
]


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for statement in CREATE:
            schema_editor.execute(statement, params=None)


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for statement in DROP:
            schema_editor.execute(statement, params=None)


class Migration(migrations.Migration):
    dependencies = [("contacts", "0046_audit_retention")]
    operations = [migrations.RunPython(forwards, backwards)]
