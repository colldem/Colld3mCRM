"""Keep this process's translation catalog in step with the database.

Each gunicorn worker holds its own in-memory catalog, so an override saved by
one worker is invisible to the other until it reloads. This checks a small
version stamp before the view runs and reloads only when it has moved, which is
what makes an edit apply "everywhere" rather than on whichever worker served the
save. Management commands are separate processes and load on startup instead.
"""
from django.db import DatabaseError

from . import translations


class TranslationOverrideMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            translations.ensure_current()
        except DatabaseError:
            # Before the first migration there is no table yet; the interface
            # must still render, just with the shipped translations.
            pass
        return self.get_response(request)
