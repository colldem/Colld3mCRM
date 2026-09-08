"""Helpers for user-defined (custom) fields on people and companies."""
from django.utils.translation import gettext as _

from .models import CustomField, CustomValue, Person


def entity_of(record):
    return CustomField.PERSON if isinstance(record, Person) else CustomField.COMPANY


def fields_for(entity):
    return list(CustomField.objects.filter(entity=entity))


def _decode(field, raw):
    if field.field_type == CustomField.BOOL:
        return raw == "1"
    if field.field_type == CustomField.MULTISELECT:
        return [line for line in (raw or "").splitlines() if line]
    return raw or ""


def _encode(field, value):
    if field.field_type == CustomField.BOOL:
        return "1" if value else ""
    if field.field_type == CustomField.MULTISELECT:
        return "\n".join(v for v in value if v)
    return (value or "").strip()


def values_by_field(record):
    """Map of CustomField.pk -> decoded value for this record."""
    return {item.field_id: _decode(item.field, item.value) for item in record.custom_values.select_related("field")}


def display(field, decoded):
    if field.field_type == CustomField.BOOL:
        return _("Taip") if decoded else _("Ne")
    if field.field_type == CustomField.MULTISELECT:
        return ", ".join(decoded) if decoded else ""
    return decoded or ""


def field_editor_context(field, decoded):
    """Data the detail_field.html template needs to render an editor for one custom field."""
    return {
        "field": field.key,
        "label": field.name,
        "custom_type": field.field_type,
        "custom_options": field.options if field.choice_type else [],
        "value": decoded if field.field_type != CustomField.MULTISELECT else "",
        "selected": set(decoded) if field.field_type == CustomField.MULTISELECT else set(),
        "checked": bool(decoded) if field.field_type == CustomField.BOOL else False,
        "entries": [{"text": display(field, decoded)}],
        "custom": True,
    }


def detail_context(record):
    """Return field_context-shaped dicts for every custom field of the record's entity."""
    values = values_by_field(record)
    key = "person" if entity_of(record) == CustomField.PERSON else "company"
    contexts = []
    for field in fields_for(entity_of(record)):
        context = field_editor_context(field, values.get(field.pk, [] if field.field_type == CustomField.MULTISELECT else ""))
        context[key] = record
        contexts.append(context)
    return contexts


def single_context(record, cf_key):
    """One field_context-shaped dict for the custom field named by `cf_<id>` (or None)."""
    field = CustomField.objects.filter(pk=cf_key[3:], entity=entity_of(record)).first()
    if not field:
        return None
    decoded = values_by_field(record).get(field.pk, [] if field.field_type == CustomField.MULTISELECT else "")
    context = field_editor_context(field, decoded)
    context["person" if entity_of(record) == CustomField.PERSON else "company"] = record
    return context


def field_by_key(record, cf_key):
    return CustomField.objects.filter(pk=cf_key[3:], entity=entity_of(record)).first()


def clean_and_store(record, field, request_post):
    """Validate the posted value for `field` and save it. Returns the decoded value."""
    if field.field_type == CustomField.MULTISELECT:
        chosen = [v for v in request_post.getlist("value") if v in field.options]
        raw = _encode(field, chosen)
        decoded = chosen
    elif field.field_type == CustomField.SELECT:
        picked = request_post.get("value", "").strip()
        if picked and picked not in field.options:
            picked = ""
        raw, decoded = picked, picked
    elif field.field_type == CustomField.BOOL:
        decoded = request_post.get("value") in ("1", "on", "true")
        raw = _encode(field, decoded)
    else:
        text = request_post.get("value", "").strip()
        if field.field_type == CustomField.TEXTAREA:
            text = text[:1000]
        else:
            text = text[:200]
        raw, decoded = text, text
    lookup = {"person": record} if entity_of(record) == CustomField.PERSON else {"company": record}
    CustomValue.objects.update_or_create(field=field, defaults={"value": raw}, **lookup)
    return decoded
