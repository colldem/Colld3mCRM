from django.apps import AppConfig


class ContactsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "contacts"

    def ready(self):
        from . import signals, translations  # noqa: F401

        # Remember the shipped translations before anything overrides them, so
        # clearing an override can restore the original.
        try:
            translations.capture_defaults()
        except Exception:  # pragma: no cover - catalogs are built lazily
            pass
