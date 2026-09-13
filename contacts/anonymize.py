"""Replace personal data in a staging clone with harmless placeholders.

A clone restored from production is useful for testing only if its shape stays
real — the same number of contacts, companies, activities, links, tags and dates —
and harmless only if nothing in it identifies a person. This keeps the former and
removes the latter:

* people, companies and their phones, e-mails, addresses, links, descriptions;
* activity and reminder texts, free-text custom field values;
* attachment files (replaced by a short placeholder file) and avatars;
* CRM users' names and e-mails (usernames too, except break-glass/superusers);
* incoming mail, the audit trail, automation and webhook logs, saved filters,
  sessions and sign-in attempt records are deleted outright.

Refuses to run on production. See ``manage.py sanitize_staging``.
"""
from secrets import token_urlsafe

from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core.files.base import ContentFile
from django.db import transaction

from .audit import sanctioned_delete
from .models import (Activity, Attachment, AuditLog, AutomationLog, Company, CustomField, CustomValue, EmailAddress,
                     IncomingMail, Person, PersonCompanyLink, PhoneNumber, PostalAddress, Reminder, SavedFilter,
                     UserProfile, WebhookDelivery, WebLink)

PLACEHOLDER_FILE = b"Anonimizuota testinei aplinkai / anonymised for the staging copy.\n"


def _rewrite(queryset, build, fields):
    """Set ``fields`` on every row from ``build(obj)``; returns the count."""
    batch, count = [], 0
    for obj in queryset.iterator(chunk_size=500):
        for name, value in build(obj).items():
            setattr(obj, name, value)
        batch.append(obj)
        if len(batch) == 500:
            queryset.model.objects.bulk_update(batch, fields)
            count, batch = count + len(batch), []
    if batch:
        queryset.model.objects.bulk_update(batch, fields)
        count += len(batch)
    return count


@transaction.atomic
def anonymize():
    counts = {}
    counts["people"] = _rewrite(Person.objects.all(), lambda p: {
        "first_name": "Vardas%d" % p.pk, "last_name": "Pavardė%d" % p.pk, "job_title": "", "description": ""},
        ["first_name", "last_name", "job_title", "description"])
    _rewrite(PhoneNumber.objects.all(), lambda o: {"number": "+370 600 %05d" % (o.pk % 100000)}, ["number"])
    _rewrite(EmailAddress.objects.all(), lambda o: {"email": "asmuo%d@example.invalid" % o.pk}, ["email"])
    _rewrite(PostalAddress.objects.all(), lambda o: {"address": "Adresas %d" % o.pk}, ["address"])
    _rewrite(WebLink.objects.all(), lambda o: {"url": "https://example.invalid/%d" % o.pk}, ["url"])
    _rewrite(PersonCompanyLink.objects.exclude(role=""), lambda o: {"role": ""}, ["role"])
    counts["companies"] = _rewrite(Company.objects.all(), lambda c: {
        "name": "Įmonė %d" % c.pk, "company_code": "", "vat_code": "", "address": "", "phone": "",
        "email": "", "url": "", "description": ""},
        ["name", "company_code", "vat_code", "address", "phone", "email", "url", "description"])
    counts["activities"] = _rewrite(Activity.objects.all(), lambda a: {"text": "Įrašas %d" % a.pk, "message_id": ""},
                                    ["text", "message_id"])
    counts["reminders"] = _rewrite(Reminder.objects.all(), lambda r: {"text": "Priminimas %d" % r.pk}, ["text"])
    free_text = CustomValue.objects.filter(field__field_type__in=[CustomField.TEXT, CustomField.TEXTAREA]).exclude(value="")
    counts["custom_values"] = _rewrite(free_text, lambda v: {"value": "—"}, ["value"])

    attachments = 0
    for attachment in Attachment.objects.all().iterator(chunk_size=200):
        if attachment.file:
            attachment.file.delete(save=False)
        attachment.file.save("anonimizuota-%d.txt" % attachment.pk, ContentFile(PLACEHOLDER_FILE), save=False)
        attachment.original_name = "priedas-%d.txt" % attachment.pk
        attachment.content_type = "text/plain"
        attachment.save(update_fields=["file", "original_name", "content_type"])
        attachments += 1
    counts["attachments"] = attachments

    from .oidc import is_break_glass

    users = 0
    for user in get_user_model().objects.all().iterator():
        user.first_name, user.last_name = "Naudotojas", str(user.pk)
        user.email = "naudotojas%d@example.invalid" % user.pk
        if not is_break_glass(user):
            user.username = "naudotojas%d" % user.pk
        user.save(update_fields=["first_name", "last_name", "email", "username"])
        users += 1
    counts["users"] = users
    for profile in UserProfile.objects.all().iterator():
        if profile.avatar:
            profile.avatar.delete(save=False)
        profile.avatar = ""
        profile.directory_subject, profile.directory_groups = "", []
        profile.calendar_token, profile.unsubscribe_token = token_urlsafe(24), token_urlsafe(24)
        profile.save(update_fields=["avatar", "directory_subject", "directory_groups", "calendar_token",
                                    "unsubscribe_token", "updated_at"])

    counts["incoming_mail"] = IncomingMail.objects.all().delete()[0]
    counts["saved_filters"] = SavedFilter.objects.all().delete()[0]
    counts["automation_log"] = AutomationLog.objects.all().delete()[0]
    counts["webhook_deliveries"] = WebhookDelivery.objects.all().delete()[0]
    counts["sessions"] = Session.objects.all().delete()[0]
    counts["audit_log"] = sanctioned_delete(AuditLog.objects.all())
    try:
        from axes.models import AccessAttempt, AccessFailureLog, AccessLog
    except ImportError:  # pragma: no cover
        pass
    else:
        counts["sign_in_records"] = sum(model.objects.all().delete()[0]
                                        for model in (AccessAttempt, AccessLog, AccessFailureLog))
    return counts
