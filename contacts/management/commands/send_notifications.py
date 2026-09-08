"""Send due email notifications (G7).

Idempotent — safe to run every few minutes from a loop container. Does nothing
until an admin turns notifications on in Settings and EMAIL_HOST is configured.
"""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db.models import F
from django.utils import timezone

from ...models import Reminder, SystemSettings, UserProfile
from ...notifications import effective_lead, send_digest, send_task_assigned, send_upcoming
from ...reminder_queries import mine_q, pending_reminders


class Command(BaseCommand):
    help = "Send due CRM email notifications. Run every ~5 minutes."

    def handle(self, *args, **options):
        from ...recurrence import extend_all
        extend_all()  # keep recurring reminders materialised regardless of email settings
        sys = SystemSettings.load()
        if not sys.notifications_enabled:
            self.stdout.write("notifications disabled")
            return
        now = timezone.now()
        total = self._assignments() + self._upcoming(sys, now) + self._digests(sys, now)
        self.stdout.write("sent %d" % total)

    def _assignments(self):
        pending = (Reminder.objects.filter(completed_at__isnull=True, deleted_at__isnull=True,
                                           assigned_to__isnull=False)
                   .exclude(assigned_to=F("created_by"))
                   .exclude(assigned_to=F("assigned_notified_to"))
                   .select_related("assigned_to", "created_by", "person", "company"))
        count = 0
        for reminder in pending:
            if send_task_assigned(reminder, reminder.created_by):
                Reminder.objects.filter(pk=reminder.pk).update(assigned_notified_to=reminder.assigned_to)
                count += 1
        return count

    def _upcoming(self, sys, now):
        pending = (Reminder.objects.filter(completed_at__isnull=True, deleted_at__isnull=True,
                                           upcoming_notified_at__isnull=True, due_at__gt=now)
                   .select_related("assigned_to", "created_by", "person", "company"))
        count = 0
        for reminder in pending:
            user = reminder.assigned_to or reminder.created_by
            lead = effective_lead(user, sys)
            if lead and reminder.due_at - now <= timedelta(minutes=lead):
                if send_upcoming(reminder):
                    Reminder.objects.filter(pk=reminder.pk).update(upcoming_notified_at=now)
                    count += 1
        return count

    def _digests(self, sys, now):
        count = 0
        users = get_user_model().objects.filter(is_active=True).exclude(email="").select_related("crm_profile")
        for user in users:
            profile = getattr(user, "crm_profile", None)
            if not profile or not profile.digest_enabled:
                continue
            try:
                tz = ZoneInfo(profile.timezone or "Europe/Vilnius")
            except Exception:
                tz = ZoneInfo("Europe/Vilnius")
            local = now.astimezone(tz)
            due_time = profile.digest_time or sys.digest_default_time
            if local.time() < due_time or profile.digest_sent_on == local.date():
                continue
            overdue, today = self._digest_content(user, now, tz)
            UserProfile.objects.filter(pk=profile.pk).update(digest_sent_on=local.date())
            if (overdue or today) and send_digest(user, overdue, today):
                count += 1
        return count

    def _digest_content(self, user, now, tz):
        local_midnight = datetime.combine(now.astimezone(tz).date(), time.min, tzinfo=tz)
        mine = pending_reminders(user).filter(mine_q(user))
        overdue = list(mine.filter(due_at__lte=now))
        today = list(mine.filter(due_at__gt=now, due_at__lt=local_midnight + timedelta(days=1)))
        return overdue, today
