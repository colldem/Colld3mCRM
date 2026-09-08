"""Recurring reminders (G3).

Every occurrence is a real ``Reminder`` row so the calendar, bell, list and
email notifications need no special-casing. The rule lives on the series root;
children point back with ``recurrence_parent``. ``extend`` only ever *appends*
occurrences past the last one, so a child edited or completed on its own is
never disturbed — "apply to all future" deletes the tail and re-appends.
"""
import calendar
from datetime import datetime, time, timedelta

from django.utils import timezone

from .models import Reminder


def _add_months(dt, months):
    total = dt.month - 1 + months
    year = dt.year + total // 12
    month = total % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def _step(dt, freq, interval):
    if freq == "daily":
        return dt + timedelta(days=interval)
    if freq == "weekly":
        return dt + timedelta(weeks=interval)
    if freq == "monthly":
        return _add_months(dt, interval)
    if freq == "yearly":
        return _add_months(dt, 12 * interval)
    return None


def occurrences(root, *, now=None):
    """Yield due_at datetimes for the rule, starting at the root's own due_at."""
    freq = root.recurrence_freq
    if not freq:
        return
    now = now or timezone.now()
    interval = max(1, root.recurrence_interval or 1)
    horizon = now + timedelta(days=Reminder.RECURRENCE_HORIZON_DAYS)
    until = None
    if root.recurrence_until:
        until = timezone.make_aware(
            datetime.combine(root.recurrence_until, time.max), timezone.get_current_timezone())
    limit = root.recurrence_count or Reminder.RECURRENCE_MAX_OCCURRENCES
    dt = root.due_at
    count = 0
    while dt <= horizon and count < limit and (until is None or dt <= until):
        yield dt
        count += 1
        dt = _step(dt, freq, interval)


def extend(root, *, now=None):
    """Append missing occurrences up to the horizon. Returns how many were created."""
    if not root.is_recurring:
        return 0
    slot = (root.end_at - root.due_at) if root.end_at else None
    last = (root.recurrence_children.order_by("-due_at").values_list("due_at", flat=True).first()
            or root.due_at)
    created = 0
    for dt in occurrences(root, now=now):
        if dt <= last:
            continue
        Reminder.objects.create(
            recurrence_parent=root, due_at=dt, end_at=(dt + slot) if slot else None,
            text=root.text, priority=root.priority,
            assigned_to_id=root.assigned_to_id or root.created_by_id,
            person_id=root.person_id, company_id=root.company_id,
            created_by_id=root.created_by_id,
        )
        created += 1
    return created


def apply_to_future(root):
    """Rebuild the tail of a series after its rule or details changed."""
    root.recurrence_children.filter(
        due_at__gt=timezone.now(), completed_at__isnull=True, deleted_at__isnull=True,
    ).delete()
    return extend(root)


def extend_all(*, now=None):
    """Roll every active series' horizon forward. Called from the cron command."""
    total = 0
    roots = Reminder.objects.filter(
        recurrence_parent__isnull=True, deleted_at__isnull=True,
    ).exclude(recurrence_freq="")
    for root in roots:
        total += extend(root, now=now)
    return total
