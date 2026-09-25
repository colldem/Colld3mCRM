"""The background commands and whether each is keeping up.

One list for the worker loop's health: the system health page (Settings →
Sistemos būklė), the admins' banner, /health/jobs for an outside monitor
(Uptime Kuma, Zabbix) and /metrics all read it. A command reports its own last
success and failure (management/tracked.py, JobHeartbeat); "late" means no
success for longer than it should ever take to come round again.
"""
from datetime import timedelta

from django.utils import timezone
from django.utils.translation import gettext_lazy as _

# The loop (scripts/worker.sh) runs everything every few minutes; a Kubernetes
# CronJob runs the daily ones once a day — so each gets the looser of the two.
FREQUENT = timedelta(minutes=45)
DAILY = timedelta(hours=26)

JOBS = {
    "send_notifications": (_("El. pašto pranešimai"), FREQUENT),
    "fetch_mail": (_("Gautų laiškų prisegimas"), FREQUENT),
    "deliver_webhooks": (_("Webhook'ų pristatymas"), FREQUENT),
    "run_automations": (_("Automatikos taisyklės"), FREQUENT),
    "complete_past_meetings": (_("Praėjusių susitikimų užbaigimas"), FREQUENT),
    "find_duplicates": (_("Dublikatų paieška"), FREQUENT),
    "refresh_analytics": (_("Analitikos skaičiai"), FREQUENT),
    "extend_recurrences": (_("Pasikartojantys priminimai"), DAILY),
    "deactivate_inactive_users": (_("Neaktyvių paskyrų išjungimas"), DAILY),
    "purge_audit_log": (_("Žurnalo valymas"), DAILY),
    "apply_retention": (_("Saugojimo terminai"), DAILY),
}

OK, LATE, FAILING, NEVER = "ok", "late", "failing", "never"


def job_states(now=None):
    """One row per command: last success, last failure and error, and its state."""
    from .models import JobHeartbeat

    now = now or timezone.now()
    beats = {beat.name: beat for beat in JobHeartbeat.objects.filter(name__in=JOBS)}
    rows = []
    for name, (label, allowed) in JOBS.items():
        beat = beats.get(name)
        success = beat.last_success_at if beat else None
        failure = beat.last_failure_at if beat else None
        if failure and (success is None or failure > success):
            state = FAILING
        elif success is None:
            state = NEVER
        elif now - success > allowed:
            state = LATE
        else:
            state = OK
        rows.append({"name": name, "label": label, "state": state, "last_success_at": success,
                     "last_failure_at": failure, "last_error": beat.last_error if beat and state == FAILING else "",
                     "allowed": allowed})
    return rows


def overall(rows):
    """"ok", "degraded", or "no-worker" when no command has ever reported (e.g. staging)."""
    if not any(row["last_success_at"] or row["last_failure_at"] for row in rows):
        return "no-worker"
    return "ok" if all(row["state"] == OK for row in rows) else "degraded"
