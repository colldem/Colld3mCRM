"""Read-only iCalendar feed of a user's reminders (G4).

Hand-rolled — the format is tiny and pulling in a dependency is not worth it.
"""
from datetime import timedelta, timezone as _utc

from django.conf import settings
from django.utils import timezone

from .models import Reminder
from .reminder_queries import mine_q

WINDOW_BACK = 90
WINDOW_FORWARD = 400


def _esc(text):
    return (str(text or "")
            .replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def _stamp(value):
    return value.astimezone(_utc.utc).strftime("%Y%m%dT%H%M%SZ")


def _fold(line):
    """iCal lines must be <=75 octets; continuation lines start with a space."""
    out = []
    while len(line.encode("utf-8")) > 75:
        cut = 74
        while len(line[:cut].encode("utf-8")) > 74:
            cut -= 1
        out.append(line[:cut])
        line = " " + line[cut:]
    out.append(line)
    return out


def feed_for(user):
    now = timezone.now()
    reminders = (Reminder.objects
                 .filter(mine_q(user), deleted_at__isnull=True,
                         due_at__gte=now - timedelta(days=WINDOW_BACK),
                         due_at__lte=now + timedelta(days=WINDOW_FORWARD))
                 .filter(models_person_ok())
                 .select_related("person", "company"))
    host = settings.CRM_BASE_URL.rstrip("/")
    rows = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Colld3m CRM//G4//EN",
            "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "X-WR-CALNAME:CRM"]
    for reminder in reminders:
        rows += [
            "BEGIN:VEVENT",
            "UID:crm-reminder-%s@colld3m" % reminder.pk,
            "DTSTAMP:%s" % _stamp(now),
            "DTSTART:%s" % _stamp(reminder.due_at),
            "DTEND:%s" % _stamp(reminder.finish_at),
            "SUMMARY:%s" % _esc(reminder.text),
            "STATUS:%s" % ("COMPLETED" if reminder.completed_at else "CONFIRMED"),
        ]
        if reminder.record:
            rows.append("DESCRIPTION:%s" % _esc(reminder.record))
        if reminder.contact_address:
            rows.append("LOCATION:%s" % _esc(reminder.contact_address))
        if reminder.record_url:
            rows.append("URL:%s%s" % (host, reminder.record_url))
        rows.append("END:VEVENT")
    rows.append("END:VCALENDAR")
    folded = []
    for row in rows:
        folded.extend(_fold(row))
    return "\r\n".join(folded) + "\r\n"


def models_person_ok():
    from django.db.models import Q
    return Q(person__isnull=True) | Q(person__deleted_at__isnull=True)
