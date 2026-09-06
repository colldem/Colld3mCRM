from .models import Reminder


def pending_reminders():
    return Reminder.objects.filter(
        completed_at__isnull=True, deleted_at__isnull=True,
        person__deleted_at__isnull=True,
    ).select_related("person").order_by("due_at", "pk")
