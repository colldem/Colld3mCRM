from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as tr
from django.db.models.signals import m2m_changed, post_save
from django.dispatch import receiver

from .audit import log as audit_log
from .models import Activity, AuditLog, Company, Person, Reminder


@receiver(m2m_changed, sender=Person.tags.through)
@receiver(m2m_changed, sender=Person.categories.through)
def enforce_three_item_limit(sender, instance, action, pk_set, **kwargs):
    if action != "pre_add":
        return
    relation = instance.tags if sender is Person.tags.through else instance.categories
    existing = relation.count()
    incoming = len(pk_set or set())
    if existing + incoming > 3:
        raise ValidationError(tr("Galima pasirinkti ne daugiau kaip 3 reikšmes."))


@receiver(user_logged_in)
def _audit_login(sender, request, user, **kwargs):
    audit_log(AuditLog.LOGIN, request=request, actor=user, target_type="auth", target_label=user.get_username())


@receiver(user_logged_out)
def _audit_logout(sender, request, user, **kwargs):
    if user is not None:
        audit_log(AuditLog.LOGOUT, request=request, actor=user, target_type="auth", target_label=user.get_username())


@receiver(user_login_failed)
def _audit_login_failed(sender, credentials, request=None, **kwargs):
    username = (credentials or {}).get("username", "")
    audit_log(AuditLog.LOGIN_FAILED, request=request, actor=None, target_type="auth", target_label=username)


# --- outbound webhooks (H4) -----------------------------------------------
# `emit` is a cheap no-op when no webhook subscribes, so firing it on every save
# is fine. Bulk `.update()` paths (bulk archive, reminder complete) do not raise
# these signals — see contacts/webhooks.py docstring.

@receiver(post_save, sender=Person)
@receiver(post_save, sender=Company)
def _webhook_record(sender, instance, created, update_fields=None, **kwargs):
    from .webhooks import emit

    kind = "contact" if sender is Person else "company"
    if created:
        emit("%s.created" % kind, instance)
    elif update_fields and "deleted_at" in update_fields and instance.deleted_at:
        emit("%s.archived" % kind, instance)
    elif not instance.deleted_at:
        emit("%s.updated" % kind, instance)


@receiver(post_save, sender=Activity)
def _webhook_activity(sender, instance, created, **kwargs):
    if created:
        from .webhooks import emit

        emit("activity.created", instance)


@receiver(post_save, sender=Reminder)
def _webhook_reminder(sender, instance, created, update_fields=None, **kwargs):
    from .webhooks import emit

    if created:
        emit("reminder.created", instance)
    elif update_fields and "completed_at" in update_fields and instance.completed_at:
        emit("reminder.completed", instance)
