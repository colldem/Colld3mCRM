"""Create or update the read-only login role for reporting (PostgreSQL).

    python manage.py create_reporting_role --name crm_reporting --password-env REPORTING_PASSWORD

The role can connect and SELECT from the ``reporting`` views (migration 0051)
and nothing else: no application table, no write. Re-run to rotate the password
or after a migration adds views. The password is read from an environment
variable so it never appears in shell history or process lists.
"""
import os
import re

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from psycopg import sql


class Command(BaseCommand):
    help = "Create/update a login role that can read only the reporting schema."

    def add_arguments(self, parser):
        parser.add_argument("--name", default="crm_reporting")
        parser.add_argument("--password-env", default="REPORTING_PASSWORD",
                            help="Environment variable holding the role's password.")

    def handle(self, *args, name, password_env, **options):
        if connection.vendor != "postgresql":
            raise CommandError("The reporting role exists on PostgreSQL only.")
        if not re.fullmatch(r"[a-z_][a-z0-9_]{2,62}", name):
            raise CommandError("Role name must be lowercase letters, digits and underscores.")
        password = os.environ.get(password_env, "")
        if len(password) < 16:
            raise CommandError("Set %s to a password of at least 16 characters." % password_env)
        role = sql.Identifier(name)
        database = sql.Identifier(connection.settings_dict["NAME"])
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [name])
            verb = "ALTER" if cursor.fetchone() else "CREATE"
            cursor.execute(sql.SQL("{} ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD {}").format(
                sql.SQL(verb), role, sql.Literal(password)).as_string(cursor.connection))
            for statement in (
                "REVOKE ALL ON DATABASE {db} FROM {role}",
                "GRANT CONNECT ON DATABASE {db} TO {role}",
                "REVOKE ALL ON SCHEMA public FROM {role}",
                "REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role}",
                "GRANT USAGE ON SCHEMA reporting TO {role}",
                "GRANT SELECT ON ALL TABLES IN SCHEMA reporting TO {role}",
                "ALTER ROLE {role} SET default_transaction_read_only = on",
            ):
                cursor.execute(sql.SQL(statement).format(db=database, role=role).as_string(cursor.connection))
        self.stdout.write("%s role %s: SELECT on schema reporting only"
                          % ("created" if verb == "CREATE" else "updated", name))
