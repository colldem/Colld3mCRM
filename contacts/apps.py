from django.apps import AppConfig
from django.db.backends.signals import connection_created


def _unicode_lower(sender, connection, **kwargs):
    """SQLite's LOWER() folds only ASCII, so "Ž" would never match "ž". PostgreSQL
    and Oracle fold every letter; the local and test database should too, or the
    duplicate check (models.match_key) behaves differently there."""
    if connection.vendor == "sqlite":
        connection.connection.create_function("LOWER", 1, lambda value: None if value is None else value.lower(),
                                              deterministic=True)


class ContactsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "contacts"

    def ready(self):
        from . import signals, translations  # noqa: F401

        connection_created.connect(_unicode_lower)

        # Remember the shipped translations before anything overrides them, so
        # clearing an override can restore the original.
        try:
            translations.capture_defaults()
        except Exception:  # nosec B110  # pragma: no cover - catalogs are built lazily
            pass
