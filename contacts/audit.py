"""Append-only audit trail. Call :func:`log` from a view once the action succeeded."""
import logging

from .models import AuditLog


def _parse(address):
    import ipaddress

    try:
        return ipaddress.ip_address(address.strip())
    except ValueError:
        return None


def _trusted(address, networks):
    ip = _parse(address)
    return ip is not None and any(ip in network for network in networks)


def client_ip(request):
    """The client's address, as the audit trail and sign-in lockout see it.

    ``X-Forwarded-For`` is believed only when the connection comes from a proxy in
    ``CRM_TRUSTED_PROXIES``; the header is then read from the right, skipping
    trusted proxies, so a client cannot choose its address by sending the header
    itself. Without trusted proxies the connection's address is used.
    """
    if request is None:
        return None
    from django.conf import settings

    remote = request.META.get("REMOTE_ADDR") or None
    networks = getattr(settings, "CRM_TRUSTED_PROXY_NETWORKS", ())
    if not remote or not networks or not _trusted(remote, networks):
        return remote
    hops = [hop.strip() for hop in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if hop.strip()]
    for hop in reversed(hops):
        if _parse(hop) is None:
            return remote  # a malformed header is not an address to record or lock out
        if not _trusted(hop, networks):
            return hop
    return hops[0] if hops else remote


def _actor_label(actor):
    if not actor:
        return ""
    from .permissions import user_label

    return user_label(actor)


def log(action, *, request=None, actor=None, target=None, target_type="", target_id="",
        target_label="", field="", old=None, new=None, ip=None, detail=None, **extra):
    """Write one audit row. `target` fills type/id/label from a model instance.

    Extra context goes in `detail` (a dict) and/or as loose keyword arguments;
    both are merged into the stored JSON.
    """
    from .observability import current_request_id, security_event

    detail = {**(detail or {}), **extra}
    request_id = getattr(request, "request_id", "") or current_request_id()
    if request_id:
        detail.setdefault("request_id", request_id)
    if actor is None and request is not None:
        actor = getattr(request, "user", None)
    if actor is not None and not getattr(actor, "is_authenticated", False):
        actor = None
    if target is not None:
        target_type = target_type or target.__class__.__name__.lower()
        target_id = target_id or str(getattr(target, "pk", "") or "")
        target_label = target_label or str(target)
    entry = AuditLog.objects.create(
        actor=actor,
        actor_label=_actor_label(actor),
        action=action,
        target_type=target_type,
        target_id=str(target_id or ""),
        target_label=(target_label or "")[:255],
        field=field or "",
        old_value="" if old is None else str(old),
        new_value="" if new is None else str(new),
        detail=detail or {},
        ip=ip if ip is not None else client_ip(request),
    )
    # Mirror to the SIEM stream: ids and types only, no labels or values.
    security_event("audit.%s" % action, level=logging.WARNING if action == AuditLog.LOGIN_FAILED else logging.INFO,
                   action=action, actor_id=entry.actor_id, target_type=target_type, target_id=entry.target_id,
                   field=entry.field, ip=entry.ip, reason=(detail or {}).get("reason", ""))
    return entry


def log_change(action, *, request, target, field, old, new, **detail):
    """Log a field change, skipping no-op saves where the value did not change."""
    if str(old or "") == str(new or ""):
        return None
    return log(action, request=request, target=target, field=field, old=old, new=new, **detail)


AUDIT_RETENTION_MINIMUM_DAYS = 180


def _database_guard(switch, value):
    from django.db import connection

    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL crm.%s = '%s'" % (switch, "on" if value else "off"))


REDACTED = "[ištrinta]"


def sanctioned_redact(queryset):
    """Strip personal data from audit rows: who, what, where and when remain.

    Only for erasing a data subject (contacts/privacy.py). Returns the count.
    """
    from django.db import models, transaction

    with transaction.atomic():
        _database_guard("audit_redact", True)
        try:
            return models.QuerySet.update(queryset, target_label=REDACTED, old_value="", new_value="",
                                          detail={"redacted": True})
        finally:
            _database_guard("audit_redact", False)


def sanctioned_delete(queryset):
    """Delete audit rows past the application and database guards.

    Only for the retention purge and for wiping a staging clone. The database
    switch is opened for this transaction and closed again before it returns.
    """
    from django.db import transaction

    with transaction.atomic():
        _database_guard("audit_purge", True)
        try:
            return queryset._raw_delete(queryset.db)
        finally:
            _database_guard("audit_purge", False)


def purge_expired(now=None):
    """Delete audit rows older than ``SystemSettings.audit_retention_days``.

    The one sanctioned deletion: on PostgreSQL it opens the database guard for
    this transaction only, and it leaves a summary row behind. Returns the count.
    """
    from datetime import timedelta

    from django.utils import timezone

    from .models import SystemSettings

    days = SystemSettings.load().audit_retention_days
    if not days:
        return 0
    days = max(days, AUDIT_RETENTION_MINIMUM_DAYS)
    cutoff = (now or timezone.now()) - timedelta(days=days)
    count = sanctioned_delete(AuditLog.objects.filter(created_at__lt=cutoff))
    if count:
        log(AuditLog.DELETE, target_type="audit_log", target_label="retention",
            detail={"purged": count, "before": cutoff.isoformat(), "retention_days": days})
    return count
