"""Prometheus metrics at /metrics (text exposition format, no extra library).

Values are read from the database and the scanner at scrape time, so every web
process answers the same — request rates and latencies belong to the reverse
proxy or ingress, which sees all processes. Protected by ``CRM_METRICS_TOKEN``
(``Authorization: Bearer <token>``); without a token the endpoint does not exist.
"""
import hmac
import socket
from datetime import timedelta

from django.conf import settings
from django.db import connection
from django.http import Http404, HttpResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

JOBS = ("send_notifications", "fetch_mail", "deliver_webhooks", "run_automations", "extend_recurrences",
        "deactivate_inactive_users", "purge_audit_log", "apply_retention", "find_duplicates",
        "refresh_analytics")


def _escape(value):
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


class Exposition:
    def __init__(self):
        self.lines = []

    def metric(self, name, kind, help_text, samples):
        self.lines.append("# HELP %s %s" % (name, help_text))
        self.lines.append("# TYPE %s %s" % (name, kind))
        for labels, value in samples:
            label_text = ",".join('%s="%s"' % (key, _escape(val)) for key, val in labels.items())
            self.lines.append("%s%s %s" % (name, "{%s}" % label_text if label_text else "", value))

    def render(self):
        return "\n".join(self.lines) + "\n"


def _clamav_up():
    if not settings.CRM_CLAMAV_HOST:
        return None
    try:
        with socket.create_connection((settings.CRM_CLAMAV_HOST, settings.CRM_CLAMAV_PORT), timeout=3) as conn:
            conn.sendall(b"zPING\0")
            return 1 if conn.recv(16).startswith(b"PONG") else 0
    except OSError:
        return 0


def collect():
    from django.contrib.auth import get_user_model

    from .models import (Activity, ApiToken, AuditLog, Company, IncomingMail, JobHeartbeat, Person, Reminder,
                         UserProfile, WebhookDelivery)

    out = Exposition()
    now = timezone.now()
    version = (settings.BASE_DIR / "VERSION").read_text().strip() if (settings.BASE_DIR / "VERSION").exists() else ""
    out.metric("crm_info", "gauge", "CRM build and tier.",
               [({"version": version, "environment": settings.CRM_ENVIRONMENT}, 1)])
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        database_up = 1
    except Exception:
        database_up = 0
    out.metric("crm_database_up", "gauge", "Whether the database answered.", [({}, database_up)])
    clamav = _clamav_up()
    if clamav is not None:
        out.metric("crm_clamav_up", "gauge", "Whether the malware scanner answered PING.", [({}, clamav)])
    if not database_up:
        return out.render()

    active = {"deleted_at__isnull": True}
    out.metric("crm_records", "gauge", "Active records by kind.", [
        ({"kind": "person"}, Person.objects.filter(**active).count()),
        ({"kind": "company"}, Company.objects.filter(**active).count()),
        ({"kind": "activity"}, Activity.objects.filter(**active).count()),
        ({"kind": "reminder"}, Reminder.objects.filter(**active).count()),
    ])
    users = get_user_model().objects.filter(is_active=True)
    out.metric("crm_users_active", "gauge", "Active CRM accounts.", [
        ({"source": "directory"}, users.filter(crm_profile__directory_managed=True).count()),
        ({"source": "local"}, users.exclude(crm_profile__directory_managed=True).count()),
    ])
    since = now - timedelta(hours=24)
    failures = AuditLog.objects.filter(action=AuditLog.LOGIN_FAILED, created_at__gte=since)
    out.metric("crm_login_failures_24h", "gauge", "Failed sign-ins in the last 24 hours, by reason.", [
        ({"reason": "password"}, failures.exclude(detail__has_key="reason").count()),
        ({"reason": "locked_out"}, failures.filter(detail__reason="locked_out").count()),
        ({"reason": "directory"}, failures.filter(detail__reason="directory").count()),
    ])
    out.metric("crm_read_only_refusals_24h", "gauge", "Writes refused for readers in the last 24 hours.",
               [({}, AuditLog.objects.filter(target_type="access", created_at__gte=since).count())])
    tokens = ApiToken.objects.filter(revoked_at__isnull=True)
    out.metric("crm_api_tokens", "gauge", "Unrevoked API tokens by state.", [
        ({"state": "valid"}, tokens.filter(expires_at__gt=now + timedelta(days=14)).count()),
        ({"state": "expiring_14d"}, tokens.filter(expires_at__gt=now, expires_at__lte=now + timedelta(days=14)).count()),
        ({"state": "expired"}, tokens.filter(expires_at__lte=now).count()),
        ({"state": "no_expiry"}, tokens.filter(expires_at__isnull=True).count()),
    ])
    pending = WebhookDelivery.objects.filter(delivered_at__isnull=True)
    out.metric("crm_webhook_deliveries_pending", "gauge", "Webhook deliveries not yet delivered.",
               [({}, pending.count())])
    out.metric("crm_incoming_mail_unmatched", "gauge", "Fetched e-mails not attached to a record.",
               [({}, IncomingMail.objects.filter(resolved_at__isnull=True).count())])
    beats = {beat.name: beat for beat in JobHeartbeat.objects.all()}
    out.metric("crm_job_last_success_timestamp_seconds", "gauge",
               "Unix time a background command last succeeded (0 = never).",
               [({"job": job}, int(beats[job].last_success_at.timestamp()) if job in beats and beats[job].last_success_at else 0)
                for job in JOBS])
    out.metric("crm_job_last_failure_timestamp_seconds", "gauge",
               "Unix time a background command last failed (0 = never).",
               [({"job": job}, int(beats[job].last_failure_at.timestamp()) if job in beats and beats[job].last_failure_at else 0)
                for job in JOBS])
    out.metric("crm_directory_managed_profiles", "gauge", "Profiles whose role follows directory groups.",
               [({}, UserProfile.objects.filter(directory_managed=True).count())])
    return out.render()


@require_GET
def metrics_view(request):
    token = settings.CRM_METRICS_TOKEN
    if not token:
        raise Http404
    supplied = request.headers.get("authorization", "")
    if not hmac.compare_digest(supplied.encode(), ("Bearer " + token).encode()):
        return HttpResponse("unauthorized\n", status=401, content_type="text/plain")
    return HttpResponse(collect(), content_type="text/plain; version=0.0.4; charset=utf-8")
