"""Which card a record in another system belongs to.

A contact or company mirrors one row in its primary source on the record
itself (``external_source`` / ``external_id``, set by import, sync or the API).
Secondary systems — DocLogix, the call platform — are linked through
``ExternalLink``. Either way one external id belongs to one card: a second
card claiming it is refused, so a sync or a document list never lands on the
wrong person.

Linking and unlinking are audited. The audit names the system and its id, never
a personal code.
"""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from .audit import log as audit_log
from .models import AuditLog, Company, ExternalLink, Person


def _alive(model):
    return model.objects.filter(deleted_at__isnull=True)


def find_record(source, external_id):
    """The live contact or company that `external_id` in `source` belongs to, or None."""
    if not source or not external_id:
        return None
    for model in (Person, Company):
        record = _alive(model).filter(external_source=source, external_id=external_id).first()
        if record is not None:
            return record
    link = ExternalLink.objects.filter(source=source, external_id=external_id).select_related(
        "person", "company").first()
    record = link.record if link else None
    return record if record is not None and record.deleted_at is None else None


def _owner(source, external_id):
    """Whoever holds the id already, live or archived — an archived card still owns it."""
    for model in (Person, Company):
        record = model.objects.filter(external_source=source, external_id=external_id).first()
        if record is not None:
            return record
    link = ExternalLink.objects.filter(source=source, external_id=external_id).first()
    return link.record if link else None


@transaction.atomic
def link(record, source, external_id, *, method=ExternalLink.MANUAL, user=None, label=""):
    """Link `record` to `external_id` in `source`; the link, new or the one it already had."""
    source, external_id = (source or "").strip()[:32], (external_id or "").strip()[:128]
    if not source or not external_id:
        raise ValidationError(_("Nurodykite sistemą ir įrašo ID joje."))
    owner = _owner(source, external_id)
    if owner is not None and owner != record:
        # No name in the message: whoever links may not be allowed to see that card.
        raise ValidationError(_("Šis %(source)s įrašas jau susietas su kita kortele.") % {"source": source},
                              code="taken")
    field = "company" if isinstance(record, Company) else "person"
    existing = ExternalLink.objects.filter(source=source, external_id=external_id, **{field: record}).first()
    if existing is not None:
        if label and existing.label != label[:255]:
            existing.label = label[:255]
            existing.save(update_fields=["label"])
        return existing
    if owner == record:
        # It is the record's primary id; there is nothing to add.
        raise ValidationError(_("Kortelė jau susieta su šiuo įrašu kaip pagrindiniu šaltiniu."))
    created = ExternalLink.objects.create(source=source, external_id=external_id, method=method,
                                          linked_by=user, label=label[:255], **{field: record})
    audit_log(AuditLog.UPDATE, actor=user, target=record, field="external_link", new=str(created),
              detail={"method": method})
    return created


@transaction.atomic
def unlink(external_link, user=None):
    """Remove one link; the audit keeps who removed which."""
    record = external_link.record
    audit_log(AuditLog.UPDATE, actor=user, target=record, field="external_link", old=str(external_link))
    external_link.delete()
