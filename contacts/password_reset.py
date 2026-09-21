"""Self-service password reset: "I forgot mine", by e-mail.

Three rules shape it:

* **No account enumeration.** Every request answers the same way, whether or not
  the address belongs to anybody. A CRM's user list is itself information.
* **The directory wins.** When group sync is on, a directory-managed account has
  no local password to reset — letting one be set would readmit somebody the
  organisation has removed.
* **A link is a key.** It is single use (Django's token stops matching once the
  password changes), short-lived (``PASSWORD_RESET_TIMEOUT``), and every step is
  written to the audit log.

The mail goes out through the SMTP configured in Settings, like every other
message the CRM sends — not through Django's global backend.
"""
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.tokens import default_token_generator
from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.utils.translation import gettext as tr

from .audit import log as audit_log
from .models import AuditLog, SystemSettings, UserProfile

# One person, however many times they press the button, gets this many mails an
# hour. Enough for a mistyped address; not enough to use the CRM as a mailer.
MAX_REQUESTS_PER_HOUR = 5
AUDIT_FIELD = "Slaptažodžio atkūrimas"


def _local_accounts(identifier):
    """Users an identifier may mean, filtered down to those a local password
    would actually let in."""
    identifier = (identifier or "").strip()
    if not identifier:
        return []
    User = get_user_model()
    found = list(User.objects.filter(username__iexact=identifier, is_active=True)
                 | User.objects.filter(email__iexact=identifier, is_active=True))
    return [user for user in found if user.email and not _directory_managed(user)]


def _directory_managed(user):
    from .integrations import oidc_config

    if not oidc_config().sync_groups:
        return False
    return UserProfile.objects.filter(user=user, directory_managed=True).exists()


def _too_many_requests(user):
    since = timezone.now() - timezone.timedelta(hours=1)
    return AuditLog.objects.filter(action=AuditLog.SETTING, target_type="user", target_id=str(user.pk),
                                   field=AUDIT_FIELD, new_value="sent", created_at__gte=since
                                   ).count() >= MAX_REQUESTS_PER_HOUR


def _send_link(request, user):
    from .integrations import email_config, site_base_url
    from .notifications import _connection, _lang

    from django.core.mail import EmailMultiAlternatives
    from django.template.loader import render_to_string
    from django.utils import translation

    system = SystemSettings.load()
    path = "/slaptazodis/%s/%s/" % (urlsafe_base64_encode(force_bytes(user.pk)),
                                    default_token_generator.make_token(user))
    context = {"user": user, "link": (site_base_url(system) or "") + path,
               "base_url": site_base_url(system), "LANGUAGE_CODE": _lang(user)}
    config = email_config(system)
    with translation.override(_lang(user)):
        subject = tr("CRM slaptažodžio atkūrimas")
        text_body = render_to_string("email/password_reset.txt", context)
        html_body = render_to_string("email/password_reset.html", context)
    message = EmailMultiAlternatives(subject, text_body, config.from_email, [user.email],
                                     connection=_connection(config))
    message.attach_alternative(html_body, "text/html")
    try:
        message.send()
    except Exception as error:  # SMTP down, bad credentials, DNS…
        audit_log(AuditLog.SETTING, request=request, target=user, target_type="user",
                  field=AUDIT_FIELD, new="ERROR: %s" % error)
        return
    audit_log(AuditLog.SETTING, request=request, target=user, target_type="user",
              field=AUDIT_FIELD, new="sent")


def password_reset_request(request):
    """Ask for a link. The answer never says whether the account exists."""
    from .integrations import oidc_config

    config = oidc_config()
    if request.method == "POST" and not config.enforced:
        for user in _local_accounts(request.POST.get("identifier")):
            if _too_many_requests(user):
                audit_log(AuditLog.SETTING, request=request, target=user, target_type="user",
                          field=AUDIT_FIELD, new="throttled")
                continue
            _send_link(request, user)
        messages.success(request, tr("Jei tokia paskyra yra, išsiuntėme nuorodą slaptažodžiui pasikeisti. "
                                     "Patikrinkite el. paštą."))
        return redirect("login")
    return render(request, "registration/password_reset_request.html", {
        "sso_only": config.enforced,
        "oidc_enabled": config.usable,
        "oidc_is_entra": config.is_entra,
    })


def password_reset_set(request, uidb64, token):
    """Follow the link and choose a new password."""
    from .integrations import oidc_config

    User = get_user_model()
    try:
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(uidb64)), is_active=True)
    except (User.DoesNotExist, ValueError, TypeError, OverflowError):
        user = None
    if user is not None and (_directory_managed(user) or oidc_config().enforced):
        user = None
    valid = user is not None and default_token_generator.check_token(user, token)
    form = None
    if valid:
        form = SetPasswordForm(user, request.POST or None)
        if request.method == "POST" and form.is_valid():
            form.save()
            audit_log(AuditLog.UPDATE, actor=user, request=request, target=user, target_type="user",
                      field=str(tr("Slaptažodis")), new=str(tr("pakeistas per atkūrimo nuorodą")))
            if request.user.is_authenticated and request.user.pk == user.pk:
                update_session_auth_hash(request, user)
            messages.success(request, tr("Slaptažodis pakeistas. Galite prisijungti."))
            return redirect("login")
    return render(request, "registration/password_reset_set.html", {"form": form, "valid": valid})
