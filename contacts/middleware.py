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


class ReadOnlyRoleMiddleware:
    """Server-side guarantee behind the "Skaitytojas" role: whatever the page
    shows, a reader cannot open an editing page or change shared data. Personal
    settings (profile, password, menu, notifications, saved filters) stay usable."""

    # Pages whose only purpose is to create or change records, refused on any method.
    EDITING_PAGES = {
        "create", "person-create", "company-create", "edit", "company-edit",
        "activity-create", "activity-edit", "company-activity-create", "company-activity-edit",
        "reminder-create", "reminder-edit", "reminder-delete", "reminder-complete",
        "calendar-event-create", "calendar-event-update", "calendar-event-delete",
        "duplicate-list", "duplicate-dismiss", "duplicate-merge", "duplicate-merge-all",
        "field-edit", "company-field-edit", "inline-update", "bulk-action", "company-bulk-action",
        "archive-bulk", "restore", "company-restore", "archive", "company-archive", "import-errors",
    }
    # The only writes a reader may make: their own session, profile and preferences.
    PERSONAL_WRITES = {
        "logout", "set_language", "settings", "profile-avatar", "settings-password",
        "settings-my-notifications", "settings-menu", "reminder-mark-read",
        "saved-filter-create", "company-saved-filter-create", "saved-filter-update",
        # POSTs that change nothing: a deliberate, audited reveal, and searches by
        # personal code sent in the body so the code stays out of URLs.
        "personal-code-reveal", "search-personal-code", "search-suggest",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        user = getattr(request, "user", None)
        if not (user and user.is_authenticated) or request.path.startswith("/api/"):
            return None
        from .permissions import is_read_only

        if not is_read_only(user):
            return None
        name = request.resolver_match.url_name if request.resolver_match else ""
        unsafe = request.method not in ("GET", "HEAD", "OPTIONS")
        if name not in self.EDITING_PAGES and not (unsafe and name not in self.PERSONAL_WRITES):
            return None
        return self.refuse(request)

    @staticmethod
    def refuse(request):
        from django.contrib import messages
        from django.http import JsonResponse
        from django.shortcuts import redirect
        from django.utils.http import url_has_allowed_host_and_scheme
        from django.utils.translation import gettext

        from .audit import log as audit_log
        from .models import AuditLog

        message = gettext("Jūsų rolė leidžia tik peržiūrėti duomenis.")
        audit_log(AuditLog.UPDATE, request=request, target_type="access", target_label=request.path[:200],
                  detail={"refused": "read_only", "method": request.method})
        if request.headers.get("x-requested-with") == "XMLHttpRequest" or "json" in request.headers.get("accept", ""):
            return JsonResponse({"error": message}, status=403)
        messages.error(request, message)
        back = request.META.get("HTTP_REFERER", "")
        if not url_has_allowed_host_and_scheme(back, {request.get_host()}, require_https=request.is_secure()) or back.endswith(request.path):
            back = "/"
        return redirect(back)


class SecurityHeadersMiddleware:
    """Content-Security-Policy with a per-request nonce, plus Permissions-Policy.

    Scripts run only from this origin or inline with the request's nonce
    (``{{ csp_nonce }}``); no inline event handlers (see static/js/behaviors.js),
    no plugins, no framing, forms post only here. Inline ``style`` attributes stay
    allowed — they cannot run code. ``CRM_CSP_REPORT_ONLY=true`` sends the policy
    as report-only while checking a new deployment.
    """

    PERMISSIONS_POLICY = ("accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), "
                          "microphone=(), payment=(), usb=()")

    def __init__(self, get_response):
        self.get_response = get_response

    @staticmethod
    def policy(nonce):
        return "; ".join((
            "default-src 'self'",
            "script-src 'self' 'nonce-%s'" % nonce,
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data: blob:",
            "font-src 'self' data:",
            "connect-src 'self'",
            "manifest-src 'self'",
            "worker-src 'self'",
            "frame-src 'none'",
            "frame-ancestors 'none'",
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self'",
        ))

    def __call__(self, request):
        import secrets

        from django.conf import settings

        request.csp_nonce = secrets.token_urlsafe(18)
        response = self.get_response(request)
        header = "Content-Security-Policy-Report-Only" if settings.CRM_CSP_REPORT_ONLY else "Content-Security-Policy"
        response.setdefault(header, self.policy(request.csp_nonce))
        response.setdefault("Permissions-Policy", self.PERMISSIONS_POLICY)
        return response
