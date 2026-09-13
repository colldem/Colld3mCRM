"""Let the erasure of a data subject redact audit rows, and nothing else.

Extends the append-only guard from 0047: while ``crm.audit_redact`` is on for
the transaction (contacts.audit.sanctioned_redact), an UPDATE may change the
label, the old/new values and the detail of a row — the personal data — but
not who acted, what was done, to which record, from where, or when.
"""
from django.db import migrations

FUNCTION = """
CREATE OR REPLACE FUNCTION crm_audit_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF current_setting('crm.audit_purge', true) = 'on' THEN
      RETURN OLD;
    END IF;
    RAISE EXCEPTION 'audit log is append-only';
  END IF;
  IF current_setting('crm.audit_redact', true) = 'on'
     AND (NEW.id, NEW.actor_id, NEW.actor_label, NEW.action, NEW.target_type, NEW.target_id, NEW.field,
          NEW.ip, NEW.created_at)
         IS NOT DISTINCT FROM
         (OLD.id, OLD.actor_id, OLD.actor_label, OLD.action, OLD.target_type, OLD.target_id, OLD.field,
          OLD.ip, OLD.created_at) THEN
    RETURN NEW;
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
"""


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(FUNCTION, params=None)


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        from importlib import import_module

        previous = import_module("contacts.migrations.0047_audit_append_only_guard")
        schema_editor.execute(previous.CREATE[0], params=None)


class Migration(migrations.Migration):
    dependencies = [("contacts", "0047_audit_append_only_guard")]
    operations = [migrations.RunPython(forwards, backwards)]
