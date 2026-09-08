"""Role helpers. `is_superuser` always counts as an administrator."""
from .models import UserProfile


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


def sees_all_records(user):
    return role_of(user) in (UserProfile.ROLE_ADMIN, UserProfile.ROLE_MEMBER)


def responsible_person_ids(user):
    """Person ids where `user` is listed among the additional responsibles."""
    from .models import Person

    return Person.responsibles.through.objects.filter(user_id=user.pk).values_list("person_id", flat=True)


def responsible_company_ids(user):
    from .models import Company

    return Company.responsibles.through.objects.filter(user_id=user.pk).values_list("company_id", flat=True)


def visible_people(user, queryset=None):
    """Restrict a Person queryset to what `user` may see.

    Admins and regular members see everything. Restricted members see only the
    records where they are the owner or an additional responsible, plus records
    with no owner yet.
    """
    from .models import Person

    if queryset is None:
        queryset = Person.objects.all()
    if user is None or sees_all_records(user):
        return queryset
    from django.db.models import Q

    return queryset.filter(Q(owner=user) | Q(pk__in=responsible_person_ids(user)) | Q(owner__isnull=True))


def visible_companies(user, queryset=None):
    """Restrict a Company queryset the same way as :func:`visible_people`."""
    from .models import Company

    if queryset is None:
        queryset = Company.objects.all()
    if user is None or sees_all_records(user):
        return queryset
    from django.db.models import Q

    return queryset.filter(Q(owner=user) | Q(pk__in=responsible_company_ids(user)) | Q(owner__isnull=True))


def visible_reminders(user, queryset=None):
    """Restrict a Reminder queryset to reminders on people `user` may see."""
    from .models import Reminder

    if queryset is None:
        queryset = Reminder.objects.all()
    if user is None or sees_all_records(user):
        return queryset
    from django.db.models import Q

    return queryset.filter(Q(person__owner=user) | Q(person__pk__in=responsible_person_ids(user)) | Q(person__owner__isnull=True))


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
    return (sees_all_records(user) or person.owner_id in (None, user.pk)
            or person.responsibles.filter(pk=user.pk).exists())


def can_see_company(user, company):
    return (sees_all_records(user) or company.owner_id in (None, user.pk)
            or company.responsibles.filter(pk=user.pk).exists())


def active_admin_ids():
    from django.contrib.auth import get_user_model

    ids = set()
    for user in get_user_model().objects.filter(is_active=True).select_related("crm_profile"):
        if is_admin(user):
            ids.add(user.pk)
    return ids
