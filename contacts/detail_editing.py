from django.utils.translation import gettext_lazy as _
"""Field-scoped contact editing. Each request owns only one field or relation."""
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST

from .models import AuditLog, Company, DuplicateSettings, Person, PersonCompanyLink, PhoneNumber, EmailAddress, PostalAddress, WebLink
from .forms import CompanyForm
from .permissions import user_label as _user_label, visible_companies, visible_people
from .duplicates import find_company_duplicates, find_person_duplicates
from .audit import log as audit_log


DUPLICATE_REASON_LABELS = {
    "email": _("tas pats el. paštas"),
    "phone": _("tas pats telefonas"),
    "name": _("tas pats vardas arba pavadinimas"),
    "company": _("ta pati įmonė"),
    "company_code": _("tas pats įmonės kodas"),
    "vat_code": _("tas pats PVM kodas"),
    "url": _("tas pats URL"),
}


def duplicate_conflict(matches):
    candidates = [{
        "label": str(match["record"]),
        "url": match["record"].get_absolute_url(),
        "reasons": match["reasons"],
        "reason_labels": [str(DUPLICATE_REASON_LABELS[reason]) for reason in match["reasons"] if reason in DUPLICATE_REASON_LABELS],
    } for match in matches]
    return JsonResponse({
        "duplicate": True,
        "error": str(_("Rastas galimas dublikatas. Patikrinkite esamą įrašą arba patvirtinkite išsaugojimą.")),
        "candidates": candidates,
    }, status=409)


def person_duplicate_data(person, *, field, value):
    data = {
        "first_name": person.first_name,
        "last_name": person.last_name,
        "phone": "\n".join(person.phones.values_list("number", flat=True)),
        "email": "\n".join(person.emails.values_list("email", flat=True)),
        "companies": list(person.companies.all()),
    }
    if field == "full_name":
        data.update(value)
    elif field in {"first_name", "last_name"}:
        data[field] = value
    elif field == "phones":
        data["phone"] = "\n".join(value)
    elif field == "emails":
        data["email"] = "\n".join(value)
    elif field == "companies":
        data["companies"] = value
    return data


def company_duplicate_data(company, *, field, value):
    data = {key: getattr(company, key) for key in ("name", "company_code", "vat_code", "email", "phone", "url")}
    if field in data:
        data[field] = value
    return data


def company_field_context(company, field):
    value = getattr(company, field)
    href = {"phone": "tel:", "email": "mailto:"}.get(field, "")
    href = (href + value) if href and value else value if field == "url" else ""
    return {"company": company, "field": field, "label": CompanyForm.Meta.labels[field],
            "value": value, "entries": [{"text": value, "href": href}]}


def company_detail_fields(company):
    from .custom_fields import detail_context

    return [company_field_context(company, field) for field in CompanyForm.Meta.fields] + [responsibles_field_context(company)] + detail_context(company)


def title_html(record, request):
    context = {"person": record} if isinstance(record, Person) else {"company": record}
    return render_to_string("contacts/detail_title.html", context, request=request)


def owner_field_context(record):
    users = list(get_user_model().objects.filter(is_active=True).order_by("username"))
    context = {
        "field": "owner", "label": _("Atsakingas"), "owner": True,
        "users": [{"pk": user.pk, "label": _user_label(user), "selected": user.pk == record.owner_id} for user in users],
        "entries": [{"text": _user_label(record.owner)}] if record.owner_id else [],
    }
    context["person" if isinstance(record, Person) else "company"] = record
    return context


def responsibles_field_context(record):
    """Unified 'Atsakingi' card field: the primary (owner) plus extra responsibles."""
    users = list(get_user_model().objects.filter(is_active=True).order_by("first_name", "last_name", "username"))
    extra_ids = set(record.responsibles.values_list("id", flat=True))
    selected = extra_ids | ({record.owner_id} if record.owner_id else set())
    entries = []
    if record.owner_id:
        entries.append({"text": "%s · %s" % (_user_label(record.owner), _("pagrindinis"))})
    for user in users:
        if user.pk in extra_ids and user.pk != record.owner_id:
            entries.append({"text": _user_label(user)})
    context = {
        "field": "responsibles", "label": _("Atsakingi"), "responsibles": True,
        "has_primary": bool(record.owner_id),
        "users": [{"pk": user.pk, "label": _user_label(user),
                   "selected": user.pk in selected, "primary": user.pk == record.owner_id} for user in users],
        "entries": entries,
    }
    context["person" if isinstance(record, Person) else "company"] = record
    return context


def set_owner(record, request_post):
    user_id = request_post.get("value") or None
    new_owner = get_user_model().objects.filter(pk=user_id, is_active=True).first() if user_id else None
    if record.owner_id != (new_owner.pk if new_owner else None):
        record.owner = new_owner
        record.save(update_fields=["owner", "updated_at"])


def set_responsibles(record, request_post):
    """Apply the 'Atsakingi' editor: `primary` -> owner, the rest -> responsibles."""
    raw = list(request_post.getlist("responsible"))
    primary_raw = request_post.get("primary")
    if primary_raw and str(primary_raw).isdigit():
        raw.append(primary_raw)  # the primary is always one of the responsibles
    ids = {int(value) for value in raw if str(value).isdigit()}
    valid = {user.pk for user in get_user_model().objects.filter(pk__in=ids, is_active=True)}
    if primary_raw is None:
        # `primary` field absent entirely: keep the current owner if still selected.
        primary_id = record.owner_id if record.owner_id in valid else None
    elif str(primary_raw).isdigit() and int(primary_raw) in valid:
        primary_id = int(primary_raw)
    else:
        primary_id = None
    record.responsibles.set(sorted(valid - {primary_id}))
    if record.owner_id != primary_id:
        record.owner_id = primary_id
        record.save(update_fields=["owner", "updated_at"])
    else:
        record.save(update_fields=["updated_at"])


@login_required
@require_POST
@transaction.atomic
def edit_company_field(request, pk):
    company = get_object_or_404(visible_companies(request.user, Company.objects.select_for_update()), pk=pk, deleted_at__isnull=True)
    field = request.POST.get("field", "")
    before = _audit_snapshot(company)
    if field == "owner":
        set_owner(company, request.POST)
        _audit_field_changes(request, company, before)
        html = render_to_string("contacts/detail_field.html", {"item": owner_field_context(company)}, request=request)
        return JsonResponse({"ok": True, "name": company.name, "html": html})
    if field == "responsibles":
        set_responsibles(company, request.POST)
        _audit_field_changes(request, company, before)
        html = render_to_string("contacts/detail_field.html", {"item": responsibles_field_context(company)}, request=request)
        return JsonResponse({"ok": True, "name": company.name, "html": html})
    if field.startswith("cf_"):
        from .custom_fields import clean_and_store, field_by_key, single_context

        custom = field_by_key(company, field)
        if not custom:
            return JsonResponse({"error": "Netinkamas laukas."}, status=400)
        clean_and_store(company, custom, request.POST)
        company.save(update_fields=["updated_at"])
        _audit_field_changes(request, company, before)
        html = render_to_string("contacts/detail_field.html", {"item": single_context(company, field)}, request=request)
        return JsonResponse({"ok": True, "name": company.name, "html": html})
    if field not in CompanyForm.Meta.fields:
        return JsonResponse({"error": "Netinkamas laukas."}, status=400)
    try:
        value = company._meta.get_field(field).formfield().clean(request.POST.get("value", ""))
    except ValidationError as error:
        return JsonResponse({"error": " ".join(error.messages)}, status=400)
    changed = getattr(company, field) != value
    duplicate_settings = DuplicateSettings.load()
    if changed and field in {"name", "company_code", "vat_code", "email", "phone", "url"} and duplicate_settings.enabled and duplicate_settings.check_on_edit and request.POST.get("confirm_duplicate") != "1":
        matches = find_company_duplicates(company_duplicate_data(company, field=field, value=value), exclude_pk=company.pk, level=duplicate_settings.level)
        if matches:
            return duplicate_conflict(matches)
    if changed:
        setattr(company, field, value)
        company.save(update_fields=[field, "updated_at"])
    _audit_field_changes(request, company, before)
    html = title_html(company, request) if request.POST.get("render_title") == "1" and field == "name" else render_to_string(
        "contacts/detail_field.html", {"item": company_field_context(company, field)}, request=request
    )
    return JsonResponse({"ok": True, "name": company.name, "html": html})


SCALARS = {"first_name": _("Vardas"), "last_name": _("Pavardė"), "job_title": _("Pareigos"), "status": _("Būsena")}
_AUDIT_LABELS = {**SCALARS, "companies": _("Įmonės"), "owner": _("Atsakingas"),
                 "responsibles": _("Atsakingi"), "full_name": _("Vardas ir pavardė")}


def _audit_snapshot(record):
    """A flat {field: text} view of everything editable on a contact/company card."""
    is_person = isinstance(record, Person)
    data = {}
    for name in (SCALARS if is_person else CompanyForm.Meta.fields):
        data[name] = str(getattr(record, name, "") or "")
    if is_person:
        for name, spec in MULTIPLE.items():
            data[name] = ", ".join(getattr(record, name).values_list(spec[1], flat=True))
        data["companies"] = ", ".join(record.company_links.values_list("company__name", flat=True))
    data["owner"] = _user_label(record.owner) if record.owner_id else ""
    data["responsibles"] = ", ".join(sorted(_user_label(u) for u in record.responsibles.all()))
    for value in record.custom_values.select_related("field").all():
        data[value.field.key] = value.value
        _AUDIT_LABELS.setdefault(value.field.key, value.field.name)
    return data


def _audit_field_changes(request, record, before):
    record.refresh_from_db()
    after = _audit_snapshot(record)
    for name in before.keys() | after.keys():
        old, new = before.get(name, ""), after.get(name, "")
        if str(old) != str(new):
            audit_log(AuditLog.UPDATE, request=request, target=record,
                      field=str(_AUDIT_LABELS.get(name, name)), old=old, new=new)
MULTIPLE = {
    "phones": (PhoneNumber, "number", _("Telefonai"), "tel:"),
    "emails": (EmailAddress, "email", _("El. paštas"), "mailto:"),
    "addresses": (PostalAddress, "address", _("Adresai"), ""),
    "web_links": (WebLink, "url", _("Nuorodos"), None),
}


def field_context(person, field):
    if field == "owner":
        return owner_field_context(person)
    if field == "responsibles":
        return responsibles_field_context(person)
    if field.startswith("cf_"):
        from .custom_fields import single_context

        return single_context(person, field)
    if field in SCALARS:
        label = SCALARS[field]
        value = getattr(person, field)
        entries = [{"text": value}]
    elif field in MULTIPLE:
        model, column, label, prefix = MULTIPLE[field]
        entries = []
        for item in getattr(person, field).all():
            value = getattr(item, column)
            entries.append({"text": value, "href": value if prefix is None else prefix + value if prefix else ""})
        value = "\n".join(item["text"] for item in entries)
    else:
        label = _("Įmonės")
        selected = set(person.company_links.values_list("company_id", flat=True))
        companies = list(Company.objects.filter(deleted_at__isnull=True).order_by("name", "pk"))
        # Assigned companies are always at the top of the editor, never collapsed to primary only.
        companies.sort(key=lambda company: company.pk not in selected)
        entries = [{"text": link.company.name, "href": link.company.get_absolute_url()} for link in person.company_links.select_related("company")]
        return {"person": person, "field": field, "label": label, "entries": entries,
                "companies": [{"pk": c.pk, "name": c.name, "selected": c.pk in selected} for c in companies]}
    return {"person": person, "field": field, "label": label, "value": value, "entries": entries, "multiple": field in MULTIPLE}


def detail_fields(person):
    from .custom_fields import detail_context

    return [field_context(person, field) for field in ["companies", "responsibles", *SCALARS, *MULTIPLE]] + detail_context(person)


@login_required
@require_POST
@transaction.atomic
def edit_contact_field(request, pk):
    person = get_object_or_404(visible_people(request.user, Person.objects.select_for_update()), pk=pk, deleted_at__isnull=True)
    field = request.POST.get("field", "")
    before = _audit_snapshot(person)
    try:
        if field == "full_name":
            first_name = forms.CharField(max_length=100).clean(request.POST.get("first_name", ""))
            last_name = forms.CharField(max_length=100).clean(request.POST.get("last_name", ""))
            values = {"first_name": first_name, "last_name": last_name}
            changed = any(getattr(person, key) != value for key, value in values.items())
            if changed:
                duplicate_settings = DuplicateSettings.load()
                if duplicate_settings.enabled and duplicate_settings.check_on_edit and request.POST.get("confirm_duplicate") != "1":
                    matches = find_person_duplicates(person_duplicate_data(person, field=field, value=values), exclude_pk=person.pk, level=duplicate_settings.level)
                    if matches:
                        return duplicate_conflict(matches)
                person.first_name = first_name
                person.last_name = last_name
                person.save(update_fields=["first_name", "last_name", "updated_at"])
        elif field in SCALARS:
            value = person._meta.get_field(field).formfield().clean(request.POST.get("value", ""))
            changed = getattr(person, field) != value
            if changed and field in {"first_name", "last_name"}:
                duplicate_settings = DuplicateSettings.load()
                if duplicate_settings.enabled and duplicate_settings.check_on_edit and request.POST.get("confirm_duplicate") != "1":
                    matches = find_person_duplicates(person_duplicate_data(person, field=field, value=value), exclude_pk=person.pk, level=duplicate_settings.level)
                    if matches:
                        return duplicate_conflict(matches)
            if changed:
                setattr(person, field, value)
                person.save(update_fields=[field, "updated_at"])
        elif field in MULTIPLE:
            model, column, _, _ = MULTIPLE[field]
            validator = model._meta.get_field(column).formfield()
            values = list(dict.fromkeys(validator.clean(line.strip()) for line in request.POST.get("value", "").splitlines() if line.strip()))
            relation = getattr(person, field)
            changed = set(relation.values_list(column, flat=True)) != set(values)
            if changed and field in {"phones", "emails"}:
                duplicate_settings = DuplicateSettings.load()
                if duplicate_settings.enabled and duplicate_settings.check_on_edit and request.POST.get("confirm_duplicate") != "1":
                    matches = find_person_duplicates(person_duplicate_data(person, field=field, value=values), exclude_pk=person.pk, level=duplicate_settings.level)
                    if matches:
                        return duplicate_conflict(matches)
            if changed:
                # Keep unchanged rows and their labels/primary flags rather than replacing them all.
                relation.exclude(**{column + "__in": values}).delete()
                primary = "is_primary" in {f.name for f in model._meta.fields}
                for value in values:
                    if not relation.filter(**{column: value}).exists():
                        model.objects.create(person=person, **{column: value})
                if primary and relation.exists() and not relation.filter(is_primary=True).exists():
                    first = relation.first()
                    first.is_primary = True
                    first.save(update_fields=["is_primary"])
                person.save(update_fields=["updated_at"])
        elif field == "companies":
            selected = list(forms.ModelMultipleChoiceField(
                queryset=Company.objects.filter(deleted_at__isnull=True), required=False,
            ).clean(request.POST.getlist("companies")))
            name = forms.CharField(required=False, max_length=200).clean(request.POST.get("new_name", ""))
            existing_company = Company.objects.filter(name__iexact=name, deleted_at__isnull=True).first() if name else None
            if existing_company and existing_company not in selected:
                selected.append(existing_company)
            changed = set(person.company_links.values_list("company_id", flat=True)) != {company.pk for company in selected} or bool(name and existing_company is None)
            duplicate_settings = DuplicateSettings.load()
            if changed and duplicate_settings.enabled and duplicate_settings.check_on_edit and request.POST.get("confirm_duplicate") != "1":
                matches = find_person_duplicates(person_duplicate_data(person, field=field, value=selected), exclude_pk=person.pk, level=duplicate_settings.level)
                if matches:
                    return duplicate_conflict(matches)
            if changed:
                if name:
                    company = existing_company
                    if company is None:
                        company = Company.objects.create(name=name)
                    if company not in selected:
                        selected.append(company)
                links = person.company_links
                links.exclude(company__in=selected).delete()
                for company in selected:
                    PersonCompanyLink.objects.get_or_create(person=person, company=company)
                if links.exists() and not links.filter(is_primary=True).exists():
                    first = links.first()
                    first.is_primary = True
                    first.save(update_fields=["is_primary"])
                person.save(update_fields=["updated_at"])
        elif field == "owner":
            set_owner(person, request.POST)
        elif field == "responsibles":
            set_responsibles(person, request.POST)
        elif field.startswith("cf_"):
            from .custom_fields import clean_and_store, field_by_key

            custom = field_by_key(person, field)
            if not custom:
                return JsonResponse({"error": "Netinkamas laukas."}, status=400)
            clean_and_store(person, custom, request.POST)
            person.save(update_fields=["updated_at"])
        else:
            return JsonResponse({"error": "Netinkamas laukas."}, status=400)
    except ValidationError as error:
        return JsonResponse({"error": " ".join(error.messages)}, status=400)
    _audit_field_changes(request, person, before)
    html = title_html(person, request) if field == "full_name" else render_to_string(
        "contacts/detail_field.html", {"item": field_context(person, field)}, request=request
    )
    return JsonResponse({"ok": True, "name": str(person), "job_title": person.job_title, "html": html})
