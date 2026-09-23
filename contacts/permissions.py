"""Role, team and record-visibility helpers. `is_superuser` is always an admin."""
from django.utils.translation import gettext_lazy as _

from .models import RolePermissions, Team, UserProfile


# (key, human label) — the capabilities an admin can grant per role.
CAPABILITIES = [
    # First, because it is the one that changes what people see rather than
    # what they may do — and the only one whose effect needs explaining.
    ("can_keep_with_reminder", _("Palikti sąraše, kol yra aktyvus priminimas")),
    ("can_import", _("Importuoti duomenis")),
    ("can_export", _("Eksportuoti duomenis")),
    ("can_delete", _("Archyvuoti ir atkurti įrašus")),
    ("can_merge_duplicates", _("Sujungti dublikatus")),
    ("can_bulk_edit", _("Masiniai veiksmai sąrašuose")),
    ("can_reassign_owner", _("Keisti atsakingą naudotoją")),
    ("can_manage_custom_fields", _("Tvarkyti dinaminius laukus")),
    ("can_manage_taxonomy", _("Tvarkyti žymas ir kategorijas")),
    ("can_manage_automations", _("Tvarkyti automatikos taisykles")),
    ("can_view_audit", _("Matyti žurnalą")),
]
CAPABILITY_KEYS = [key for key, _label in CAPABILITIES]

# Plain-language notes for the settings table, where a capability's name is not
# enough on its own. Only the ones that really need it — a note beside every
# row would be noise.
CAPABILITY_HINTS = {
    "can_keep_with_reminder": _(
        "Paprastai kontaktas iš sąrašo dingsta dienos pabaigoje. Su šia varnele jis "
        "lieka tol, kol tam pačiam darbuotojui priskirtas priminimas nėra užbaigtas — "
        "kad ilgas darbas su klientu nedingtų kas naktį."
    ),
}

_CAPABILITY_DEFAULTS = {
    UserProfile.ROLE_MANAGER: {
        "can_keep_with_reminder": True, "can_import": True, "can_export": True,
        "can_delete": True, "can_merge_duplicates": True, "can_bulk_edit": True,
        "can_reassign_owner": True, "can_manage_custom_fields": False,
        "can_manage_taxonomy": False, "can_manage_automations": False,
        # A manager answers for what their people do, so the log is theirs to read.
        "can_view_audit": True,
    },
    UserProfile.ROLE_MEMBER: {
        "can_keep_with_reminder": True, "can_import": True, "can_export": True, "can_delete": True,
        "can_merge_duplicates": True, "can_bulk_edit": True, "can_reassign_owner": True,
        "can_manage_custom_fields": False, "can_manage_taxonomy": False,
        "can_manage_automations": False, "can_view_audit": False,
    },
    UserProfile.ROLE_RESTRICTED: {
        "can_keep_with_reminder": True, "can_import": False, "can_export": True, "can_delete": True,
        "can_merge_duplicates": False, "can_bulk_edit": False, "can_reassign_owner": False,
        "can_manage_custom_fields": False, "can_manage_taxonomy": False,
        "can_manage_automations": False, "can_view_audit": False,
    },
    UserProfile.ROLE_READONLY: {key: False for key in CAPABILITY_KEYS},
}
# A reader changes nothing; only these read-side capabilities can be granted.
READONLY_CAPABILITIES = {"can_export", "can_view_audit", "can_keep_with_reminder"}
EDITABLE_ROLES = (UserProfile.ROLE_MANAGER, UserProfile.ROLE_MEMBER,
                  UserProfile.ROLE_RESTRICTED, UserProfile.ROLE_READONLY)


def capability_matrix():
    """{role: {capability: bool}} for the non-admin roles, stored value over default."""
    stored = {row.role: row.permissions or {} for row in RolePermissions.objects.all()}
    matrix = {}
    for role in EDITABLE_ROLES:
        defaults = _CAPABILITY_DEFAULTS[role]
        matrix[role] = {key: bool(stored.get(role, {}).get(key, defaults[key])) for key in CAPABILITY_KEYS}
        if role == UserProfile.ROLE_READONLY:
            matrix[role] = {key: value and key in READONLY_CAPABILITIES for key, value in matrix[role].items()}
    return matrix


def has_capability(user, capability):
    if not getattr(user, "is_authenticated", False):
        return False
    if is_admin(user):
        return True
    role = role_of(user)
    if role not in _CAPABILITY_DEFAULTS:
        return False
    if role == UserProfile.ROLE_READONLY and capability not in READONLY_CAPABILITIES:
        return False
    # Pages check a dozen capabilities (menu, context, view); read the role's row
    # once per user object, i.e. once per request.
    rows = user.__dict__.setdefault("_crm_role_permissions", {})
    if role not in rows:
        rows[role] = RolePermissions.objects.filter(role=role).first()
    row = rows[role]
    if row and capability in (row.permissions or {}):
        return bool(row.permissions[capability])
    return _CAPABILITY_DEFAULTS[role].get(capability, False)

# --- registry blocks -------------------------------------------------------
#
# The middle column of a card carries registry data, and not every desk needs
# every part of it: a role can be shown the vehicles without being shown the
# mandates. Blocks are visible unless an admin says otherwise, so installing an
# integration does not silently hide what people were already using.

def block_matrix():
    """{role: {block key: bool}} for the non-admin roles, stored value over the
    default (visible)."""
    from .record_blocks import block_keys

    stored = {row.role: row.blocks or {} for row in RolePermissions.objects.all()}
    return {role: {key: bool(stored.get(role, {}).get(key, True)) for key in block_keys()}
            for role in EDITABLE_ROLES}


def can_see_block(user, key):
    if not getattr(user, "is_authenticated", False):
        return False
    if is_admin(user):
        return True
    role = role_of(user)
    if role not in _CAPABILITY_DEFAULTS:
        return False
    # A card renders a dozen blocks; read the role's row once per user object.
    rows = user.__dict__.setdefault("_crm_role_permissions", {})
    if role not in rows:
        rows[role] = RolePermissions.objects.filter(role=role).first()
    row = rows[role]
    return bool((row.blocks or {}).get(key, True)) if row else True


# Loosest to strictest; `record_visibility` takes the strictest that applies.
_VIS_ORDER = {UserProfile.VISIBILITY_ALL: 0, UserProfile.VISIBILITY_TEAM: 1,
              UserProfile.VISIBILITY_OWN: 2, UserProfile.VISIBILITY_TEAM_ACTIVE: 3,
              UserProfile.VISIBILITY_OWN_ACTIVE: 4}
ACTIVE_VISIBILITIES = (UserProfile.VISIBILITY_TEAM_ACTIVE, UserProfile.VISIBILITY_OWN_ACTIVE)


def role_of(user):
    if not getattr(user, "is_authenticated", False):
        return None
    if user.is_superuser:
        return UserProfile.ROLE_ADMIN
    profile = getattr(user, "crm_profile", None)
    if profile and profile.role:
        return profile.role
    return UserProfile.ROLE_ADMIN if user.is_staff else UserProfile.ROLE_MEMBER


def is_read_only(user):
    return role_of(user) == UserProfile.ROLE_READONLY


def is_admin(user):
    return role_of(user) == UserProfile.ROLE_ADMIN


def record_visibility(user):
    """Effective record visibility for `user` — one of `VISIBILITY_CHOICES`.

    The strictest of the user's own setting and any team the user belongs to
    that is marked "team records only" wins. Admins and managers always see
    everything. The two "active" modes show only what the user is working on
    right now; see :mod:`contacts.record_access`.
    """
    if not getattr(user, "is_authenticated", False):
        return UserProfile.VISIBILITY_ALL
    if is_admin(user) or role_of(user) == UserProfile.ROLE_MANAGER:
        return UserProfile.VISIBILITY_ALL
    profile = getattr(user, "crm_profile", None)
    candidates = [profile.record_visibility if profile and profile.record_visibility else UserProfile.VISIBILITY_ALL]
    # The "restricted" role is a preset floor of "own".
    if role_of(user) == UserProfile.ROLE_RESTRICTED:
        candidates.append(UserProfile.VISIBILITY_OWN)
    if Team.objects.filter(members=user, visibility=Team.VISIBILITY_TEAM).exists():
        candidates.append(UserProfile.VISIBILITY_TEAM)
    return max(candidates, key=lambda value: _VIS_ORDER[value])


def active_viewer_ids(user):
    """Whose live access counts as this user's own list.

    A lead sees what the teams they lead are working on, so that they can
    supervise and stand in. Leading no team, "team's active" is the same as
    one's own — a profile setting alone must not open a team up.
    """
    ids = {user.pk}
    if record_visibility(user) == UserProfile.VISIBILITY_TEAM_ACTIVE:
        ids |= set(Team.members.through.objects.filter(
            team_id__in=Team.objects.filter(leads=user).values("id")
        ).values_list("user_id", flat=True))
    return ids


def sees_all_records(user):
    return record_visibility(user) == UserProfile.VISIBILITY_ALL


def audit_scope(user):
    """Whose journal entries `user` may read.

    Three answers, and the middle one is the point: ``None`` for someone with
    no business here at all, ``"all"`` for the roles the capability is granted
    to, and a set of user ids for a team lead. A lead answers for the people in
    their teams, which means answering for how those people open records — and
    until now the only way to check was to walk the cards one at a time.

    It does not widen what they may see about the records themselves: a journal
    row names the record its actor already had open.
    """
    from .record_access import assignable_users

    if not getattr(user, "is_authenticated", False):
        return None
    if has_capability(user, "can_view_audit"):
        return "all"
    led = assignable_users(user)
    if not led.exists():
        return None
    # Their own entries too: a lead reviewing the desk is part of the desk.
    return set(led.values_list("pk", flat=True)) | {user.pk}


def teammate_ids(user):
    """User ids sharing at least one team with `user`, plus `user` itself."""
    ids = set(
        Team.members.through.objects.filter(
            team_id__in=Team.objects.filter(members=user).values("id")
        ).values_list("user_id", flat=True)
    )
    ids.add(user.pk)
    return ids


def in_any_team(user):
    """True when `user` belongs to at least one team."""
    if not getattr(user, "is_authenticated", False):
        return False
    return Team.objects.filter(members=user).exists()


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
    if vis in ACTIVE_VISIBILITIES:
        # Nothing is visible by default here, not even an unowned record: it is
        # in the list because someone opened it for a reason, or not at all.
        from .record_access import accessible_person_ids

        return Q(pk__in=accessible_person_ids(active_viewer_ids(user)))
    if vis == UserProfile.VISIBILITY_OWN:
        return Q(owner=user) | Q(pk__in=responsible_person_ids(user.pk)) | Q(owner__isnull=True)
    ids = teammate_ids(user)
    return Q(owner_id__in=ids) | Q(pk__in=responsible_person_ids(ids)) | Q(owner__isnull=True)


def _company_visibility_q(user):
    from django.db.models import Q

    vis = record_visibility(user)
    if vis == UserProfile.VISIBILITY_ALL:
        return None
    if vis in ACTIVE_VISIBILITIES:
        # Nothing is visible by default here, not even an unowned record: it is
        # in the list because someone opened it for a reason, or not at all.
        from .record_access import accessible_company_ids

        return Q(pk__in=accessible_company_ids(active_viewer_ids(user)))
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
