"""Role, team and record-visibility helpers. `is_superuser` is always an admin."""
from .models import Team, UserProfile

_VIS_ORDER = {UserProfile.VISIBILITY_ALL: 0, UserProfile.VISIBILITY_TEAM: 1, UserProfile.VISIBILITY_OWN: 2}


def role_of(user):
    if not getattr(user, "is_authenticated", False):
        return None
    if user.is_superuser:
        return UserProfile.ROLE_ADMIN
    profile = getattr(user, "crm_profile", None)
    if profile and profile.role:
        return profile.role
    return UserProfile.ROLE_ADMIN if user.is_staff else UserProfile.ROLE_MEMBER


def is_admin(user):
    return role_of(user) == UserProfile.ROLE_ADMIN


def record_visibility(user):
    """Effective record visibility for `user`: 'all', 'team' or 'own'.

    The strictest of the user's own setting and any team the user belongs to
    that is marked "team records only" wins. Admins always see everything.
    """
    if not getattr(user, "is_authenticated", False):
        return UserProfile.VISIBILITY_ALL
    if is_admin(user):
        return UserProfile.VISIBILITY_ALL
    profile = getattr(user, "crm_profile", None)
    candidates = [profile.record_visibility if profile and profile.record_visibility else UserProfile.VISIBILITY_ALL]
    # The "restricted" role is a preset floor of "own".
    if role_of(user) == UserProfile.ROLE_RESTRICTED:
        candidates.append(UserProfile.VISIBILITY_OWN)
    if Team.objects.filter(members=user, visibility=Team.VISIBILITY_TEAM).exists():
        candidates.append(UserProfile.VISIBILITY_TEAM)
    return max(candidates, key=lambda value: _VIS_ORDER[value])


def sees_all_records(user):
    return record_visibility(user) == UserProfile.VISIBILITY_ALL


def teammate_ids(user):
    """User ids sharing at least one team with `user`, plus `user` itself."""
    ids = set(
        Team.members.through.objects.filter(
            team_id__in=Team.objects.filter(members=user).values("id")
        ).values_list("user_id", flat=True)
    )
    ids.add(user.pk)
    return ids


def responsible_person_ids(user_or_ids):
    """Person ids where the given user (or any of the given user ids) is a responsible."""
    from .models import Person

    lookup = "user_id__in" if _is_iterable(user_or_ids) else "user_id"
    return Person.responsibles.through.objects.filter(**{lookup: user_or_ids}).values_list("person_id", flat=True)


def responsible_company_ids(user_or_ids):
    from .models import Company

    lookup = "user_id__in" if _is_iterable(user_or_ids) else "user_id"
    return Company.responsibles.through.objects.filter(**{lookup: user_or_ids}).values_list("company_id", flat=True)


def _is_iterable(value):
    return isinstance(value, (set, list, tuple, frozenset))


def _person_visibility_q(user):
    """A Q on Person for what `user` may see, or None when the user sees everything."""
    from django.db.models import Q

    vis = record_visibility(user)
    if vis == UserProfile.VISIBILITY_ALL:
        return None
    if vis == UserProfile.VISIBILITY_OWN:
        return Q(owner=user) | Q(pk__in=responsible_person_ids(user.pk)) | Q(owner__isnull=True)
    ids = teammate_ids(user)
    return Q(owner_id__in=ids) | Q(pk__in=responsible_person_ids(ids)) | Q(owner__isnull=True)


def _company_visibility_q(user):
    from django.db.models import Q

    vis = record_visibility(user)
    if vis == UserProfile.VISIBILITY_ALL:
        return None
    if vis == UserProfile.VISIBILITY_OWN:
        return Q(owner=user) | Q(pk__in=responsible_company_ids(user.pk)) | Q(owner__isnull=True)
    ids = teammate_ids(user)
    return Q(owner_id__in=ids) | Q(pk__in=responsible_company_ids(ids)) | Q(owner__isnull=True)


def visible_people(user, queryset=None):
    """Restrict a Person queryset to what `user` may see (see :func:`record_visibility`)."""
    from .models import Person

    if queryset is None:
        queryset = Person.objects.all()
    if user is None:
        return queryset
    clause = _person_visibility_q(user)
    return queryset if clause is None else queryset.filter(clause)


def visible_companies(user, queryset=None):
    from .models import Company

    if queryset is None:
        queryset = Company.objects.all()
    if user is None:
        return queryset
    clause = _company_visibility_q(user)
    return queryset if clause is None else queryset.filter(clause)


def visible_reminders(user, queryset=None):
    """Restrict a Reminder queryset to reminders on people `user` may see."""
    from django.db.models import Q
    from .models import Reminder

    if queryset is None:
        queryset = Reminder.objects.all()
    if user is None:
        return queryset
    clause = _person_visibility_q(user)
    if clause is None:
        return queryset
    visible_ids = visible_people(user, None).values_list("pk", flat=True)
    return queryset.filter(person__pk__in=visible_ids)


def visible_person_ids(user):
    return visible_people(user, None).values_list("pk", flat=True)


def visible_company_ids(user):
    return visible_companies(user, None).values_list("pk", flat=True)


def user_label(user):
    """Human-readable name for a CRM user: full name if set, else the username."""
    if not user:
        return ""
    return user.get_full_name().strip() or user.get_username()


def assignable_users():
    """Active users that a record can be assigned to, ordered by name."""
    from django.contrib.auth import get_user_model

    return list(get_user_model().objects.filter(is_active=True).order_by("first_name", "last_name", "username"))


def can_see_person(user, person):
    if sees_all_records(user):
        return True
    from .models import Person

    return visible_people(user, Person.objects.filter(pk=person.pk)).exists()


def can_see_company(user, company):
    if sees_all_records(user):
        return True
    from .models import Company

    return visible_companies(user, Company.objects.filter(pk=company.pk)).exists()


def active_admin_ids():
    from django.contrib.auth import get_user_model

    ids = set()
    for user in get_user_model().objects.filter(is_active=True).select_related("crm_profile"):
        if is_admin(user):
            ids.add(user.pk)
    return ids
