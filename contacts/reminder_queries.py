from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from .models import Reminder
from .permissions import visible_reminders


def mine_q(user):
    """Reminders `user` owns: assigned to them, or created by them and still unassigned."""
    return Q(assigned_to=user) | Q(assigned_to__isnull=True, created_by=user)


def open_q(now=None):
    """Not finished: neither ticked off nor a meeting whose slot has passed.

    A meeting closes itself once it is over; a call or a plain reminder waits to
    be marked done. `Reminder.is_done` is the same rule, one row at a time.
    """
    now = now or timezone.now()
    default_end = now - timedelta(minutes=Reminder.DEFAULT_MINUTES)
    return Q(completed_at__isnull=True) & (
        ~Q(kind=Reminder.KIND_MEETING)
        | Q(end_at__gte=now)
        | Q(end_at__isnull=True, due_at__gte=default_end)
    )


def autocomplete_past_meetings(now=None):
    """Write the auto-completion out, so reports and exports agree with the UI.

    `open_q` already hides these everywhere; this is the worker's catch-up pass.
    """
    now = now or timezone.now()
    default_end = now - timedelta(minutes=Reminder.DEFAULT_MINUTES)
    stale = Reminder.objects.filter(
        kind=Reminder.KIND_MEETING, completed_at__isnull=True, deleted_at__isnull=True,
    ).filter(Q(end_at__lt=now) | Q(end_at__isnull=True, due_at__lt=default_end))
    return stale.update(completed_at=now, updated_at=now)


def pending_reminders(user=None):
    queryset = Reminder.objects.filter(
        open_q(), deleted_at__isnull=True,
    ).filter(
        Q(person__isnull=True) | Q(person__deleted_at__isnull=True)
    ).select_related("person", "company").order_by("due_at", "pk")
    if user is not None:
        queryset = visible_reminders(user, queryset)
    return queryset
