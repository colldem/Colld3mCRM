from urllib.parse import urlencode

from django.db.models import Max, Q
from django.utils.dateparse import parse_date
from django.utils.translation import gettext as _

from .models import CustomField


def _custom_values(data, entity):
    """Flatten non-empty custom-field filters as {"cf_<id>": "text"}."""
    result = {}
    for field in CustomField.objects.filter(entity=entity):
        value = data.get(field.key, "").strip()
        if value:
            result[field.key] = value
    return result


CONTACT_FILTER_KEYS = (
    "q",
    "categories",
    "tags",
    "email",
    "favourite",
    "last_contact_from",
    "last_contact_to",
)
COMPANY_FILTER_KEYS = (
    "q",
    "categories",
    "tags",
    "city",
    "last_contact_from",
    "last_contact_to",
)


def _ids(data, key, legacy_key=None):
    values = data.getlist(key)
    if not values and legacy_key and data.get(legacy_key):
        values = [data.get(legacy_key)]
    return list(dict.fromkeys(int(value) for value in values if str(value).isdigit()))


def _date(data, key):
    value = data.get(key, "").strip()
    return value if value and parse_date(value) else ""


def contact_filter_values(data):
    return {
        "q": data.get("q", "").strip(),
        "categories": _ids(data, "categories", "category"),
        "tags": _ids(data, "tags", "tag"),
        "email": data.get("email", "").strip(),
        "favourite": "1" if data.get("favourite") == "1" else "",
        "last_contact_from": _date(data, "last_contact_from"),
        "last_contact_to": _date(data, "last_contact_to"),
        **_custom_values(data, CustomField.PERSON),
    }


def company_filter_values(data):
    return {
        "q": data.get("q", "").strip(),
        "categories": _ids(data, "categories", "category"),
        "tags": _ids(data, "tags", "tag"),
        "city": data.get("city", "").strip(),
        "last_contact_from": _date(data, "last_contact_from"),
        "last_contact_to": _date(data, "last_contact_to"),
        **_custom_values(data, CustomField.COMPANY),
    }


def _apply_custom_filters(queryset, values):
    for key, value in values.items():
        if key.startswith("cf_") and value:
            queryset = queryset.filter(custom_values__field_id=key[3:], custom_values__value__icontains=value)
    return queryset


def apply_contact_filters(people, values):
    for term in values["q"].split():
        people = people.filter(
            Q(first_name__icontains=term)
            | Q(last_name__icontains=term)
            | Q(job_title__icontains=term)
            | Q(company_links__company__name__icontains=term)
            | Q(phones__number__icontains=term)
            | Q(emails__email__icontains=term)
            | Q(tags__name__icontains=term)
            | Q(categories__name__icontains=term)
            | Q(addresses__address__icontains=term)
            | Q(web_links__url__icontains=term)
            | Q(status__icontains=term)
            | Q(custom_values__value__icontains=term)
        )
    if values["categories"]:
        people = people.filter(categories__pk__in=values["categories"])
    if values["tags"]:
        people = people.filter(tags__pk__in=values["tags"])
    if values["email"]:
        people = people.filter(emails__email__icontains=values["email"])
    if values["favourite"]:
        people = people.filter(favourite=True)
    # last_contact_at is annotated by the contact_list view before filtering.
    if values["last_contact_from"]:
        people = people.filter(last_contact_at__date__gte=values["last_contact_from"])
    if values["last_contact_to"]:
        people = people.filter(last_contact_at__date__lte=values["last_contact_to"])
    people = _apply_custom_filters(people, values)
    return people.distinct()


def apply_company_filters(companies, values):
    for term in values["q"].split():
        companies = companies.filter(
            Q(name__icontains=term)
            | Q(company_code__icontains=term)
            | Q(vat_code__icontains=term)
            | Q(address__icontains=term)
            | Q(phone__icontains=term)
            | Q(email__icontains=term)
            | Q(url__icontains=term)
            | Q(people__first_name__icontains=term)
            | Q(people__last_name__icontains=term)
            | Q(people__job_title__icontains=term)
            | Q(people__emails__email__icontains=term)
            | Q(people__phones__number__icontains=term)
            | Q(custom_values__value__icontains=term)
        )
    if values["categories"]:
        companies = companies.filter(categories__pk__in=values["categories"])
    if values["tags"]:
        companies = companies.filter(tags__pk__in=values["tags"])
    if values["city"]:
        companies = companies.filter(address__icontains=values["city"])
    if values["last_contact_from"] or values["last_contact_to"]:
        companies = companies.annotate(
            own_last_contact_at=Max(
                "activities__created_at",
                filter=Q(activities__deleted_at__isnull=True),
            ),
            linked_last_contact_at=Max(
                "people__activities__created_at",
                filter=Q(
                    people__deleted_at__isnull=True,
                    people__activities__deleted_at__isnull=True,
                ),
            ),
        )
    if values["last_contact_from"]:
        companies = companies.filter(
            Q(own_last_contact_at__date__gte=values["last_contact_from"])
            | Q(linked_last_contact_at__date__gte=values["last_contact_from"])
        )
    if values["last_contact_to"]:
        companies = companies.filter(
            (Q(own_last_contact_at__isnull=True) | Q(own_last_contact_at__date__lte=values["last_contact_to"]))
            & (Q(linked_last_contact_at__isnull=True) | Q(linked_last_contact_at__date__lte=values["last_contact_to"]))
        )
    companies = _apply_custom_filters(companies, values)
    return companies.distinct()


def active_filter_count(values):
    return sum(bool(value) for key, value in values.items() if key != "q")


def saved_filter_payload(data, scope):
    values = contact_filter_values(data) if scope == "contacts" else company_filter_values(data)
    return {key: value for key, value in values.items() if value}


def encoded_filter_values(values):
    return urlencode([(key, item) for key, value in values.items() for item in (value if isinstance(value, list) else [value])])


def filter_chips(data, values, label_maps, path):
    labels = {
        "email": _("El. paštas"),
        "favourite": _("Tik mėgstami"),
        "city": _("Miestas arba adresas"),
        "last_contact_from": _("Nuo"),
        "last_contact_to": _("Iki"),
    }
    chips = []
    for key, value in values.items():
        if key == "q" or not value:
            continue
        selected = value if isinstance(value, list) else [value]
        for item in selected:
            display = label_maps.get(key, {}).get(item, item)
            if key == "favourite":
                display = _("Taip")
            query = data.copy()
            if isinstance(value, list):
                remaining = [str(candidate) for candidate in value if candidate != item]
                query.setlist(key, remaining)
            else:
                query.pop(key, None)
            query.pop("page", None)
            chips.append({
                "label": labels.get(key, label_maps.get("titles", {}).get(key, key)),
                "value": display,
                "remove_url": f"{path}?{query.urlencode()}" if query else path,
            })
    return chips
