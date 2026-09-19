from django.apps import AppConfig


class ContactsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "contacts"

    def ready(self):
        from . import record_blocks_demo, signals, translations  # noqa: F401

        # Sample rows in the registry blocks, for looking at the layout before
        # the integration exists. Off unless asked for, never in production.
        if record_blocks_demo.enabled():
            record_blocks_demo.install()

        # Remember the shipped translations before anything overrides them, so
        # clearing an override can restore the original.
        try:
            translations.capture_defaults()
        except Exception:  # nosec B110  # pragma: no cover - catalogs are built lazily
            pass
