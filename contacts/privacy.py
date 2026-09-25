"""Data subject requests (GDPR / BDAR arts. 15, 17 and 20) for a contact person.

* ``export_person`` — everything the CRM holds about one person, as a ZIP with
  a machine-readable ``data.json`` and the attached files (access, portability).
* ``erase_person`` — erasure: the person, contact details, links, activities,
  reminders, custom values, attachments and their files, matching incoming mail
  and automation/webhook log entries are deleted; audit rows about the person keep
  who did what and when but lose names and values (contacts.audit.sanctioned_redact).

Both are administrator actions and are themselves audited without personal data.
Database backups keep the erased data until they rotate out — see the documentation.
"""
import io
import json
import zipfile

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from . import identity
from .audit import REDACTED, log as audit_log, sanctioned_redact
from .models import (Activity, Attachment, AuditLog, AutomationLog, Company, CustomValue, DuplicateException,
                     IncomingMail, Person, Reminder, SystemSettings, WebhookDelivery)


def _kind(record):
    return "company" if isinstance(record, Company) else "person"


def _identifiers(record):
    """Strings that identify the record inside free text of other rows."""
    values = {str(record).strip()}
    if isinstance(record, Company):
        values |= {record.email.lower(), record.phone}
    else:
        values |= {email.lower() for email in record.emails.values_list("email", flat=True)}
        values |= set(record.phones.values_list("number", flat=True))
    return {value for value in values if len(value) >= 5}


def _related(person):
    owner = {_kind(person): person}
    activities = Activity.objects.filter(**owner)
    activity_ids = list(activities.values_list("pk", flat=True))
    reminder_ids = list(Reminder.objects.filter(**owner).values_list("pk", flat=True))
    if isinstance(person, Company):
        emails = [person.email.lower()] if person.email else []
    else:
        emails = [email.lower() for email in person.emails.values_list("email", flat=True)]
    mail_filter = Q(resolved_activity_id__in=activity_ids)
    for email in emails:
        mail_filter |= Q(from_addr__icontains=email)
    return {
        "activities": activities,
        "activity_ids": activity_ids,
        "reminder_ids": reminder_ids,
        "attachments": Attachment.objects.filter(activity_id__in=activity_ids),
        "mail": IncomingMail.objects.filter(mail_filter) if activity_ids or emails else IncomingMail.objects.none(),
    }


def _audit_rows(person, related):
    targets = Q(target_type=_kind(person), target_id=str(person.pk))
    if related["activity_ids"]:
        targets |= Q(target_type="activity", target_id__in=[str(pk) for pk in related["activity_ids"]])
    if related["reminder_ids"]:
        targets |= Q(target_type="reminder", target_id__in=[str(pk) for pk in related["reminder_ids"]])
    mentions = Q()
    for value in _identifiers(person):
        mentions |= Q(target_label__icontains=value) | Q(old_value__icontains=value) | Q(new_value__icontains=value)
    return AuditLog.objects.filter(targets | mentions).exclude(target_label=REDACTED, old_value="", new_value="")


def summary(person):
    related = _related(person)
    return {
        "activities": len(related["activity_ids"]),
        "reminders": len(related["reminder_ids"]),
        "attachments": related["attachments"].count(),
        "incoming_mail": related["mail"].count(),
        "audit_rows": _audit_rows(person, related).count(),
    }


def _dt(value):
    return value.isoformat() if value else None


def person_data(person):
    related = _related(person)
    return {
        "exported_at": timezone.now().isoformat(),
        "person": {
            "id": person.pk, "first_name": person.first_name, "last_name": person.last_name,
            "job_title": person.job_title, "description": person.description, "favourite": person.favourite,
            # The subject's own identifiers belong in their copy of the data.
            "birth_date": person.birth_date.isoformat() if person.birth_date else None,
            "personal_code_type": person.personal_code_type or None,
            "personal_code": identity.reveal(person) or None,
            "external_source": person.external_source or None, "external_id": person.external_id or None,
            "created_at": _dt(person.created_at), "updated_at": _dt(person.updated_at),
            "archived_at": _dt(person.deleted_at),
            "owner": person.owner.get_username() if person.owner else None,
            "tags": list(person.tags.values_list("name", flat=True)),
            "categories": list(person.categories.values_list("name", flat=True)),
        },
        "phones": list(person.phones.values("number", "label")),
        "emails": list(person.emails.values("email", "label")),
        "addresses": list(person.addresses.values("address", "label")),
        "web_links": list(person.web_links.values("url", "label")),
        "companies": [{"company": link.company.name, "role": link.role} for link in
                      person.company_links.select_related("company")],
        "custom_fields": [{"field": value.field.name, "value": value.value} for value in
                          CustomValue.objects.filter(person=person).select_related("field")],
        "activities": [{"id": a.pk, "type": a.activity_type, "text": a.text, "created_at": _dt(a.created_at),
                        "author": a.created_by.get_username(), "archived_at": _dt(a.deleted_at),
                        "attachments": [f.original_name for f in a.attachments.all()]}
                       for a in related["activities"].select_related("created_by").prefetch_related("attachments")],
        "reminders": [{"text": r.text, "due_at": _dt(r.due_at), "created_at": _dt(r.created_at)}
                      for r in Reminder.objects.filter(person=person)],
        "incoming_mail": [{"from": m.from_addr, "to": m.to_addrs, "subject": m.subject, "body": m.body,
                           "received_at": _dt(m.received_at)} for m in related["mail"]],
        "audit_trail": [{"at": _dt(e.created_at), "by": e.actor_label, "action": e.action, "field": e.field,
                         "old": e.old_value, "new": e.new_value}
                        for e in AuditLog.objects.filter(target_type="person", target_id=str(person.pk))],
    }


def export_person(person, request):
    """A ZIP (``data.json`` + ``attachments/``) of everything held about ``person``."""
    data = person_data(person)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("data.json", json.dumps(data, ensure_ascii=False, indent=2))
        for attachment in _related(person)["attachments"]:
            try:
                with attachment.file.open("rb") as handle:
                    archive.writestr("attachments/%d-%s" % (attachment.pk, attachment.original_name), handle.read())
            except (FileNotFoundError, ValueError, OSError):
                archive.writestr("attachments/%d-MISSING.txt" % attachment.pk, "file not found in storage")
    audit_log(AuditLog.EXPORT, request=request, target_type="person", target_id=str(person.pk),
              target_label="data subject export", detail={"reason": "data_subject_request"})
    return buffer.getvalue()


def erase_person(person, request, reason="data_subject_erasure"):
    """Erase a person (or, for retention, a company); returns what was removed."""
    kind = _kind(person)
    related = _related(person)
    person_id = person.pk
    files = [attachment.file.name for attachment in related["attachments"] if attachment.file]
    storage = Attachment._meta.get_field("file").storage
    identifiers = _identifiers(person)
    with transaction.atomic():
        counts = summary(person)
        counts["audit_rows"] = sanctioned_redact(_audit_rows(person, related))
        counts["incoming_mail"] = related["mail"].delete()[0]
        counts["automation_log"] = AutomationLog.objects.filter(target_type=kind, target_id=str(person_id)).delete()[0]
        deliveries = [d.pk for d in WebhookDelivery.objects.all().iterator()
                      if any(value.lower() in json.dumps(d.payload, ensure_ascii=False).lower() for value in identifiers)]
        counts["webhook_deliveries"] = WebhookDelivery.objects.filter(pk__in=deliveries).delete()[0]
        DuplicateException.objects.filter(kind=kind).filter(Q(left_id=person_id) | Q(right_id=person_id)).delete()
        person.delete()
        transaction.on_commit(lambda: [storage.delete(name) for name in files])
        audit_log(AuditLog.DELETE, request=request, target_type=kind, target_id=str(person_id),
                  target_label=REDACTED, detail={"reason": reason, **counts})
    return counts


def find_people(query):
    """Active and archived people matching a name, e-mail, phone or personal code."""
    query = (query or "").strip()
    if len(query) < 2:
        return Person.objects.none()
    parts = query.split()
    by_name = Q()
    for part in parts:
        by_name &= Q(first_name__icontains=part) | Q(last_name__icontains=part)
    by_code = Q(personal_code_hash__in=identity.candidate_hashes(query)) if identity.available() else Q(pk__in=[])
    return (Person.objects.filter(by_name | by_code | Q(emails__email__icontains=query) | Q(phones__number__icontains=query))
            .distinct().order_by("last_name", "first_name")[:50])


# --- retention -------------------------------------------------------------

RETENTION_MINIMUM_DAYS = 30


def retention_candidates(now=None):
    """What the retention settings would delete right now (querysets)."""
    from datetime import timedelta

    now = now or timezone.now()
    system = SystemSettings.load()
    empty = {"people": Person.objects.none(), "companies": Company.objects.none(), "mail": IncomingMail.objects.none()}
    if system.archived_retention_days:
        cutoff = now - timedelta(days=max(system.archived_retention_days, RETENTION_MINIMUM_DAYS))
        empty["people"] = Person.objects.filter(deleted_at__lt=cutoff)
        empty["companies"] = Company.objects.filter(deleted_at__lt=cutoff)
    if system.incoming_mail_retention_days:
        cutoff = now - timedelta(days=max(system.incoming_mail_retention_days, RETENTION_MINIMUM_DAYS))
        empty["mail"] = IncomingMail.objects.filter(received_at__lt=cutoff)
    return empty


def apply_retention(now=None):
    """Delete what is past retention; each record goes through the erasure path."""
    candidates = retention_candidates(now)
    done = {"people": 0, "companies": 0, "mail": 0}
    for key in ("people", "companies"):
        for record in candidates[key].iterator(chunk_size=100):
            erase_person(record, request=None, reason="retention")
            done[key] += 1
    done["mail"] = candidates["mail"].delete()[0]
    if done["mail"]:
        audit_log(AuditLog.DELETE, target_type="incoming_mail", target_label="retention",
                  detail={"reason": "retention", "deleted": done["mail"]})
    return done
