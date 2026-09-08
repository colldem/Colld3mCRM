"""Role, team and record-visibility helpers. `is_superuser` is always an admin."""
from django.utils.translation import gettext_lazy as _

from .models import RolePermissions, Team, UserProfile


# (key, human label) — the capabilities an admin can grant per role.
CAPABILITIES = [
    ("can_import", _("Importuoti duomenis")),
    ("can_export", _("Eksportuoti duomenis")),
    ("can_delete", _("Archyvuoti ir atkurti įrašus")),
    ("can_merge_duplicates", _("Sujungti dublikatus")),
    ("can_bulk_edit", _("Masiniai veiksmai sąrašuose")),
    ("can_reassign_owner", _("Keisti atsakingą naudotoją")),
    ("can_manage_custom_fields", _("Tvarkyti dinaminius laukus")),
    ("can_manage_taxonomy", _("Tvarkyti žymas ir kategorijas")),
    ("can_view_audit", _("Matyti žurnalą")),
]
CAPABILITY_KEYS = [key for key, _label in CAPABILITIES]

_CAPABILITY_DEFAULTS = {
    UserProfile.ROLE_MEMBER: {
        "can_import": True, "can_export": True, "can_delete": True,
        "can_merge_duplicates": True, "can_bulk_edit": True, "can_reassign_owner": True,
        "can_manage_custom_fields": False, "can_manage_taxonomy": False, "can_view_audit": False,
    },
    UserProfile.ROLE_RESTRICTED: {
        "can_import": False, "can_export": True, "can_delete": True,
        "can_merge_duplicates": False, "can_bulk_edit": False, "can_reassign_owner": False,
        "can_manage_custom_fields": False, "can_manage_taxonomy": False, "can_view_audit": False,
    },
}


def capability_matrix():
    """{role: {capability: bool}} for the non-admin roles, stored value over default."""
    stored = {row.role: row.permissions or {} for row in RolePermissions.objects.all()}
    matrix = {}
    for role in (UserProfile.ROLE_MEMBER, UserProfile.ROLE_RESTRICTED):
        defaults = _CAPABILITY_DEFAULTS[role]
        matrix[role] = {key: bool(stored.get(role, {}).get(key, defaults[key])) for key in CAPABILITY_KEYS}
    return matrix


def has_capability(user, capability):
    if not getattr(user, "is_authenticated", False):
        return False
    if is_admin(user):
        return True
    role = role_of(user)
    if role not in _CAPABILITY_DEFAULTS:
        return False
    row = RolePermissions.objects.filter(role=role).first()
    if row and capability in (row.permissions or {}):
        return bool(row.permissions[capability])
    return _CAPABILITY_DEFAULTS[role].get(capability, False)

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
    """Restrict a Reminder queryset to the records `user` may see.

    A reminder follows its contact, else its company; one attached to neither is
    a private calendar entry visible only to whoever created it.
    """
    from django.db.models import Q
    from .models import Reminder

    if queryset is None:
        queryset = Reminder.objects.all()
    if user is None:
        return queryset
    if _person_visibility_q(user) is None and _company_visibility_q(user) is None:
        return queryset
    return queryset.filter(
        Q(person__isnull=False, person__pk__in=visible_people(user, None).values_list("pk", flat=True))
        | Q(person__isnull=True, company__isnull=False,
            company__pk__in=visible_companies(user, None).values_list("pk", flat=True))
        | Q(person__isnull=True, company__isnull=True, created_by=user)
        | Q(assigned_to=user)
    )


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


def assignable_users_for(user):
    """Active users `user` may hand a task to: everyone if they see all records,
    otherwise themselves and their teammates."""
    from django.contrib.auth import get_user_model

    qs = get_user_model().objects.filter(is_active=True)
    if not sees_all_records(user):
        qs = qs.filter(pk__in=teammate_ids(user))
    return qs.order_by("first_name", "last_name", "username")


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
