"""What is in someone's list right now, and what keeps it there.

A row in `RecordAccess` puts a contact or a company into one user's list until
the end of the day. Three things extend that, so a month-long piece of work does
not vanish every midnight:

* an open reminder assigned to that user on that record — no expiry at all
  while it is open, and the ordinary way a long engagement is carried; whether
  a role gets this is a checkbox in Settings → Roles and permissions
  (`can_keep_with_reminder`);
* logging an activity on the record — pushes the lease to the end of that day;
* "take into work" — a deliberate 30 days, for what has no reminder.

Nothing here deletes anything. A lease ends; the row stays, because the log of
who opened whose record, and why, is the point.
"""
from datetime import datetime, time, timedelta

from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from .models import Company, Person, RecordAccess, Reminder
from .reminder_queries import open_q

# What "take into work" buys before it has to be renewed.
LONG_LEASE_DAYS = 30


def end_of_day(moment=None):
    """Local midnight after `moment` — when an ordinary lease runs out."""
    moment = moment or timezone.now()
    local = timezone.localtime(moment)
    tz = timezone.get_current_timezone()
    return timezone.make_aware(datetime.combine(local.date() + timedelta(days=1), time.min), tz)


def _record_q(record, prefix=""):
    field = "company" if isinstance(record, Company) else "person"
    return Q(**{f"{prefix}{field}": record})


def grant(user, record, purpose, source=RecordAccess.SOURCE_SEARCH, note="", granted_by=None,
          days=None):
    """Put `record` in `user`'s list, or extend what is already there.

    Re-opening a record the user already has does not stack up rows: the reason
    is refreshed and the lease pushed out, so the log reads as one engagement
    rather than as one line per page view.
    """
    existing = live_for(user).filter(_record_q(record)).first()
    expires = timezone.now() + timedelta(days=days) if days else end_of_day()
    if existing is not None:
        existing.purpose = purpose
        existing.note = note or existing.note
        existing.expires_at = max(existing.expires_at, expires)
        existing.save(update_fields=["purpose", "note", "expires_at"])
        return existing
    field = "company" if isinstance(record, Company) else "person"
    return RecordAccess.objects.create(user=user, purpose=purpose, source=source, note=note,
                                       granted_by=granted_by, expires_at=expires,
                                       **{field: record})


def take_into_work(user, record, purpose, note=""):
    """A deliberate long lease, for work that will not finish today."""
    return grant(user, record, purpose, note=note, days=LONG_LEASE_DAYS)


def touch(user, record):
    """Extend the lease because the user did something on the record.

    Called when an activity is logged: coming back to a record is itself the
    statement that the work is still going on.
    """
    access = live_for(user).filter(_record_q(record)).first()
    if access is None:
        return None
    access.expires_at = max(access.expires_at, end_of_day())
    access.save(update_fields=["expires_at"])
    return access


def assignable_users(actor):
    """The people `actor` may put a record in front of.

    An admin or a manager may hand work to anyone; a team lead only to the
    teams they lead, which is the whole of what leading one gives them here.
    Nobody else may assign at all, and the empty queryset says so.
    """
    from django.contrib.auth import get_user_model

    from .models import Team, UserProfile
    from .permissions import is_admin, role_of

    User = get_user_model()
    if not getattr(actor, "is_authenticated", False):
        return User.objects.none()
    everyone = User.objects.filter(is_active=True).order_by("first_name", "last_name", "username")
    if is_admin(actor) or role_of(actor) == UserProfile.ROLE_MANAGER:
        return everyone
    led = Team.objects.filter(leads=actor)
    if not led.exists():
        return User.objects.none()
    return everyone.filter(crm_teams__in=led).distinct()


def assign(actor, target, record, purpose, note=""):
    """Put `record` in `target`'s list on `actor`'s say-so."""
    return grant(target, record, purpose, source=RecordAccess.SOURCE_ASSIGNED, note=note,
                 granted_by=actor)


def end(access, now=None):
    """Close an access early. The row stays; only the lease ends."""
    access.ended_at = now or timezone.now()
    access.save(update_fields=["ended_at"])
    return access


def live_on(record, now=None):
    """Who currently has this record in their list, and why."""
    rows = RecordAccess.objects.filter(_record_q(record), ended_at__isnull=True)
    return (_still_live(rows, rows.values_list("user_id", flat=True), now)
            .select_related("user", "granted_by").order_by("-created_at"))


def live_for(users, now=None):
    """`RecordAccess` rows that still put a record in someone's list.

    A lease that has run out still counts while a reminder assigned to that
    same user is open on the same record — the work is evidently not over.
    """
    given = users if isinstance(users, (set, list, tuple, frozenset)) else [users]
    # Callers pass users or their ids; everything below works in ids.
    ids = [getattr(user, "pk", user) for user in given]
    rows = RecordAccess.objects.filter(user_id__in=ids, ended_at__isnull=True)
    return _still_live(rows, ids, now)


def _still_live(rows, candidate_ids, now=None):
    """Of `rows`, the ones whose lease has not run out.

    `candidate_ids` are the users those rows belong to: whether a reminder may
    hold a record past its lease is decided per role, one user at a time.
    """
    now = now or timezone.now()
    kept = _may_keep_with_reminder(candidate_ids)
    live = Q(expires_at__gt=now)
    if kept:
        live |= Q(user_id__in=kept) & _kept_by_reminder(now)
    return rows.filter(live)


def _may_keep_with_reminder(ids):
    """Of these users, the ones whose role lets a reminder hold a record.

    Settings → Roles decides it per role, so two people looking at the same
    record can honestly get different answers.
    """
    from django.contrib.auth import get_user_model

    from .permissions import has_capability

    users = get_user_model().objects.filter(pk__in=ids).select_related("crm_profile")
    return [user.pk for user in users if has_capability(user, "can_keep_with_reminder")]


def _kept_by_reminder(now):
    """Rows whose own user still has an open reminder on that same record.

    Correlated on both the user and the record: a colleague's reminder is their
    reason to hold the record, not this row's.
    """
    mine = Q(assigned_to_id=OuterRef("user_id")) | Q(assigned_to__isnull=True,
                                                     created_by_id=OuterRef("user_id"))
    base = Reminder.objects.filter(mine, open_q(now), deleted_at__isnull=True)
    return (Q(Exists(base.filter(person_id=OuterRef("person_id"))))
            | Q(Exists(base.filter(company_id=OuterRef("company_id")))))


def searches_on(record, limit=50):
    """Every time this record was opened with a reason, newest first.

    Read from the audit trail rather than from `RecordAccess`: a lease is one
    row per engagement — opening the same record again the same day only
    refreshes it — while the card has to show each opening as its own line.
    The audit row is also the one nobody can edit afterwards.
    """
    from .models import AuditLog

    kind = "company" if isinstance(record, Company) else "person"
    rows = (AuditLog.objects.filter(action=AuditLog.ACCESS, target_type=kind,
                                    target_id=str(record.pk))
            .order_by("-created_at")[:limit])
    # The keys are read back into today's language; the columns beside them
    # hold the label as it was written, which is what the journal shows and
    # what a row from before the keys existed still has.
    sources = dict(RecordAccess.SOURCE_CHOICES)
    purposes = dict(RecordAccess.PURPOSES)
    return [{"when": row.created_at, "who": row.actor_label,
             "purpose": purposes.get(row.detail.get("purpose")) or row.field,
             "note": row.new_value, "source": sources.get(row.detail.get("source"), "")}
            for row in rows]


def accessible_person_ids(users, now=None):
    return live_for(users, now).filter(person__isnull=False).values_list("person_id", flat=True)


def accessible_company_ids(users, now=None):
    return live_for(users, now).filter(company__isnull=False).values_list("company_id", flat=True)


def find(query):
    """The one record a purposeful search turns up, or None.

    A code — a personal code, or a company's registration code — matches
    exactly, and that is how the desk is meant to search. A name matches only
    when it picks out exactly one record, because a list of candidates is the
    browsing this build exists to avoid.
    """
    query = (query or "").strip()
    if len(query) < 3:
        return None
    people = Person.objects.filter(deleted_at__isnull=True)
    companies = Company.objects.filter(deleted_at__isnull=True)
    if query.isdigit():
        return (people.filter(personal_code=query).first()
                or companies.filter(company_code=query).first())
    for term in query.split():
        people = people.filter(Q(first_name__icontains=term) | Q(last_name__icontains=term))
        companies = companies.filter(name__icontains=term)
    matches = list(people[:2]) or list(companies[:2])
    return matches[0] if len(matches) == 1 else None
