from django.utils.translation import gettext as _, gettext_lazy as tr
import mimetypes
import os
import secrets
import uuid
import csv
from io import TextIOWrapper

from django.conf import settings
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models import Count, Max, Min, Prefetch, Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .forms import ActivityForm, CompanyForm, DuplicateSettingsForm, PersonForm, ReminderForm, SetupAdminForm, UserProfileForm
from .duplicates import all_company_duplicate_pairs, all_person_duplicate_pairs, find_company_duplicates, find_person_duplicates
from .filters import (
    active_filter_count,
    apply_company_filters,
    apply_contact_filters,
    company_filter_values,
    contact_filter_values,
    filter_chips,
    saved_filter_payload,
)
from .models import Activity, Attachment, Category, Company, DuplicateSettings, EmailAddress, Person, PersonCompanyLink, PhoneNumber, PostalAddress, Reminder, SavedFilter, Tag, UserProfile, WebLink


def _elided_page_numbers(page):
    """A compact page list for the paginator: ints, with "…" where pages are skipped."""
    raw = page.paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1)
    return [number if isinstance(number, int) else "…" for number in raw]


def _last_activity_context(last_activity):
    days = None
    if last_activity:
        days = (timezone.localdate() - timezone.localtime(last_activity.created_at).date()).days
    return {"last_activity": last_activity, "last_activity_days": days}


def _search_results(query, per_group):
    """Grouped global-search results. `per_group` caps each list; counts are full."""
    data = QueryDict(mutable=True)
    data["q"] = query
    terms = query.split()
    text_match = Q()
    for term in terms:
        text_match &= Q(text__icontains=term)

    people = apply_contact_filters(
        Person.objects.filter(deleted_at__isnull=True).prefetch_related("emails", "company_links__company"),
        contact_filter_values(data),
    ).order_by("last_name", "first_name")
    companies = apply_company_filters(
        Company.objects.filter(deleted_at__isnull=True).prefetch_related("people"),
        company_filter_values(data),
    ).order_by("name")
    activities = (
        Activity.objects.filter(deleted_at__isnull=True).filter(text_match)
        .exclude(person__isnull=False, person__deleted_at__isnull=False)
        .exclude(company__isnull=False, company__deleted_at__isnull=False)
        .select_related("person", "company").order_by("-created_at")
    )
    reminders = (
        Reminder.objects.filter(deleted_at__isnull=True, person__deleted_at__isnull=True).filter(text_match)
        .select_related("person").order_by("due_at")
    )
    return {
        "q": query,
        "people": people[:per_group], "people_count": people.count(),
        "companies": companies[:per_group], "companies_count": companies.count(),
        "activities": activities[:per_group], "activities_count": activities.count(),
        "reminders": reminders[:per_group], "reminders_count": reminders.count(),
    }


@login_required
def global_search(request):
    query = request.GET.get("q", "").strip()
    results = _search_results(query, 50) if len(query) >= 2 else None
    return render(request, "search.html", {"query": query, "results": results})


@login_required
def search_suggest(request):
    query = request.GET.get("q", "").strip()
    if len(query) < 2:
        return JsonResponse({"q": query, "groups": []})
    results = _search_results(query, 5)
    search_url = f"{reverse('contacts:search')}?q={query}"
    groups = []
    if results["people_count"]:
        groups.append({"label": str(tr("Kontaktai")), "count": results["people_count"], "url": search_url, "items": [
            {"label": str(person), "sublabel": person.primary_company.name if person.primary_company else "", "url": person.get_absolute_url()}
            for person in results["people"]
        ]})
    if results["companies_count"]:
        groups.append({"label": str(tr("Įmonės")), "count": results["companies_count"], "url": search_url, "items": [
            {"label": company.name, "sublabel": "", "url": company.get_absolute_url()}
            for company in results["companies"]
        ]})
    if results["activities_count"]:
        groups.append({"label": str(tr("Veiklos")), "count": results["activities_count"], "url": search_url, "items": [
            {"label": activity.text[:70], "sublabel": str(activity.person or activity.company or ""),
             "url": (activity.person or activity.company).get_absolute_url() if (activity.person or activity.company) else search_url}
            for activity in results["activities"]
        ]})
    if results["reminders_count"]:
        groups.append({"label": str(tr("Priminimai")), "count": results["reminders_count"], "url": search_url, "items": [
            {"label": reminder.text[:70], "sublabel": str(reminder.person), "url": reminder.person.get_absolute_url()}
            for reminder in results["reminders"]
        ]})
    return JsonResponse({"q": query, "groups": groups, "url": search_url})


def health_live(request):
    return JsonResponse({"status": "live"})


def health_ready(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return JsonResponse({"status": "not-ready"}, status=503)
    return JsonResponse({"status": "ready"})


def setup_admin(request):
    if get_user_model().objects.exists():
        return redirect("login")
    form = SetupAdminForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        configured_token = settings.CRM_SETUP_TOKEN
        supplied_token = form.cleaned_data["setup_token"]
        if not configured_token or not secrets.compare_digest(configured_token, supplied_token):
            form.add_error("setup_token", "Neteisingas arba neaktyvus diegimo kodas.")
        else:
            with transaction.atomic():
                user = form.save(commit=False)
                user.is_staff = True
                user.is_superuser = True
                user.save()
            return redirect("login")
    return render(request, "registration/setup.html", {"form": form})


@login_required
def contact_list(request):
    redirect_to = _default_filter_redirect(request, "contacts")
    if redirect_to:
        return redirect(redirect_to)
    filter_values = contact_filter_values(request.GET)
    query = filter_values["q"]
    page_size = 100 if request.GET.get("page_size") == "100" else 50
    sort_key = request.GET.get("sort", "name")
    direction = "desc" if request.GET.get("direction") == "desc" else "asc"
    sort_map = {"id": ["id"], "name": ["last_name", "first_name"], "company": ["sort_company"], "phone": ["sort_phone"], "email": ["sort_email"], "category": ["sort_category"], "tags": ["sort_tag"], "status": ["status"], "last_contact": ["last_contact_at"], "created": ["created_at"], "updated": ["updated_at"]}
    sort_key = sort_key if sort_key in sort_map else "name"
    order_prefix = "-" if direction == "desc" else ""
    order = [f"{order_prefix}{field}" for field in sort_map.get(sort_key, sort_map["name"])]
    people = Person.objects.filter(deleted_at__isnull=True).prefetch_related(
        "phones", "emails", "tags", "categories", Prefetch("company_links", queryset=PersonCompanyLink.objects.select_related("company"))
    )
    people = people.annotate(last_contact_at=Max("activities__created_at", filter=Q(activities__deleted_at__isnull=True)))
    people = apply_contact_filters(people, filter_values)
    people = people.annotate(
        sort_company=Min("company_links__company__name"),
        sort_phone=Min("phones__number"),
        sort_email=Min("emails__email"),
        sort_category=Min("categories__name"),
        sort_tag=Min("tags__name"),
    )
    allowed_columns = ["company", "phone", "email", "category", "tags", "status", "last_contact", "updated"]
    default_columns = ["company", "phone", "email", "category", "tags", "updated"]
    requested_columns = request.GET.getlist("columns")
    if requested_columns:
        columns = [column for column in requested_columns if column in allowed_columns]
        request.session["contacts_columns"] = columns
    else:
        columns = [column for column in request.session.get("contacts_columns", default_columns) if column in allowed_columns]
    from django.core.paginator import Paginator

    page = Paginator(people.order_by(*order, "id"), page_size).get_page(request.GET.get("page"))
    list_query = request.GET.copy()
    for key in ("page", "sort", "direction"):
        list_query.pop(key, None)
    categories = Category.objects.all()
    tags = Tag.objects.all()
    label_maps = {
        "categories": {item.pk: item.name for item in categories},
        "tags": {item.pk: item.name for item in tags},
        "titles": {"categories": tr("Kategorija"), "tags": tr("Žyma")},
    }
    return render(request, "contacts/list.html", {
        "page": page, "query": query, "page_size": page_size, "sort": sort_key,
        "page_numbers": _elided_page_numbers(page),
        "direction": direction, "columns": columns, "categories": categories,
        "tags": tags, "filter_values": filter_values,
        "active_filter_count": active_filter_count(filter_values),
        "filter_chips": filter_chips(request.GET, filter_values, label_maps, request.path),
        "saved_filters": SavedFilter.objects.filter(user=request.user, scope="contacts"),
        "list_query": list_query.urlencode(),
    })


def _bulk_add_label(request, queryset, action):
    """Add one tag or category to every record in queryset, keeping the 3-item cap."""
    if action == "add_tag":
        model, field = Tag, "tags"
        item = model.objects.filter(pk=request.POST.get("tag")).first()
        limit_msg = tr("Praleista (jau 3 žymos): %(n)s.")
    else:
        model, field = Category, "categories"
        item = model.objects.filter(pk=request.POST.get("category")).first()
        limit_msg = tr("Praleista (jau 3 kategorijos): %(n)s.")
    if not item:
        return
    added = skipped = 0
    for record in queryset:
        relation = getattr(record, field)
        if relation.filter(pk=item.pk).exists():
            continue
        if relation.count() >= 3:
            skipped += 1
            continue
        try:
            relation.add(item)
            added += 1
        except ValidationError:
            skipped += 1
    if added:
        messages.success(request, tr("Priskirta įrašams: %(n)s.") % {"n": added})
    if skipped:
        messages.error(request, limit_msg % {"n": skipped})


@login_required
def contact_bulk_action(request):
    if request.method != "POST":
        return redirect("contacts:list")
    action = request.POST.get("action")
    ids = request.POST.getlist("selected")
    if not ids:
        return redirect("contacts:list")
    people = Person.objects.filter(pk__in=ids, deleted_at__isnull=True)
    if action == "archive":
        count = people.update(deleted_at=timezone.now())
        messages.success(request, tr("Archyvuota kontaktų: %(count)s.") % {"count": count})
    elif action in {"add_tag", "add_category"}:
        _bulk_add_label(request, people, action)
    return redirect("contacts:list")


@login_required
def company_bulk_action(request):
    if request.method != "POST":
        return redirect("contacts:company-list")
    action = request.POST.get("action")
    ids = request.POST.getlist("selected")
    if not ids:
        return redirect("contacts:company-list")
    companies = Company.objects.filter(pk__in=ids, deleted_at__isnull=True)
    if action == "archive":
        count = companies.update(deleted_at=timezone.now())
        if count:
            messages.success(request, tr("Archyvuota įmonių: %(count)s.") % {"count": count})
    elif action in {"add_tag", "add_category"}:
        _bulk_add_label(request, companies, action)
    return redirect("contacts:company-list")


@login_required
def contact_archive(request, pk):
    person = get_object_or_404(Person, pk=pk)
    if request.method == "POST" and person.deleted_at is None:
        person.deleted_at = timezone.now()
        person.save(update_fields=["deleted_at", "updated_at"])
        messages.success(request, tr("Kontaktas perkeltas į archyvą."))
    return redirect("contacts:list")


@login_required
def company_archive(request, pk):
    company = get_object_or_404(Company, pk=pk)
    if request.method == "POST" and company.deleted_at is None:
        company.deleted_at = timezone.now()
        company.save(update_fields=["deleted_at", "updated_at"])
        messages.success(request, tr("Įmonė perkelta į archyvą."))
    return redirect("contacts:company-list")


@login_required
def archive_list(request):
    people = Person.objects.filter(deleted_at__isnull=False, merged_into__isnull=True).order_by("-deleted_at")
    companies = Company.objects.filter(deleted_at__isnull=False, merged_into__isnull=True).order_by("-deleted_at")
    return render(request, "archive.html", {"people": people, "companies": companies})


@login_required
def contact_restore(request, pk):
    person = get_object_or_404(Person, pk=pk, merged_into__isnull=True)
    if request.method == "POST" and person.deleted_at is not None:
        person.deleted_at = None
        person.save(update_fields=["deleted_at", "updated_at"])
        messages.success(request, tr("Kontaktas atkurtas."))
    return redirect("contacts:archive-list")


@login_required
def company_restore(request, pk):
    company = get_object_or_404(Company, pk=pk, merged_into__isnull=True)
    if request.method == "POST" and company.deleted_at is not None:
        company.deleted_at = None
        company.save(update_fields=["deleted_at", "updated_at"])
        messages.success(request, tr("Įmonė atkurta."))
    return redirect("contacts:archive-list")


def _default_filter_redirect(request, scope):
    """Apply the user's default saved filter once per session on the first
    parameter-free visit to the list. Returns a URL to redirect to, or None."""
    seen_key = f"{scope}_list_seen"
    first_visit = not request.session.get(seen_key)
    request.session[seen_key] = True
    if not first_visit or request.GET:
        return None
    default = SavedFilter.objects.filter(user=request.user, scope=scope, is_default=True).first()
    if default and default.query_string:
        return f"{request.path}?{default.query_string}"
    return None


@login_required
def saved_filter_create(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        filters = saved_filter_payload(request.POST, "contacts")
        if name:
            SavedFilter.objects.update_or_create(user=request.user, scope="contacts", name=name, defaults={"filters": filters})
            messages.success(request, tr("Filtras išsaugotas."))
    return redirect("contacts:list")


@login_required
def company_saved_filter_create(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        filters = saved_filter_payload(request.POST, "companies")
        if name:
            SavedFilter.objects.update_or_create(user=request.user, scope="companies", name=name, defaults={"filters": filters})
            messages.success(request, tr("Įmonių sąrašas išsaugotas."))
    return redirect("contacts:company-list")


@login_required
def saved_filter_update(request, pk):
    saved = get_object_or_404(SavedFilter, pk=pk, user=request.user)
    target = "contacts:company-list" if saved.scope == "companies" else "contacts:list"
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "delete":
            saved.delete()
            messages.success(request, tr("Filtras pašalintas."))
        elif action == "rename":
            name = request.POST.get("name", "").strip()
            if not name:
                messages.error(request, tr("Filtro pavadinimas negali būti tuščias."))
            elif SavedFilter.objects.filter(user=request.user, scope=saved.scope, name=name).exclude(pk=saved.pk).exists():
                messages.error(request, tr("Toks filtro pavadinimas jau yra."))
            else:
                saved.name = name
                saved.save(update_fields=["name"])
                messages.success(request, tr("Filtras pervadintas."))
        elif action == "default":
            make_default = not saved.is_default
            SavedFilter.objects.filter(user=request.user, scope=saved.scope).exclude(pk=saved.pk).update(is_default=False)
            SavedFilter.objects.filter(pk=saved.pk).update(is_default=make_default)
            messages.success(request, tr("Numatytasis filtras nustatytas.") if make_default else tr("Numatytasis filtras išjungtas."))
    return redirect(target)


@login_required
def settings_page(request):
    if request.method == "POST" and request.POST.get("kind") in {"tag", "category"}:
        return settings_taxonomy(request, request.POST["kind"])
    form = UserProfileForm(request.POST or None, request.FILES or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        profile = form.save()
        messages.success(request, tr("Profilis atnaujintas."))
        response = redirect("contacts:settings")
        response.set_cookie(settings.LANGUAGE_COOKIE_NAME, profile.language, max_age=365 * 24 * 60 * 60, samesite="Lax")
        return response
    return render(request, "settings/profile.html", {"form": form, "settings_section": "profile"})


@login_required
def settings_password(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        update_session_auth_hash(request, form.user)
        messages.success(request, tr("Slaptažodis pakeistas."))
        return redirect("contacts:settings-password")
    return render(request, "settings/password.html", {"form": form, "settings_section": "password"})


_EXPORT_README = (
    "CRM duomenų eksportas / CRM data export\n"
    "======================================\n\n"
    "data.json  - visų CRM duomenų kopija (Django dumpdata).\n"
    "media/     - įrašų priedai ir profilių nuotraukos.\n\n"
    "Atkūrimas / restore:\n"
    "  1. python manage.py migrate\n"
    "  2. python manage.py loaddata data.json\n"
    "  3. media/ turinį nukopijuoti į runtime/media/\n"
)


@login_required
def settings_data_export(request):
    if not request.user.is_staff:
        raise Http404
    if request.method == "POST":
        import io
        import zipfile
        from django.core.management import call_command

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            dump = io.StringIO()
            call_command(
                "dumpdata", "auth.Group", "auth.User", "contacts",
                natural_foreign=True, natural_primary=True, indent=2, stdout=dump,
            )
            archive.writestr("data.json", dump.getvalue())
            archive.writestr("README.txt", _EXPORT_README)
            media_root = str(settings.MEDIA_ROOT)
            if os.path.isdir(media_root):
                for folder, _subdirs, names in os.walk(media_root):
                    for name in names:
                        full = os.path.join(folder, name)
                        archive.write(full, os.path.join("media", os.path.relpath(full, media_root)))
        response = HttpResponse(buffer.getvalue(), content_type="application/zip")
        response["Content-Disposition"] = 'attachment; filename="crm-eksportas-%s.zip"' % timezone.now().strftime("%Y%m%d-%H%M")
        return response
    return render(request, "settings/data_export.html", {"settings_section": "data-export"})


@login_required
def profile_avatar(request):
    profile = UserProfile.objects.filter(user=request.user).first()
    if not profile or not profile.avatar:
        raise Http404
    try:
        response = FileResponse(
            profile.avatar.open("rb"),
            content_type=mimetypes.guess_type(profile.avatar.name)[0] or "application/octet-stream",
        )
    except FileNotFoundError:
        raise Http404("Profilio nuotrauka nerasta.")
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
def settings_taxonomy(request, kind):
    model = Tag if kind == "tag" else Category if kind == "category" else None
    if not model:
        raise Http404
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        item_id = request.POST.get("item_id", "").strip()
        if not name:
            messages.error(request, tr("Žyma negali būti tuščia.") if kind == "tag" else tr("Kategorija negali būti tuščia."))
        elif model.objects.filter(name__iexact=name).exclude(pk=item_id or None).exists():
            messages.error(request, tr("Tokia žyma jau yra.") if kind == "tag" else tr("Tokia kategorija jau yra."))
        elif item_id:
            item = get_object_or_404(model, pk=item_id)
            item.name = name
            update_fields = ["name"]
            if kind == "tag":
                color = request.POST.get("color", "")
                if color and color not in dict(Tag.COLOR_CHOICES):
                    messages.error(request, tr("Pasirinkta netinkama žymos spalva."))
                    return redirect("contacts:settings-tags")
                item.color = color
                update_fields.append("color")
            item.save(update_fields=update_fields)
            messages.success(request, tr("Žyma atnaujinta.") if kind == "tag" else tr("Kategorija atnaujinta."))
        else:
            item = model.objects.create(name=name)
            if kind == "tag" and request.POST.get("color") in dict(Tag.COLOR_CHOICES):
                item.color = request.POST["color"]
                item.save(update_fields=["color"])
            messages.success(request, tr("Žyma pridėta.") if kind == "tag" else tr("Kategorija pridėta."))
        return redirect("contacts:settings-tags" if kind == "tag" else "contacts:settings-categories")
    items = model.objects.annotate(people_count=Count("people", distinct=True), companies_count=Count("companies", distinct=True))
    return render(request, "settings/taxonomy.html", {"items": items, "kind": kind, "tag_colors": Tag.COLOR_CHOICES, "settings_section": "tags" if kind == "tag" else "categories"})


@login_required
def settings_duplicates(request):
    duplicate_settings = DuplicateSettings.load()
    form = DuplicateSettingsForm(request.POST or None, instance=duplicate_settings)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, tr("Dublikatų tikrinimo nustatymai išsaugoti."))
        return redirect("contacts:settings-duplicates")
    return render(request, "settings/duplicates.html", {"form": form, "settings_section": "duplicates"})


@login_required
def documentation_page(request):
    topics = (
        ("overview", tr("Pradžia")),
        ("installation", tr("Diegimas")),
        ("screens", tr("Langai ir mygtukai")),
        ("user", tr("Naudotojui")),
        ("admin", tr("Administratoriui")),
        ("data", tr("Duomenys ir sauga")),
        ("backup", tr("Kopijos ir atkūrimas")),
    )
    allowed_topics = {key for key, _label in topics}
    topic = request.GET.get("topic", "overview")
    if topic not in allowed_topics:
        topic = "overview"
    return render(request, "settings/documentation.html", {
        "settings_section": "documentation",
        "documentation_topic": topic,
        "documentation_topics": topics,
    })


@login_required
def duplicate_list(request):
    duplicate_settings = DuplicateSettings.load()
    pairs = (all_person_duplicate_pairs(duplicate_settings.level) + all_company_duplicate_pairs(duplicate_settings.level)) if duplicate_settings.enabled else []
    return render(request, "duplicates/list.html", {"pairs": pairs, "duplicate_settings": duplicate_settings})


@login_required
def duplicate_merge(request, kind, source_pk, target_pk):
    if request.method != "POST":
        return HttpResponse(status=405)
    if kind not in {"person", "company"} or source_pk == target_pk:
        return HttpResponse("Netinkami sujungimo duomenys.", status=400)
    duplicate_settings = DuplicateSettings.load()
    if not duplicate_settings.enabled:
        return HttpResponse("Dublikatų tikrinimas išjungtas.", status=400)

    model = Person if kind == "person" else Company
    source = model.objects.filter(pk=source_pk).first()
    target = model.objects.filter(pk=target_pk).first()
    if not source or not target:
        return HttpResponse("Vienas iš sujungiamų įrašų nerastas.", status=404)
    if source.merged_into_id == target.pk:
        return redirect(target.get_absolute_url())

    pair_function = all_person_duplicate_pairs if kind == "person" else all_company_duplicate_pairs
    is_duplicate_pair = any(
        {pair["left"].pk, pair["right"].pk} == {source_pk, target_pk}
        for pair in pair_function(duplicate_settings.level)
    )
    if not is_duplicate_pair:
        return HttpResponse("Pasirinkti įrašai pagal dabartines taisykles nėra dublikatai.", status=400)

    from .merging import merge_companies, merge_people
    try:
        target = merge_people(source_pk, target_pk) if kind == "person" else merge_companies(source_pk, target_pk)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
        return redirect("contacts:duplicate-list")
    messages.success(request, _("Įrašai sėkmingai sujungti."))
    return redirect(target.get_absolute_url())


@login_required
def contact_detail(request, pk):
    from .detail_editing import detail_fields
    person = get_object_or_404(Person.objects.prefetch_related("phones", "emails", "addresses", "web_links", "tags", "categories", "activities__created_by", "activities__attachments", "reminders", "company_links__company"), pk=pk, deleted_at__isnull=True)
    now = timezone.now()
    open_reminders = person.reminders.filter(completed_at__isnull=True, deleted_at__isnull=True)
    return render(request, "contacts/detail.html", {
        "person": person,
        "detail_fields": detail_fields(person),
        "tags": Tag.objects.all(), "categories": Category.objects.all(),
        "activity_form": ActivityForm(),
        "reminder_form": ReminderForm(),
        "activity_token": uuid.uuid4().hex,
        "reminder_token": uuid.uuid4().hex,
        "active_reminders": open_reminders,
        "next_reminder": open_reminders.filter(due_at__gt=now).order_by("due_at").first(),
        "overdue_reminder_count": open_reminders.filter(due_at__lte=now).count(),
        **_last_activity_context(person.activities.filter(deleted_at__isnull=True).order_by("-created_at").first()),
    })


@login_required
def contact_type_choice(request):
    return render(request, "contacts/type_choice.html")


@login_required
def contact_create(request):
    form = PersonForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        duplicate_settings = DuplicateSettings.load()
        duplicates = find_person_duplicates(form.cleaned_data, level=duplicate_settings.level) if duplicate_settings.enabled else []
        if duplicates and request.POST.get("confirm_duplicate") != "1":
            return render(request, "contacts/form.html", {"form": form, "title": tr("Pridėti asmenį"), "duplicate_candidates": duplicates})
        return redirect(form.save())
    return render(request, "contacts/form.html", {"form": form, "title": tr("Pridėti asmenį")})


@login_required
def contact_edit(request, pk):
    person = get_object_or_404(Person, pk=pk, deleted_at__isnull=True)
    initial = {
        "companies": person.companies.all(),
        "phone": "\n".join(person.phones.values_list("number", flat=True)),
        "email": "\n".join(person.emails.values_list("email", flat=True)),
        "address": "\n".join(person.addresses.values_list("address", flat=True)),
        "url": "\n".join(person.web_links.values_list("url", flat=True)),
    }
    form = PersonForm(request.POST or None, instance=person, initial=initial)
    if request.method == "POST" and form.is_valid():
        duplicate_settings = DuplicateSettings.load()
        duplicates = find_person_duplicates(form.cleaned_data, exclude_pk=person.pk, level=duplicate_settings.level) if duplicate_settings.enabled and duplicate_settings.check_on_edit else []
        if duplicates and request.POST.get("confirm_duplicate") != "1":
            return render(request, "contacts/form.html", {"form": form, "title": tr("Redaguoti kontaktą"), "person": person, "duplicate_candidates": duplicates})
        return redirect(form.save())
    return render(request, "contacts/form.html", {"form": form, "title": tr("Redaguoti kontaktą"), "person": person})


ATTACHMENT_MAX_BYTES = 10 * 1024 * 1024
ATTACHMENT_ALLOWED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".pdf", ".txt",
    ".doc", ".docx", ".xls", ".xlsx",
}


def _save_attachments(request, activity):
    """Store the uploaded files that pass the size and extension limits.
    Returns the names of any rejected files."""
    rejected = []
    for upload in request.FILES.getlist("attachments"):
        extension = os.path.splitext(upload.name)[1].lower()
        if upload.size > ATTACHMENT_MAX_BYTES or extension not in ATTACHMENT_ALLOWED_EXTENSIONS:
            rejected.append(upload.name)
            continue
        Attachment.objects.create(
            activity=activity, file=upload, original_name=upload.name[:255],
            content_type=getattr(upload, "content_type", "") or "", size=upload.size,
        )
    return rejected


def _report_rejected_attachments(request, rejected):
    if rejected:
        messages.error(request, tr("Nepridėti failai (per dideli arba netinkamo tipo): %(names)s") % {"names": ", ".join(rejected)})


@login_required
def activity_create(request, pk):
    person = get_object_or_404(Person, pk=pk, deleted_at__isnull=True)
    form = ActivityForm(request.POST)
    if form.is_valid():
        token = request.POST.get("submission_token", "")
        if token and person.activities.filter(submission_token=token).exists():
            return redirect(person)
        activity = form.save(commit=False)
        activity.person = person
        activity.created_by = request.user
        activity.submission_token = token or None
        activity.save()
        _report_rejected_attachments(request, _save_attachments(request, activity))
    return redirect(person)


@login_required
def activity_edit(request, person_pk, pk):
    person = get_object_or_404(Person, pk=person_pk, deleted_at__isnull=True)
    activity = get_object_or_404(person.activities, pk=pk, deleted_at__isnull=True)
    form = ActivityForm(request.POST or None, instance=activity)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, tr("Įrašas atnaujintas."))
        return redirect(person)
    return render(request, "contacts/activity_form.html", {"form": form, "person": person, "activity": activity})


@login_required
def reminder_create(request, pk):
    person = get_object_or_404(Person, pk=pk, deleted_at__isnull=True)
    form = ReminderForm(request.POST)
    if form.is_valid():
        token = request.POST.get("submission_token", "")
        if token and person.reminders.filter(submission_token=token).exists():
            return redirect(person)
        reminder = form.save(commit=False)
        reminder.person = person
        reminder.created_by = request.user
        reminder.submission_token = token or None
        reminder.save()
    return redirect(person)


@login_required
def reminder_complete(request, pk):
    reminder = get_object_or_404(Reminder, pk=pk, deleted_at__isnull=True)
    if request.method == "POST":
        now = timezone.now()
        Reminder.objects.filter(pk=reminder.pk, deleted_at__isnull=True, completed_at__isnull=True).update(
            completed_at=now, updated_at=now,
        )
    return redirect(reminder.person)


@login_required
def reminder_edit(request, pk):
    reminder = get_object_or_404(Reminder, pk=pk, deleted_at__isnull=True)
    original_due_at = reminder.due_at
    form = ReminderForm(request.POST or None, instance=reminder)
    if request.method == "POST" and form.is_valid():
        if form.cleaned_data["due_at"] != original_due_at:
            form.instance.read_at = None
        form.save()
        messages.success(request, tr("Priminimas atnaujintas."))
        return redirect("contacts:reminder-list")
    return render(request, "reminders/form.html", {"form": form, "reminder": reminder})


@login_required
def reminder_delete(request, pk):
    reminder = get_object_or_404(Reminder, pk=pk, deleted_at__isnull=True)
    if request.method == "POST":
        reminder.deleted_at = timezone.now()
        reminder.save(update_fields=["deleted_at", "updated_at"])
        messages.success(request, tr("Priminimas pašalintas."))
    return redirect("contacts:reminder-list")


@login_required
def reminder_list(request):
    from .reminder_queries import pending_reminders
    now = timezone.now()
    active = pending_reminders().filter(due_at__lte=now)
    scheduled = pending_reminders().filter(due_at__gt=now)
    active.filter(read_at__isnull=True).update(read_at=now)
    return render(request, "reminders/list.html", {"active_reminders": active, "scheduled_reminders": scheduled})


@login_required
def attachment_download(request, pk):
    available = Attachment.objects.filter(deleted_at__isnull=True, activity__deleted_at__isnull=True).filter(
        Q(activity__person__isnull=False, activity__person__deleted_at__isnull=True)
        | Q(activity__company__isnull=False, activity__company__deleted_at__isnull=True)
    )
    attachment = get_object_or_404(available, pk=pk)
    if not attachment.file:
        raise Http404
    try:
        return FileResponse(attachment.file.open("rb"), as_attachment=True, filename=attachment.original_name)
    except FileNotFoundError:
        raise Http404("Failas nerastas.")


@login_required
def company_list(request):
    redirect_to = _default_filter_redirect(request, "companies")
    if redirect_to:
        return redirect(redirect_to)
    companies = Company.objects.filter(deleted_at__isnull=True).prefetch_related("people", "tags", "categories")
    filter_values = company_filter_values(request.GET)
    query = filter_values["q"]
    page_size = 100 if request.GET.get("page_size") == "100" else 50
    sort_key = request.GET.get("sort", "name")
    direction = "desc" if request.GET.get("direction") == "desc" else "asc"
    companies = apply_company_filters(companies, filter_values)
    sort_map = {
        "id": "id",
        "name": "name",
        "company_code": "company_code",
        "vat_code": "vat_code",
        "phone": "phone",
        "email": "email",
        "address": "address",
        "contacts": "contact_count",
        "category": "sort_category",
        "tags": "sort_tag",
    }
    sort_key = sort_key if sort_key in sort_map else "name"
    order_prefix = "-" if direction == "desc" else ""
    companies = companies.distinct().annotate(
        contact_count=Count("people", distinct=True),
        sort_category=Min("categories__name"),
        sort_tag=Min("tags__name"),
    ).order_by(f"{order_prefix}{sort_map[sort_key]}", "id")
    allowed_columns = ("company_code", "vat_code", "address", "phone", "email", "contacts")
    default_columns = ["company_code", "vat_code", "phone", "email", "contacts"]
    requested_columns = request.GET.getlist("columns")
    if requested_columns:
        columns = [column for column in requested_columns if column in allowed_columns]
        request.session["companies_columns"] = columns
    else:
        columns = request.session.get("companies_columns", default_columns)
        columns = [column for column in columns if column in allowed_columns]
    from django.core.paginator import Paginator

    page = Paginator(companies, page_size).get_page(request.GET.get("page"))
    list_query = request.GET.copy()
    for key in ("page", "sort", "direction"):
        list_query.pop(key, None)
    categories = Category.objects.all()
    tags = Tag.objects.all()
    label_maps = {
        "categories": {item.pk: item.name for item in categories},
        "tags": {item.pk: item.name for item in tags},
        "titles": {"categories": tr("Kategorija"), "tags": tr("Žyma")},
    }
    return render(request, "companies/list.html", {
        "page": page, "query": query, "page_size": page_size, "sort": sort_key, "direction": direction, "filter_values": filter_values, "columns": columns,
        "page_numbers": _elided_page_numbers(page),
        "list_query": list_query.urlencode(),
        "active_filter_count": active_filter_count(filter_values),
        "filter_chips": filter_chips(request.GET, filter_values, label_maps, request.path),
        "saved_filters": SavedFilter.objects.filter(user=request.user, scope="companies"),
        "tags": tags, "categories": categories,
    })


@login_required
def company_detail(request, pk):
    from .detail_editing import company_detail_fields
    company = get_object_or_404(Company.objects.prefetch_related("person_links__person"), pk=pk, deleted_at__isnull=True)
    history = Activity.objects.filter(deleted_at__isnull=True).filter(
        Q(company=company) | Q(person__company_links__company=company)
    ).select_related("person", "company", "created_by").prefetch_related("attachments").distinct().order_by("-created_at")
    now = timezone.now()
    linked_reminders = Reminder.objects.filter(
        person__company_links__company=company, person__deleted_at__isnull=True,
        completed_at__isnull=True, deleted_at__isnull=True,
    )
    next_reminder = linked_reminders.filter(due_at__gt=now).select_related("person").order_by("due_at").first()
    return render(request, "companies/detail.html", {
        "company": company, "detail_fields": company_detail_fields(company),
        "tags": Tag.objects.all(), "categories": Category.objects.all(),
        "history": history, "activity_form": ActivityForm(), "activity_token": uuid.uuid4().hex,
        "next_reminder": next_reminder,
        "next_reminder_person": next_reminder.person if next_reminder else None,
        "overdue_reminder_count": linked_reminders.filter(due_at__lte=now).count(),
        **_last_activity_context(history.first()),
    })


@login_required
def company_activity_edit(request, company_pk, pk):
    company = get_object_or_404(Company, pk=company_pk, deleted_at__isnull=True)
    activity = get_object_or_404(company.activities, pk=pk, deleted_at__isnull=True)
    form = ActivityForm(request.POST or None, instance=activity)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, tr("Įrašas atnaujintas."))
        return redirect(company)
    return render(request, "contacts/activity_form.html", {"form": form, "person": company, "activity": activity})


@login_required
def company_activity_create(request, pk):
    company = get_object_or_404(Company, pk=pk, deleted_at__isnull=True)
    form = ActivityForm(request.POST)
    if form.is_valid():
        token = request.POST.get("submission_token", "")
        if token and company.activities.filter(submission_token=token).exists():
            return redirect(company)
        activity = form.save(commit=False)
        activity.company = company
        activity.created_by = request.user
        activity.submission_token = token or None
        activity.save()
        _report_rejected_attachments(request, _save_attachments(request, activity))
    return redirect(company)


@login_required
def company_create(request):
    form = CompanyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        duplicate_settings = DuplicateSettings.load()
        duplicates = find_company_duplicates(form.cleaned_data, level=duplicate_settings.level) if duplicate_settings.enabled else []
        if duplicates and request.POST.get("confirm_duplicate") != "1":
            return render(request, "contacts/form.html", {"form": form, "title": tr("Pridėti įmonę"), "cancel_url": "/companies/", "duplicate_candidates": duplicates})
        return redirect(form.save())
    return render(request, "contacts/form.html", {"form": form, "title": tr("Pridėti įmonę"), "cancel_url": "/companies/"})


@login_required
def company_edit(request, pk):
    company = get_object_or_404(Company, pk=pk, deleted_at__isnull=True)
    form = CompanyForm(request.POST or None, instance=company)
    if request.method == "POST" and form.is_valid():
        duplicate_settings = DuplicateSettings.load()
        duplicates = find_company_duplicates(form.cleaned_data, exclude_pk=company.pk, level=duplicate_settings.level) if duplicate_settings.enabled and duplicate_settings.check_on_edit else []
        if duplicates and request.POST.get("confirm_duplicate") != "1":
            return render(request, "contacts/form.html", {"form": form, "title": tr("Redaguoti įmonę"), "company": company, "cancel_url": company.get_absolute_url(), "duplicate_candidates": duplicates})
        return redirect(form.save())
    return render(request, "contacts/form.html", {"form": form, "title": tr("Redaguoti įmonę"), "company": company, "cancel_url": company.get_absolute_url()})


def _value(row, *names):
    for name in names:
        value = row.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _import_relation_names(row, *names):
    values = []
    for value in _value(row, *names).split(";"):
        value = value.strip()
        if value and value not in values:
            values.append(value)
    return values


@login_required
def contacts_export(request):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="crm-kontaktai.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(["Vardas", "Pavardė", "Pareigos", "Įmonė", "Telefonai", "El. paštai", "Adresai", "URL", "Būsena", "Tagai", "Kategorijos"])
    people = Person.objects.filter(deleted_at__isnull=True)
    if request.method == "POST":
        people = people.filter(pk__in=request.POST.getlist("selected"))
    people = people.prefetch_related("phones", "emails", "addresses", "web_links", "tags", "categories", "company_links__company")
    for person in people:
        writer.writerow([person.first_name, person.last_name, person.job_title, "; ".join(link.company.name for link in person.company_links.all()), "; ".join(item.number for item in person.phones.all()), "; ".join(item.email for item in person.emails.all()), "; ".join(item.address for item in person.addresses.all()), "; ".join(item.url for item in person.web_links.all()), person.status, "; ".join(item.name for item in person.tags.all()), "; ".join(item.name for item in person.categories.all())])
    return response

@login_required
def companies_export(request):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="crm-imones.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(["Pavadinimas", "Įmonės kodas", "PVM kodas", "Adresas", "Telefonas", "El. paštas"])
    companies = Company.objects.filter(deleted_at__isnull=True)
    if request.method == "POST": companies = companies.filter(pk__in=request.POST.getlist("selected"))
    for company in companies: writer.writerow([company.name, company.company_code, company.vat_code, company.address, company.phone, company.email])
    return response


@transaction.atomic
def _import_contact_rows(rows):
    created = updated = skipped = possible_duplicates = 0
    created_person_ids = set()
    duplicate_settings = DuplicateSettings.load()
    report_duplicates = duplicate_settings.enabled and duplicate_settings.check_on_import
    for row in rows:
        first_name = _value(row, "Vardas", "first_name", "First name")
        last_name = _value(row, "Pavardė", "last_name", "Last name")
        company_names = _import_relation_names(row, "Įmonė", "company", "Company")
        phone_values = list(filter(None, (item.strip() for item in _value(row, "Telefonai", "Telefonas", "phone", "Phone").split(";"))))
        email_values = list(filter(None, (item.strip() for item in _value(row, "El. paštai", "El. paštas", "email", "Email").split(";"))))
        email = email_values[0] if email_values else ""
        if not first_name and not last_name:
            skipped += 1
            continue
        person = None
        if email:
            person = Person.objects.filter(emails__email__iexact=email, deleted_at__isnull=True).first()
        if not person:
            person = Person.objects.filter(first_name__iexact=first_name, last_name__iexact=last_name, deleted_at__isnull=True).first()
        values = {"first_name": first_name, "last_name": last_name, "job_title": _value(row, "Pareigos", "job_title"), "status": _value(row, "Būsena", "status") or "Aktyvus"}
        if person:
            for field, value in values.items():
                if value:
                    setattr(person, field, value)
            person.save()
            updated += 1
        else:
            person = Person.objects.create(**values)
            created += 1
            created_person_ids.add(person.pk)
        for company_name in company_names:
            company, _ = Company.objects.get_or_create(name=company_name)
            PersonCompanyLink.objects.get_or_create(
                person=person, company=company,
                defaults={"is_primary": not person.company_links.filter(is_primary=True).exists()},
            )
        for number in phone_values:
            PhoneNumber.objects.get_or_create(person=person, number=number, defaults={"is_primary": not person.phones.exists()})
        for address in filter(None, (item.strip() for item in _value(row, "Adresai", "Adresas", "address", "Address").split(";"))):
            PostalAddress.objects.get_or_create(person=person, address=address)
        for url in filter(None, (item.strip() for item in _value(row, "URL", "url", "Website").split(";"))):
            WebLink.objects.get_or_create(person=person, url=url)
        for address in email_values:
            EmailAddress.objects.get_or_create(person=person, email=address, defaults={"is_primary": not person.emails.exists()})
        tag_names = _import_relation_names(row, "Tagai", "Tags", "tags")
        category_names = _import_relation_names(row, "Kategorijos", "Categories", "categories")
        if len(tag_names) > 3 or len(category_names) > 3:
            raise ValueError(tr("Viršytas leistinas žymų arba kategorijų skaičius"))
        for tag_name in tag_names:
            tag, _ = Tag.objects.get_or_create(name=tag_name[:60])
            person.tags.add(tag)
        for category_name in category_names:
            category, _ = Category.objects.get_or_create(name=category_name[:60])
            person.categories.add(category)
    if report_duplicates and created_person_ids:
        possible_duplicates = sum(
            1 for pair in all_person_duplicate_pairs(duplicate_settings.level)
            if pair["left"].pk in created_person_ids or pair["right"].pk in created_person_ids
        )
    return {"created": created, "updated": updated, "skipped": skipped, "possible_duplicates": possible_duplicates, "duplicate_check_enabled": report_duplicates}


IMPORT_PREVIEW_LIMIT = 5000


def _read_import_rows(upload):
    name = upload.name.lower()
    if name.endswith(".csv"):
        raw = list(csv.DictReader(TextIOWrapper(upload.file, encoding="utf-8-sig")))
    elif name.endswith(".xlsx"):
        from openpyxl import load_workbook

        sheet = load_workbook(upload, read_only=True, data_only=True).active
        headers = [str(cell.value or "").strip() for cell in next(sheet.iter_rows())]
        raw = [{headers[index]: cell.value for index, cell in enumerate(row)} for row in sheet.iter_rows(min_row=2)]
    else:
        raise ValueError(tr("Netinkamas failo formatas"))
    # Normalise every value to a string so the rows are JSON/session safe.
    return [{str(key): ("" if value is None else str(value)) for key, value in row.items() if key} for row in raw]


def _import_preview(rows):
    created = updated = skipped = 0
    for row in rows:
        first_name = _value(row, "Vardas", "first_name", "First name")
        last_name = _value(row, "Pavardė", "last_name", "Last name")
        emails = list(filter(None, (item.strip() for item in _value(row, "El. paštai", "El. paštas", "email", "Email").split(";"))))
        if not first_name and not last_name:
            skipped += 1
            continue
        match = (emails and Person.objects.filter(emails__email__iexact=emails[0], deleted_at__isnull=True).exists()) or \
            Person.objects.filter(first_name__iexact=first_name, last_name__iexact=last_name, deleted_at__isnull=True).exists()
        if match:
            updated += 1
        else:
            created += 1
    headers = list(rows[0].keys()) if rows else []
    return {"total": len(rows), "created": created, "updated": updated, "skipped": skipped,
            "headers": headers, "sample": [[row.get(header, "") for header in headers] for row in rows[:8]]}


@login_required
def contacts_import(request):
    context = {}
    if request.method == "POST" and request.POST.get("confirm") == "1":
        rows = request.session.pop("import_rows", None)
        if not rows:
            messages.error(request, tr("Importo peržiūra pasibaigė. Įkelkite failą iš naujo."))
        else:
            try:
                context["result"] = _import_contact_rows(rows)
            except Exception:
                messages.error(request, tr("Nepavyko importuoti. Patikrinkite žymų ir kategorijų skaičių bei stulpelius."))
    elif request.method == "POST":
        upload = request.FILES.get("file")
        if not upload or upload.size > 10 * 1024 * 1024:
            messages.error(request, tr("Pasirinkite iki 10 MB dydžio CSV arba XLSX failą."))
        else:
            try:
                rows = _read_import_rows(upload)
            except Exception:
                rows = None
                messages.error(request, tr("Nepavyko perskaityti failo. Patikrinkite stulpelius ir failo formatą."))
            if rows is not None and len(rows) > IMPORT_PREVIEW_LIMIT:
                messages.error(request, tr("Peržiūrai skirtas failas su ne daugiau kaip %(n)s eilučių.") % {"n": IMPORT_PREVIEW_LIMIT})
            elif rows:
                request.session["import_rows"] = rows
                context["preview"] = _import_preview(rows)
            elif rows is not None:
                messages.error(request, tr("Faile nerasta įrašų."))
    else:
        request.session.pop("import_rows", None)
    return render(request, "import_export.html", context)
