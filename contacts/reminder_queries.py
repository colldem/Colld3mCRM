from django.db.models import Q

from .models import Reminder
from .permissions import visible_reminders


def pending_reminders(user=None):
    queryset = Reminder.objects.filter(
        completed_at__isnull=True, deleted_at__isnull=True,
    ).filter(
        Q(person__isnull=True) | Q(person__deleted_at__isnull=True)
    ).select_related("person", "company").order_by("due_at", "pk")
    if user is not None:
        queryset = visible_reminders(user, queryset)
    return queryset
