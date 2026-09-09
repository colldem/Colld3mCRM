"""Hand-rolled JSON API (H3).

Bearer-token auth (``Authorization: Bearer crmk_…``). A token acts with its
creator's record visibility and capabilities; ``read`` tokens cannot write.
No DRF — matches the rest of the project. Endpoints live under ``/api/v1/``.
"""
import hashlib
import json
import logging
from functools import wraps

from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt

from .audit import log as audit_log
from .models import (
    Activity, ApiToken, AuditLog, Category, Company, DuplicateSettings,
    EmailAddress, Person, PersonCompanyLink, PhoneNumber, PostalAddress,
    Reminder, Tag, WebLink,
)
from .permissions import assignable_users_for, has_capability, visible_companies, visible_people, visible_reminders
from .sanitizers import safe_url

logger = logging.getLogger(__name__)
MAX_PAGE = 100


class ApiError(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message


def _authenticate(request):
    header = request.META.get("HTTP_AUTHORIZATION", "")
    if not header.startswith("Bearer "):
        raise ApiError(401, "missing bearer token")
    digest = hashlib.sha256(header[7:].strip().encode()).hexdigest()
    token = (ApiToken.objects.filter(token_hash=digest, revoked_at__isnull=True)
             .select_related("created_by").first())
    if token is None or not token.created_by.is_active:
        raise ApiError(401, "invalid or revoked token")
    if token.last_used_at is None or (timezone.now() - token.last_used_at).total_seconds() > 300:
        ApiToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now())
    return token


def api_view(fn):
    @csrf_exempt
    @wraps(fn)
    def wrapper(request, *args, **kwargs):
        try:
            token = _authenticate(request)
            return fn(request, token, *args, **kwargs)
        except ApiError as error:
            return JsonResponse({"error": error.message}, status=error.status)
        except Exception:  # never leak a stack trace over the API
            logger.exception("unhandled API error")
            return JsonResponse({"error": "internal error"}, status=500)
    return wrapper


def _require_write(token):
    if token.scope != ApiToken.READ_WRITE:
        raise ApiError(403, "token is read-only")


def _json_body(request):
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        raise ApiError(400, "invalid JSON body") from None
    if not isinstance(data, dict):
        raise ApiError(400, "body must be a JSON object")
    return data


def _paginate(request, queryset):
    try:
        limit = min(max(int(request.GET.get("limit", 50)), 1), MAX_PAGE)
        offset = max(int(request.GET.get("offset", 0)), 0)
    except (TypeError, ValueError):
        raise ApiError(400, "bad limit or offset") from None
    total = queryset.count()
    return list(queryset[offset:offset + limit]), total, limit, offset


def _list_response(request, queryset, serializer):
    rows, total, limit, offset = _paginate(request, queryset)
    response = JsonResponse({"results": [serializer(row) for row in rows],
                             "count": total, "limit": limit, "offset": offset})
    response["X-Total-Count"] = str(total)
    return response


def _since(request):
    raw = request.GET.get("updated_since") or request.GET.get("since")
    return parse_datetime(raw) if raw else None


def _assignable_user(actor, pk):
    """An active user `actor` is allowed to set as owner/assignee, else None."""
    if pk in (None, "", 0):
        return None
    return assignable_users_for(actor).filter(pk=pk).first()


# --- serializers -----------------------------------------------------------

def _custom_fields(record):
    from .custom_fields import _decode

    return {v.field.key: _decode(v.field, v.value)
            for v in record.custom_values.select_related("field").all()}


def _q_person(query):
    clause = Q()
    for term in query.split():
        clause &= (Q(first_name__icontains=term) | Q(last_name__icontains=term)
                   | Q(emails__email__icontains=term) | Q(job_title__icontains=term))
    return clause


def serialize_person(p):
    return {
        "id": p.pk, "type": "person",
        "first_name": p.first_name, "last_name": p.last_name, "job_title": p.job_title,
        "favourite": p.favourite, "description": p.description,
        "owner_id": p.owner_id,
        "responsible_ids": list(p.responsibles.values_list("id", flat=True)),
        "emails": list(p.emails.values_list("email", flat=True)),
        "phones": list(p.phones.values_list("number", flat=True)),
        "addresses": list(p.addresses.values_list("address", flat=True)),
        "urls": list(p.web_links.values_list("url", flat=True)),
        "tags": list(p.tags.values_list("name", flat=True)),
        "categories": list(p.categories.values_list("name", flat=True)),
        "companies": [
            {"id": link.company_id, "name": link.company.name,
             "primary": link.is_primary, "role": link.role}
            for link in p.company_links.select_related("company").all()
        ],
        "custom_fields": _custom_fields(p),
        "created_at": p.created_at.isoformat(), "updated_at": p.updated_at.isoformat(),
        "url": p.get_absolute_url(),
    }


def serialize_company(c):
    return {
        "id": c.pk, "type": "company", "name": c.name,
        "company_code": c.company_code, "vat_code": c.vat_code,
        "address": c.address, "city": c.city, "phone": c.phone, "email": c.email,
        "description": c.description, "owner_id": c.owner_id,
        "responsible_ids": list(c.responsibles.values_list("id", flat=True)),
        "tags": list(c.tags.values_list("name", flat=True)),
        "categories": list(c.categories.values_list("name", flat=True)),
        "website": c.url,
        "custom_fields": _custom_fields(c),
        "created_at": c.created_at.isoformat(), "updated_at": c.updated_at.isoformat(),
        "url": c.get_absolute_url(),
    }


def serialize_activity(a):
    return {
        "id": a.pk, "type": "activity", "activity_type": a.activity_type, "text": a.text,
        "person_id": a.person_id, "company_id": a.company_id, "created_by_id": a.created_by_id,
        "message_id": a.message_id,
        "created_at": a.created_at.isoformat(), "updated_at": a.updated_at.isoformat(),
    }


def serialize_reminder(r):
    return {
        "id": r.pk, "type": "reminder", "text": r.text, "priority": r.priority,
        "due_at": r.due_at.isoformat() if r.due_at else None,
        "end_at": r.end_at.isoformat() if r.end_at else None,
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        "person_id": r.person_id, "company_id": r.company_id,
        "assigned_to_id": r.assigned_to_id, "created_by_id": r.created_by_id,
        "created_at": r.created_at.isoformat(),
    }


# --- write helpers -------------------------------------------------------

_MULTI_MAX = {"email": 254, "number": 80, "address": 300, "url": 200}


def _sync_multi(record, accessor, model, field, values):
    getattr(record, accessor).all().delete()
    seen = set()
    for raw in (values or [])[:50]:
        value = (str(raw) or "").strip()[:_MULTI_MAX.get(field, 200)]
        if not value or value.lower() in seen:
            continue
        seen.add(value.lower())
        model.objects.create(person=record, **{field: value},
                             **({"is_primary": len(seen) == 1} if field in ("email", "number") else {}))


def _sync_labels(manager, model, names):
    manager.clear()
    for name in (names or [])[:3]:
        name = (str(name) or "").strip()[:60]
        if name:
            manager.add(model.objects.get_or_create(name=name)[0])


_PERSON_MAX = {"first_name": 100, "last_name": 100, "job_title": 160}
_COMPANY_MAX = {"name": 200, "company_code": 40, "vat_code": 40, "address": 300, "city": 120, "phone": 80, "email": 254}


def _write_person(person, data, token, *, creating):
    for field, cap in _PERSON_MAX.items():
        if field in data:
            setattr(person, field, str(data[field] or "").strip()[:cap])
    if "description" in data:
        person.description = str(data["description"] or "")[:5000]
    if "favourite" in data:
        person.favourite = bool(data["favourite"])
    if "owner_id" in data:
        person.owner = _assignable_user(token.created_by, data["owner_id"])
    if creating:
        person.created_by = token.created_by
    person.save()
    if "emails" in data:
        _sync_multi(person, "emails", EmailAddress, "email", data["emails"])
    if "phones" in data:
        _sync_multi(person, "phones", PhoneNumber, "number", data["phones"])
    if "addresses" in data:
        _sync_multi(person, "addresses", PostalAddress, "address", data["addresses"])
    if "urls" in data:
        _sync_multi(person, "web_links", WebLink, "url", [safe_url(u) for u in data["urls"] or []])
    if "tags" in data:
        _sync_labels(person.tags, Tag, data["tags"])
    if "categories" in data:
        _sync_labels(person.categories, Category, data["categories"])
    if data.get("company_id"):
        company = visible_companies(token.created_by, Company.objects.filter(pk=data["company_id"], deleted_at__isnull=True)).first()
        if company and not person.company_links.filter(company=company).exists():
            PersonCompanyLink.objects.create(
                person=person, company=company,
                is_primary=not person.company_links.filter(is_primary=True).exists())
    return person


def _write_company(company, data, token, *, creating):
    for field, cap in _COMPANY_MAX.items():
        if field in data:
            setattr(company, field, str(data[field] or "").strip()[:cap])
    if "website" in data:
        company.url = safe_url(str(data["website"] or ""))
    if "description" in data:
        company.description = str(data["description"] or "")[:5000]
    if "owner_id" in data:
        company.owner = _assignable_user(token.created_by, data["owner_id"])
    if creating:
        company.created_by = token.created_by
    company.save()
    if "tags" in data:
        _sync_labels(company.tags, Tag, data["tags"])
    if "categories" in data:
        _sync_labels(company.categories, Category, data["categories"])
    return company


def _duplicate_matches(data, token):
    settings = DuplicateSettings.load()
    if not settings.enabled:
        return []
    from .duplicates import find_person_duplicates

    found = find_person_duplicates({
        "first_name": data.get("first_name", ""), "last_name": data.get("last_name", ""),
        "email": "\n".join(data.get("emails", []) or []),
        "phone": "\n".join(data.get("phones", []) or []),
        "companies": [],
    }, viewer=token.created_by)
    return [{"id": m["record"].pk, "reasons": m["reasons"], "url": m["record"].get_absolute_url()} for m in found]


def _audit(token, action, target, *, field="", new=""):
    audit_log(action, actor=token.created_by, target=target, field=field, new=new,
              detail={"via": "api", "token": token.name})


# --- endpoints ----------------------------------------------------------

@api_view
def me(request, token):
    return JsonResponse({"user_id": token.created_by_id, "username": token.created_by.username,
                         "token": token.name, "scope": token.scope})


@api_view
def contacts_collection(request, token):
    if request.method == "GET":
        qs = visible_people(token.created_by, Person.objects.filter(deleted_at__isnull=True)) \
            .select_related("owner").prefetch_related(
                "emails", "phones", "addresses", "web_links", "tags", "categories",
                "responsibles", "company_links__company", "custom_values__field")
        query = request.GET.get("q")
        if query:
            qs = qs.filter(_q_person(query)).distinct()
        since = _since(request)
        if since:
            qs = qs.filter(updated_at__gte=since)
        if request.GET.get("owner"):
            qs = qs.filter(owner_id=request.GET["owner"])
        return _list_response(request, qs.order_by("-updated_at", "id"), serialize_person)
    if request.method == "POST":
        _require_write(token)
        data = _json_body(request)
        if not (data.get("first_name") or data.get("last_name")):
            raise ApiError(400, "first_name or last_name is required")
        if request.GET.get("force") != "1":
            matches = _duplicate_matches(data, token)
            if matches:
                return JsonResponse({"error": "possible duplicates; retry with ?force=1", "matches": matches}, status=409)
        person = _write_person(Person(), data, token, creating=True)
        _audit(token, AuditLog.CREATE, person, field="API")
        return JsonResponse(serialize_person(person), status=201)
    return JsonResponse({"error": "method not allowed"}, status=405)


@api_view
def contact_item(request, token, pk):
    person = visible_people(token.created_by, Person.objects.filter(deleted_at__isnull=True)).filter(pk=pk).first()
    if person is None:
        raise ApiError(404, "not found")
    if request.method == "GET":
        return JsonResponse(serialize_person(person))
    if request.method == "PATCH":
        _require_write(token)
        _write_person(person, _json_body(request), token, creating=False)
        _audit(token, AuditLog.UPDATE, person, field="API")
        return JsonResponse(serialize_person(person))
    if request.method == "DELETE":
        _require_write(token)
        if not has_capability(token.created_by, "can_delete"):
            raise ApiError(403, "token owner cannot archive records")
        person.deleted_at = timezone.now()
        person.save(update_fields=["deleted_at", "updated_at"])
        _audit(token, AuditLog.ARCHIVE, person)
        return JsonResponse({"archived": True})
    return JsonResponse({"error": "method not allowed"}, status=405)


@api_view
def companies_collection(request, token):
    if request.method == "GET":
        qs = visible_companies(token.created_by, Company.objects.filter(deleted_at__isnull=True)) \
            .select_related("owner").prefetch_related("tags", "categories", "responsibles", "custom_values__field")
        query = request.GET.get("q")
        if query:
            qs = qs.filter(name__icontains=query)
        since = _since(request)
        if since:
            qs = qs.filter(updated_at__gte=since)
        return _list_response(request, qs.order_by("-updated_at", "id"), serialize_company)
    if request.method == "POST":
        _require_write(token)
        data = _json_body(request)
        if not data.get("name"):
            raise ApiError(400, "name is required")
        company = _write_company(Company(), data, token, creating=True)
        _audit(token, AuditLog.CREATE, company, field="API")
        return JsonResponse(serialize_company(company), status=201)
    return JsonResponse({"error": "method not allowed"}, status=405)


@api_view
def company_item(request, token, pk):
    company = visible_companies(token.created_by, Company.objects.filter(deleted_at__isnull=True)).filter(pk=pk).first()
    if company is None:
        raise ApiError(404, "not found")
    if request.method == "GET":
        return JsonResponse(serialize_company(company))
    if request.method == "PATCH":
        _require_write(token)
        _write_company(company, _json_body(request), token, creating=False)
        _audit(token, AuditLog.UPDATE, company, field="API")
        return JsonResponse(serialize_company(company))
    if request.method == "DELETE":
        _require_write(token)
        if not has_capability(token.created_by, "can_delete"):
            raise ApiError(403, "token owner cannot archive records")
        company.deleted_at = timezone.now()
        company.save(update_fields=["deleted_at", "updated_at"])
        _audit(token, AuditLog.ARCHIVE, company)
        return JsonResponse({"archived": True})
    return JsonResponse({"error": "method not allowed"}, status=405)


def _visible_record(token, data):
    """Resolve `person_id` / `company_id` from a payload to a visible record."""
    if data.get("person_id"):
        person = visible_people(token.created_by, Person.objects.filter(deleted_at__isnull=True)).filter(pk=data["person_id"]).first()
        if person is None:
            raise ApiError(404, "person not found")
        return person, None
    if data.get("company_id"):
        company = visible_companies(token.created_by, Company.objects.filter(deleted_at__isnull=True)).filter(pk=data["company_id"]).first()
        if company is None:
            raise ApiError(404, "company not found")
        return None, company
    return None, None


@api_view
def activities_collection(request, token):
    if request.method == "GET":
        qs = Activity.objects.filter(deleted_at__isnull=True).select_related("person", "company")
        person, company = _visible_record(token, request.GET)
        if person:
            qs = qs.filter(person=person)
        elif company:
            qs = qs.filter(company=company)
        else:
            qs = qs.filter(
                Q(person__in=visible_people(token.created_by, Person.objects.filter(deleted_at__isnull=True)))
                | Q(company__in=visible_companies(token.created_by, Company.objects.filter(deleted_at__isnull=True))))
        since = _since(request)
        if since:
            qs = qs.filter(created_at__gte=since)
        return _list_response(request, qs.order_by("-created_at", "id"), serialize_activity)
    if request.method == "POST":
        _require_write(token)
        data = _json_body(request)
        person, company = _visible_record(token, data)
        if not person and not company:
            raise ApiError(400, "person_id or company_id is required")
        if data.get("activity_type") not in {choice[0] for choice in Activity.TYPE_CHOICES}:
            raise ApiError(400, "invalid activity_type")
        if not (data.get("text") or "").strip():
            raise ApiError(400, "text is required")
        activity = Activity.objects.create(
            person=person, company=company, activity_type=data["activity_type"],
            text=str(data["text"])[:10000], created_by=token.created_by)
        _audit(token, AuditLog.CREATE, person or company, field="API activity", new=activity.text[:150])
        return JsonResponse(serialize_activity(activity), status=201)
    return JsonResponse({"error": "method not allowed"}, status=405)


@api_view
def reminders_collection(request, token):
    if request.method == "GET":
        qs = visible_reminders(token.created_by, Reminder.objects.filter(deleted_at__isnull=True)) \
            .select_related("person", "company", "assigned_to")
        if request.GET.get("open") == "1":
            qs = qs.filter(completed_at__isnull=True)
        return _list_response(request, qs.order_by("due_at", "id"), serialize_reminder)
    if request.method == "POST":
        _require_write(token)
        data = _json_body(request)
        person, company = _visible_record(token, data)
        due_at = parse_datetime(data.get("due_at") or "")
        if not (data.get("text") or "").strip() or due_at is None:
            raise ApiError(400, "text and a valid ISO due_at are required")
        priority = data.get("priority") if data.get("priority") in {p[0] for p in Reminder.PRIORITY_CHOICES} else Reminder.PRIORITY_NORMAL
        reminder = Reminder.objects.create(
            person=person, company=company, text=str(data["text"])[:500], due_at=due_at,
            priority=priority, created_by=token.created_by,
            assigned_to=_assignable_user(token.created_by, data.get("assigned_to_id")) or token.created_by)
        _audit(token, AuditLog.CREATE, person or company or reminder, field="API reminder", new=reminder.text[:150])
        return JsonResponse(serialize_reminder(reminder), status=201)
    return JsonResponse({"error": "method not allowed"}, status=405)
