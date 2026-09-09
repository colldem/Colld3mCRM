"""Automation rules (H2).

Admin-configured "when X, do Y" rules evaluated by the worker every few minutes.
Not a visual builder — a fixed catalogue of triggers and actions, each rule a row
in :class:`AutomationRule`. :class:`AutomationLog` records every action and doubles
as the idempotency guard: a rule does not act again on the same target within its
``threshold`` days (so notify rules re-nag once per period while the condition
holds, and self-clearing conditions — owner assigned, mail resolved — never
re-fire).
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Max, Q
from django.utils import timezone
from django.utils.translation import gettext as _, gettext_lazy as tr

from .audit import log as audit_log
from .models import (
    AuditLog, AutomationLog, AutomationRule, Company, Person, Reminder, SystemSettings,
)

_PER_RULE_CAP = 200
_LOG_RETENTION_DAYS = 90


def _actor(rule):
    User = get_user_model()
    return (rule.created_by
            or User.objects.filter(is_active=True, is_superuser=True).order_by("pk").first()
            or User.objects.filter(is_active=True).order_by("pk").first())


def _target_type(target):
    return type(target).__name__.lower()


# --- triggers: (rule, now) -> iterable of target objects currently matching ---

def _t_no_owner(rule, now):
    cutoff = now - timedelta(days=rule.threshold or 1)
    return (Person.objects.filter(deleted_at__isnull=True, owner__isnull=True,
                                  responsibles__isnull=True, created_at__lt=cutoff)
            .distinct())


def _t_silent(rule, now):
    cutoff = now - timedelta(days=rule.threshold or 30)
    return (Person.objects.filter(deleted_at__isnull=True, owner__isnull=False)
            .annotate(last_act=Max("activities__created_at", filter=Q(activities__deleted_at__isnull=True)))
            .filter(last_act__lt=cutoff))


def _t_never(rule, now):
    cutoff = now - timedelta(days=rule.threshold or 14)
    return (Person.objects.filter(deleted_at__isnull=True, created_at__lt=cutoff)
            .annotate(n_act=Count("activities", filter=Q(activities__deleted_at__isnull=True)))
            .filter(n_act=0))


def _t_overdue(rule, now):
    cutoff = now - timedelta(days=rule.threshold or 3)
    return (Reminder.objects.filter(completed_at__isnull=True, deleted_at__isnull=True, due_at__lt=cutoff)
            .select_related("assigned_to", "person", "company"))


_TRIGGERS = {
    AutomationRule.NO_OWNER: _t_no_owner,
    AutomationRule.SILENT: _t_silent,
    AutomationRule.NEVER: _t_never,
    AutomationRule.OVERDUE: _t_overdue,
}


# --- actions: (rule, target, now) -> None (raise to record an error) ---

def _a_notify(rule, target, now):
    if not rule.action_user or not (rule.action_user.email or "").strip():
        raise ValueError("notify_user needs a user with an email")
    from .notifications import send_rule_notice

    if not send_rule_notice(rule.action_user, rule, target):
        raise ValueError("email not sent")


def _a_assign_owner(rule, target, now):
    if not isinstance(target, Person) or not rule.action_user:
        raise ValueError("assign_owner needs a contact and a user")
    if target.owner_id != rule.action_user_id:
        target.owner = rule.action_user
        target.save(update_fields=["owner", "updated_at"])
        audit_log(AuditLog.UPDATE, target=target, field=str(tr("Atsakingas")),
                  new=rule.action_user.get_full_name() or rule.action_user.username,
                  detail={"automation": rule.name})


def _a_create_task(rule, target, now):
    person = target if isinstance(target, Person) else getattr(target, "person", None)
    company = target if isinstance(target, Company) else getattr(target, "company", None)
    text = (rule.action_text or _("Automatinė užduotis")).replace("{vardas}", str(person or target))[:500]
    Reminder.objects.create(
        person=person, company=company, text=text,
        due_at=now + timedelta(days=rule.action_due_days or 3),
        created_by=_actor(rule),
        assigned_to=rule.action_user or getattr(target, "owner", None),
    )


def _a_add_tag(rule, target, now):
    if not isinstance(target, Person) or not rule.action_tag:
        raise ValueError("add_tag needs a contact and a tag")
    if not target.tags.filter(pk=rule.action_tag_id).exists():
        if target.tags.count() >= 3:
            raise ValueError("contact already has 3 tags")
        target.tags.add(rule.action_tag)
        audit_log(AuditLog.UPDATE, target=target, field=str(tr("Žyma")),
                  new=rule.action_tag.name, detail={"automation": rule.name})


_ACTIONS = {
    AutomationRule.NOTIFY: _a_notify,
    AutomationRule.ASSIGN: _a_assign_owner,
    AutomationRule.CREATE_TASK: _a_create_task,
    AutomationRule.ADD_TAG: _a_add_tag,
}


def _recently_acted(rule, target, now):
    guard = timedelta(days=rule.threshold or 3650)
    return AutomationLog.objects.filter(
        rule=rule, target_type=_target_type(target), target_id=str(target.pk),
        created_at__gte=now - guard,
    ).exists()


def matching_count(rule, now=None):
    """How many records a rule's trigger currently matches (for the UI)."""
    handler = _TRIGGERS.get(rule.trigger)
    return handler(rule, now or timezone.now()).count() if handler else 0


def run_all(now=None):
    """Evaluate every active rule. Returns the number of actions taken."""
    now = now or timezone.now()
    AutomationLog.objects.filter(created_at__lt=now - timedelta(days=_LOG_RETENTION_DAYS)).delete()
    if not SystemSettings.load().automations_enabled:
        return 0
    total = 0
    for rule in AutomationRule.objects.filter(active=True).select_related("action_user", "action_tag", "created_by"):
        handler = _TRIGGERS.get(rule.trigger)
        action = _ACTIONS.get(rule.action)
        if not handler or not action:
            continue
        acted = 0
        for target in handler(rule, now):
            if acted >= _PER_RULE_CAP:
                break
            if _recently_acted(rule, target, now):
                continue
            try:
                action(rule, target, now)
                _log(rule, target, "ok")
            except Exception as error:  # a bad rule must not break the loop
                _log(rule, target, "error", error=str(error)[:300])
            acted += 1
        AutomationRule.objects.filter(pk=rule.pk).update(last_run_at=now)
        total += acted
    return total


def _log(rule, target, status, **detail):
    AutomationLog.objects.create(
        rule=rule, target_type=_target_type(target), target_id=str(target.pk),
        target_label=str(target)[:255], status=status, detail=detail,
    )
