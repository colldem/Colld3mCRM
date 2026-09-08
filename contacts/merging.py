import re

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from .models import Activity, Company, Person, Reminder


def _merge_labels(source, target):
    for relation_name in ("tags", "categories"):
        source_ids = set(getattr(source, relation_name).values_list("pk", flat=True))
        target_ids = set(getattr(target, relation_name).values_list("pk", flat=True))
        combined = source_ids | target_ids
        if len(combined) > 3:
            raise ValidationError(_("Prieš sujungiant palikite ne daugiau kaip 3 bendras žymas ir 3 bendras kategorijas."))
        getattr(target, relation_name).add(*(combined - target_ids))


def _merge_responsibles(source, target):
    """Keep the target's primary owner; fold in the source's people as extra responsibles."""
    fields = []
    if not target.owner_id and source.owner_id:
        target.owner_id = source.owner_id
        fields.append("owner")
    if fields:
        target.save(update_fields=[*fields, "updated_at"])
    extra = set(source.responsibles.values_list("pk", flat=True))
    if source.owner_id:
        extra.add(source.owner_id)
    extra.discard(target.owner_id)
    if extra:
        target.responsibles.add(*extra)


def _move_unique_children(source, target, relation_name, value_field, normalize):
    source_relation = getattr(source, relation_name)
    target_relation = getattr(target, relation_name)
    existing = {normalize(value) for value in target_relation.values_list(value_field, flat=True)}
    for child in source_relation.all():
        value = normalize(getattr(child, value_field))
        if value not in existing:
            child.person = target
            child.save(update_fields=["person"])
            existing.add(value)


def _merge_person_company_links(source, target):
    original_primary_id = target.company_links.filter(is_primary=True).values_list("pk", flat=True).first()
    for link in list(source.company_links.select_related("company")):
        existing = target.company_links.filter(company=link.company).first()
        if existing:
            fields = []
            if not existing.role and link.role:
                existing.role = link.role
                fields.append("role")
            if link.is_primary and not existing.is_primary:
                existing.is_primary = True
                fields.append("is_primary")
            if fields:
                existing.save(update_fields=fields)
        else:
            link.person = target
            link.save(update_fields=["person"])
    links = target.company_links.order_by("pk")
    chosen_primary_id = original_primary_id or links.filter(is_primary=True).values_list("pk", flat=True).first()
    if chosen_primary_id is None:
        chosen_primary_id = links.values_list("pk", flat=True).first()
    if chosen_primary_id is not None:
        links.exclude(pk=chosen_primary_id).update(is_primary=False)
        links.filter(pk=chosen_primary_id).update(is_primary=True)


def _merge_company_person_links(source, target):
    for link in list(source.person_links.select_related("person")):
        existing = target.person_links.filter(person=link.person).first()
        if existing:
            fields = []
            if not existing.role and link.role:
                existing.role = link.role
                fields.append("role")
            if link.is_primary and not existing.is_primary:
                existing.is_primary = True
                fields.append("is_primary")
            if fields:
                existing.save(update_fields=fields)
        else:
            link.company = target
            link.save(update_fields=["company"])


@transaction.atomic
def merge_people(source_pk, target_pk):
    if source_pk == target_pk:
        raise ValidationError(_("Negalima sujungti įrašo su juo pačiu."))
    records = {record.pk: record for record in Person.objects.select_for_update().filter(pk__in=[source_pk, target_pk])}
    if len(records) != 2:
        raise ValidationError(_("Vienas iš sujungiamų įrašų nerastas."))
    source, target = records[source_pk], records[target_pk]
    if source.merged_into_id:
        if source.merged_into_id == target.pk:
            return target
        raise ValidationError(_("Šis įrašas jau sujungtas su kitu įrašu."))
    if source.deleted_at or target.deleted_at or target.merged_into_id:
        raise ValidationError(_("Sujungti galima tik du aktyvius įrašus."))

    _merge_labels(source, target)
    _merge_responsibles(source, target)
    changed_fields = []
    for field in ("first_name", "last_name", "job_title", "description"):
        if not getattr(target, field) and getattr(source, field):
            setattr(target, field, getattr(source, field))
            changed_fields.append(field)
    if source.favourite and not target.favourite:
        target.favourite = True
        changed_fields.append("favourite")
    if changed_fields:
        target.save(update_fields=[*changed_fields, "updated_at"])

    _move_unique_children(source, target, "phones", "number", lambda value: re.sub(r"\D", "", value))
    _move_unique_children(source, target, "emails", "email", lambda value: value.strip().casefold())
    _move_unique_children(source, target, "addresses", "address", lambda value: value.strip().casefold())
    _move_unique_children(source, target, "web_links", "url", lambda value: value.strip().rstrip("/").casefold())
    _merge_person_company_links(source, target)
    Activity.objects.filter(person=source).update(person=target)
    Reminder.objects.filter(person=source).update(person=target)
    source.merged_into = target
    source.deleted_at = timezone.now()
    source.save(update_fields=["merged_into", "deleted_at", "updated_at"])
    return target


@transaction.atomic
def merge_companies(source_pk, target_pk):
    if source_pk == target_pk:
        raise ValidationError(_("Negalima sujungti įrašo su juo pačiu."))
    records = {record.pk: record for record in Company.objects.select_for_update().filter(pk__in=[source_pk, target_pk])}
    if len(records) != 2:
        raise ValidationError(_("Vienas iš sujungiamų įrašų nerastas."))
    source, target = records[source_pk], records[target_pk]
    if source.merged_into_id:
        if source.merged_into_id == target.pk:
            return target
        raise ValidationError(_("Šis įrašas jau sujungtas su kitu įrašu."))
    if source.deleted_at or target.deleted_at or target.merged_into_id:
        raise ValidationError(_("Sujungti galima tik dvi aktyvias įmones."))

    _merge_labels(source, target)
    _merge_responsibles(source, target)
    changed_fields = []
    for field in ("name", "company_code", "vat_code", "address", "phone", "email", "url", "description"):
        if not getattr(target, field) and getattr(source, field):
            setattr(target, field, getattr(source, field))
            changed_fields.append(field)
    if changed_fields:
        target.save(update_fields=[*changed_fields, "updated_at"])
    _merge_company_person_links(source, target)
    Activity.objects.filter(company=source).update(company=target)
    source.merged_into = target
    source.deleted_at = timezone.now()
    source.save(update_fields=["merged_into", "deleted_at", "updated_at"])
    return target
