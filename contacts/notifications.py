"""Email notifications (G7).

Three messages: an upcoming-event reminder, a daily morning digest, and a
"task assigned to you" note. Delivery is best-effort — a failure is logged to
the audit trail and never propagates. Real sending only happens when EMAIL_HOST
is configured; otherwise Django prints the message to the container log.
"""
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone, translation

from .audit import log as audit_log
from .models import AuditLog, SystemSettings, UserProfile


def _profile(user):
    return getattr(user, "crm_profile", None) or UserProfile.objects.filter(user=user).first()


def effective_lead(user, sys=None):
    sys = sys or SystemSettings.load()
    profile = _profile(user)
    if profile and profile.notify_lead is not None:
        return profile.notify_lead
    return sys.notify_default_lead


def effective_digest_time(user, sys=None):
    sys = sys or SystemSettings.load()
    profile = _profile(user)
    return (profile.digest_time if profile and profile.digest_time else sys.digest_default_time)


def _lang(user):
    profile = _profile(user)
    return profile.language if profile and profile.language else settings.LANGUAGE_CODE


def _url(path):
    return settings.CRM_BASE_URL.rstrip("/") + path


def _send(name, subject, user, context, *, audit_label):
    to = (user.email or "").strip()
    if not to:
        return False
    sys = SystemSettings.load()
    context = {**context, "base_url": settings.CRM_BASE_URL.rstrip("/"),
               "date_format": sys.date_format, "datetime_format": sys.datetime_format,
               "LANGUAGE_CODE": _lang(user)}
    with translation.override(_lang(user)):
        subject = str(subject)
        text_body = render_to_string("email/%s.txt" % name, context)
        html_body = render_to_string("email/%s.html" % name, context)
    message = EmailMultiAlternatives(subject, text_body, settings.DEFAULT_FROM_EMAIL, [to])
    message.attach_alternative(html_body, "text/html")
    try:
        message.send()
        return True
    except Exception as error:  # SMTP down, bad credentials, DNS…
        audit_log(AuditLog.SETTING, actor=user, target_type="notification",
                  target_label=audit_label, new="ERROR: %s" % error)
        return False


def send_task_assigned(reminder, assigned_by):
    with translation.override(_lang(reminder.assigned_to)):
        from django.utils.translation import gettext as _
        subject = _("Jums priskirta užduotis: %s") % reminder.text[:60]
    return _send("task_assigned", subject, reminder.assigned_to, {
        "reminder": reminder, "assigned_by": assigned_by,
        "link": _url(reminder.record_url or "/calendar/"),
    }, audit_label="task_assigned #%s" % reminder.pk)


def send_upcoming(reminder):
    user = reminder.assigned_to or reminder.created_by
    with translation.override(_lang(user)):
        from django.utils.translation import gettext as _
        subject = _("Artėja: %s") % reminder.text[:60]
    return _send("upcoming", subject, user, {
        "reminder": reminder, "link": _url(reminder.record_url or "/calendar/"),
    }, audit_label="upcoming #%s" % reminder.pk)


def send_digest(user, overdue, today):
    profile = _profile(user)
    with translation.override(_lang(user)):
        from django.utils.translation import gettext as _
        subject = _("CRM rytinė santrauka")
    return _send("digest", subject, user, {
        "overdue": overdue, "today": today,
        "unsubscribe": _url("/notifications/unsubscribe/%s/" % (profile.unsubscribe_token if profile else "")),
        "calendar_link": _url("/calendar/"),
    }, audit_label="digest %s" % timezone.localdate())
