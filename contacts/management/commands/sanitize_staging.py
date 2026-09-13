"""Strip a restored production dump of everything that could reach the outside,
and of the personal data in it.

Run right after ``pg_restore`` on a non-production tier. ``CRM_ENVIRONMENT``
already forces SMTP, IMAP, Entra and webhook delivery off at runtime; this is the
second layer, clearing the credentials and switches the dump carried with it so
the clone is also harmless if it is ever pointed at a production environment by
mistake.

It then anonymises the clone (contacts/anonymize.py): names, contact details,
texts, attachment files, users, mail, the audit trail and logs are replaced or
removed, keeping the data's shape for testing. ``--keep-personal-data`` skips
that step — only for a documented, approved reason.

Refuses to run on production — this deletes real configuration and data.
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ...models import ApiToken, SystemSettings, Webhook

BLANKED = [
    "email_host", "email_host_user", "email_host_password", "email_from",
    "imap_host", "imap_user", "imap_password",
    "oidc_tenant_id", "oidc_client_id", "oidc_client_secret",
]
SWITCHED_OFF = [
    "notifications_enabled", "imap_enabled", "oidc_enabled",
    "oidc_create_users", "automations_enabled",
]


class Command(BaseCommand):
    help = "Clear outbound integration config from a restored dump (staging only)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force", action="store_true",
            help="Run even on a production tier. Never use this on the live CRM.")
        parser.add_argument(
            "--keep-personal-data", action="store_true",
            help="Clear integrations only; leave the personal data in the clone.")

    def handle(self, *args, **options):
        if not settings.CRM_ISOLATED and not options["force"]:
            raise CommandError(
                "Refusing to run on CRM_ENVIRONMENT=%s. This clears SMTP, IMAP, Entra "
                "and webhook configuration. Set CRM_ENVIRONMENT=staging, or pass "
                "--force if you really mean it." % settings.CRM_ENVIRONMENT)

        system = SystemSettings.load()
        for field in BLANKED:
            setattr(system, field, "")
        for field in SWITCHED_OFF:
            setattr(system, field, False)
        system.site_base_url = settings.CRM_BASE_URL
        system.save(update_fields=BLANKED + SWITCHED_OFF + ["site_base_url"])

        hooks = Webhook.objects.filter(active=True).update(active=False)
        tokens = ApiToken.objects.count()
        ApiToken.objects.all().delete()

        self.stdout.write(
            "sanitised: integrations cleared, %d webhook(s) disabled, %d API token(s) removed"
            % (hooks, tokens))
        if options["keep_personal_data"]:
            self.stdout.write("personal data KEPT (--keep-personal-data)")
            return
        from ...anonymize import anonymize

        counts = anonymize()
        self.stdout.write("anonymised: " + ", ".join("%s=%d" % item for item in counts.items()))
