"""Append-only audit trail. Call :func:`log` from a view once the action succeeded."""
from .models import AuditLog


def client_ip(request):
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None


def _actor_label(actor):
    if not actor:
        return ""
    from .permissions import user_label

    return user_label(actor)


def log(action, *, request=None, actor=None, target=None, target_type="", target_id="",
        target_label="", field="", old=None, new=None, ip=None, **detail):
    """Write one audit row. `target` fills type/id/label from a model instance."""
    if actor is None and request is not None:
        actor = getattr(request, "user", None)
    if actor is not None and not getattr(actor, "is_authenticated", False):
        actor = None
    if target is not None:
        target_type = target_type or target.__class__.__name__.lower()
        target_id = target_id or str(getattr(target, "pk", "") or "")
        target_label = target_label or str(target)
    return AuditLog.objects.create(
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


def log_change(action, *, request, target, field, old, new, **detail):
    """Log a field change, skipping no-op saves where the value did not change."""
    if str(old or "") == str(new or ""):
        return None
    return log(action, request=request, target=target, field=field, old=old, new=new, **detail)
