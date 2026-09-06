from django.utils import timezone

from .reminder_queries import pending_reminders


def reminder_count(request):
    if not request.user.is_authenticated:
        return {"active_reminder_count": 0, "active_reminders_menu": []}
    now = timezone.now()
    pending = pending_reminders()
    reminders = pending.filter(due_at__lte=now)
    return {"active_reminder_count": reminders.filter(read_at__isnull=True).count(),
            "active_reminders_menu": reminders, "scheduled_reminders_menu": pending.filter(due_at__gt=now)}
