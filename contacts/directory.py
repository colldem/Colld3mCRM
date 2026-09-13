"""Directory (AD / Entra ID) group based access.

The organisation manages people in its directory: a user is put into a group
such as ``CRM-Admins`` and gets the rights that come with it. With group sync
turned on (Settings -> Prisijungimas), every sign-in through the identity
provider re-reads the groups from the ID token and applies them:

* the role is the strongest role among the user's mapped groups;
* membership of every team that some mapping points at follows the groups
  (teams no mapping refers to stay under manual control);
* a user in no group that grants a role is refused;
* the local password is disabled, so a person removed from the directory
  cannot fall back to a CRM password.

``evaluate`` is pure and is also what the "test claims" tool in Settings shows,
so a mapping can be checked with a pasted token before real sign-ins happen.
"""
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from .models import AuditLog, DirectoryGroupMapping, Team, UserProfile

# Strongest first. A role not listed here (added later) ranks last.
ROLE_STRENGTH = [UserProfile.ROLE_ADMIN, UserProfile.ROLE_MEMBER, UserProfile.ROLE_RESTRICTED]


class DirectoryAccessDenied(Exception):
    """Sign-in refused; the message is safe to show to the person signing in."""


@dataclass
class Evaluation:
    groups: list
    matched: list = field(default_factory=list)
    role: str = ""
    teams: list = field(default_factory=list)
    denied: str = ""


def groups_from_claims(claims, claim_name):
    """The group identifiers in ``claims`` as a list of strings.

    Entra sends a JSON list of object ids (or names, for synced groups when so
    configured); AD FS may send a single string for one group.
    """
    value = claims.get(claim_name)
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def has_group_overage(claims, claim_name):
    """Entra leaves the groups out of the token when a user is in too many
    (over 200) and points to Microsoft Graph instead. Treating that as "no
    groups" would silently strip rights, so it is refused with a clear reason."""
    names = claims.get("_claim_names")
    return bool(claims.get("hasgroups")) or (isinstance(names, dict) and claim_name in names)


def evaluate(claims, config, mappings=None):
    claim_name = config.groups_claim or "groups"
    groups = groups_from_claims(claims, claim_name)
    result = Evaluation(groups=groups)
    if has_group_overage(claims, claim_name):
        result.denied = _("Naudotojas priklauso per daug grupių, todėl jos neįtrauktos į prisijungimo žetoną. "
                          "Entra programoje nustatykite, kad būtų siunčiamos tik programai priskirtos grupės.")
        return result
    wanted = {group.lower() for group in groups}
    mappings = list(mappings if mappings is not None else DirectoryGroupMapping.objects.select_related("team"))
    result.matched = [mapping for mapping in mappings if mapping.group.lower() in wanted]
    roles = [mapping.role for mapping in result.matched if mapping.role]
    if roles:
        result.role = min(roles, key=lambda role: ROLE_STRENGTH.index(role) if role in ROLE_STRENGTH else len(ROLE_STRENGTH))
    result.teams = sorted({mapping.team for mapping in result.matched if mapping.team}, key=lambda team: team.name)
    if not result.role:
        result.denied = _("Naudotojas nepriklauso nė vienai CRM prieigą suteikiančiai katalogo grupei.")
    return result


def subject_of(claims, config):
    """A stable, non-reassignable identity: Entra object id, else ``sub``."""
    if config.is_entra and claims.get("oid"):
        return "%s:%s" % (claims.get("tid", ""), claims["oid"])
    return str(claims.get("sub") or "")


def check_subject(user, claims, config):
    """Refuse when a CRM user already linked to one directory identity is
    presented with another one carrying the same email (a reassigned address)."""
    subject = subject_of(claims, config)
    profile = UserProfile.objects.filter(user=user).first()
    if profile and profile.directory_subject and subject and profile.directory_subject != subject:
        raise DirectoryAccessDenied(_("Šis el. pašto adresas susietas su kita katalogo paskyra. Kreipkitės į administratorių."))
    return subject


@transaction.atomic
def apply(user, claims, config, request=None):
    """Apply the directory groups in ``claims`` to ``user``; raise when refused."""
    from .audit import log as audit_log
    from .permissions import role_of

    if user.is_superuser:
        raise DirectoryAccessDenied(_("Vietinė pagrindinio administratoriaus paskyra per katalogą neprisijungia. "
                                      "Naudokite vietinį prisijungimą."))
    result = evaluate(claims, config)
    if result.denied:
        audit_log(AuditLog.LOGIN_FAILED, request=request, actor=user, target=user, target_type="user",
                  detail={"reason": "directory", "groups": result.groups[:50]})
        raise DirectoryAccessDenied(result.denied)
    subject = check_subject(user, claims, config)
    labels = dict(UserProfile.ROLE_CHOICES)
    old_role = role_of(user)
    profile, _created = UserProfile.objects.get_or_create(user=user)
    profile.role = result.role
    profile.directory_managed = True
    profile.directory_subject = subject or profile.directory_subject
    profile.directory_groups = result.groups[:200]
    profile.directory_synced_at = timezone.now()
    profile.save(update_fields=["role", "directory_managed", "directory_subject", "directory_groups",
                                "directory_synced_at", "updated_at"])
    user.crm_profile = profile  # the caller keeps using this user object
    user_fields = []
    if user.is_staff != (result.role == UserProfile.ROLE_ADMIN):
        user.is_staff = result.role == UserProfile.ROLE_ADMIN
        user_fields.append("is_staff")
    if user.has_usable_password():
        user.set_unusable_password()
        user_fields.append("password")
    if user_fields:
        user.save(update_fields=user_fields)
    if old_role != result.role:
        audit_log(AuditLog.UPDATE, request=request, actor=user, target=user, target_type="user",
                  field=_("Rolė"), old=labels.get(old_role, old_role), new=labels.get(result.role, result.role),
                  detail={"source": "directory"})

    managed = set(Team.objects.filter(directory_groups__isnull=False).distinct())
    wanted = set(result.teams)
    current = set(user.crm_teams.all())
    for team in (current & managed) - wanted:
        team.members.remove(user)
        audit_log(AuditLog.UPDATE, request=request, actor=user, target=user, target_type="user",
                  field=_("Komanda"), old=team.name, new="", detail={"source": "directory"})
    for team in wanted - current:
        team.members.add(user)
        audit_log(AuditLog.UPDATE, request=request, actor=user, target=user, target_type="user",
                  field=_("Komanda"), old="", new=team.name, detail={"source": "directory"})
    return result
