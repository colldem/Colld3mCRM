from django.utils.translation import gettext_lazy as tr
import mimetypes
import secrets
import uuid
import csv
from io import TextIOWrapper

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import connection, transaction
from django.db.models import Count, Min, Prefetch, Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
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
    filter_values = contact_filter_values(request.GET)
    query = filter_values["q"]
    page_size = 100 if request.GET.get("page_size") == "100" else 50
    sort_key = request.GET.get("sort", "name")
    direction = "desc" if request.GET.get("direction") == "desc" else "asc"
    sort_map = {"id": ["id"], "name": ["last_name", "first_name"], "company": ["sort_company"], "phone": ["sort_phone"], "email": ["sort_email"], "category": ["sort_category"], "tags": ["sort_tag"], "status": ["status"], "created": ["created_at"], "updated": ["updated_at"]}
    sort_key = sort_key if sort_key in sort_map else "name"
    order_prefix = "-" if direction == "desc" else ""
    order = [f"{order_prefix}{field}" for field in sort_map.get(sort_key, sort_map["name"])]
    people = Person.objects.filter(deleted_at__isnull=True).prefetch_related(
        "phones", "emails", "tags", "categories", Prefetch("company_links", queryset=PersonCompanyLink.objects.select_related("company"))
    )
    people = apply_contact_filters(people, filter_values)
    people = people.annotate(
        sort_company=Min("company_links__company__name"),
        sort_phone=Min("phones__number"),
        sort_email=Min("emails__email"),
        sort_category=Min("categories__name"),
        sort_tag=Min("tags__name"),
    )
    allowed_columns = ["company", "phone", "email", "category", "tags", "status", "updated"]
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
        "direction": direction, "columns": columns, "categories": categories,
        "tags": tags, "filter_values": filter_values,
        "active_filter_count": active_filter_count(filter_values),
        "filter_chips": filter_chips(request.GET, filter_values, label_maps, request.path),
        "saved_filters": SavedFilter.objects.filter(user=request.user, scope="contacts"),
        "list_query": list_query.urlencode(),
    })


@login_required
def contact_bulk_action(request):
    if request.method != "POST":
        return redirect("contacts:list")
    ids = request.POST.getlist("selected")
    if request.POST.get("action") == "archive" and ids:
        Person.objects.filter(pk__in=ids, deleted_at__isnull=True).update(deleted_at=timezone.now())
        messages.success(request, tr("Archyvuota kontaktų: %(count)s.") % {"count": len(ids)})
    return redirect("contacts:list")

@login_required
def company_bulk_action(request):
    if request.method == "POST" and request.POST.get("action") == "archive":
        ids = request.POST.getlist("selected")
        updated = Company.objects.filter(pk__in=ids, deleted_at__isnull=True).update(deleted_at=timezone.now())
        if updated:
            messages.success(request, tr("Archyvuota įmonių: %(count)s.") % {"count": updated})
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
    people = Person.objects.filter(deleted_at__isnull=False).order_by("-deleted_at")
    companies = Company.objects.filter(deleted_at__isnull=False).order_by("-deleted_at")
    return render(request, "archive.html", {"people": people, "companies": companies})


@login_required
def contact_restore(request, pk):
    person = get_object_or_404(Person, pk=pk)
    if request.method == "POST" and person.deleted_at is not None:
        person.deleted_at = None
        person.save(update_fields=["deleted_at", "updated_at"])
        messages.success(request, tr("Kontaktas atkurtas."))
    return redirect("contacts:archive-list")


@login_required
def company_restore(request, pk):
    company = get_object_or_404(Company, pk=pk)
    if request.method == "POST" and company.deleted_at is not None:
        company.deleted_at = None
        company.save(update_fields=["deleted_at", "updated_at"])
        messages.success(request, tr("Įmonė atkurta."))
    return redirect("contacts:archive-list")


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
def contact_detail(request, pk):
    from .detail_editing import detail_fields
    person = get_object_or_404(Person.objects.prefetch_related("phones", "emails", "addresses", "web_links", "tags", "categories", "activities__created_by", "activities__attachments", "reminders", "company_links__company"), pk=pk, deleted_at__isnull=True)
    return render(request, "contacts/detail.html", {
        "person": person,
        "detail_fields": detail_fields(person),
        "tags": Tag.objects.all(), "categories": Category.objects.all(),
        "activity_form": ActivityForm(),
        "reminder_form": ReminderForm(),
        "activity_token": uuid.uuid4().hex,
        "reminder_token": uuid.uuid4().hex,
        "active_reminders": person.reminders.filter(completed_at__isnull=True, deleted_at__isnull=True),
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
        for upload in request.FILES.getlist("attachments"):
            Attachment.objects.create(activity=activity, file=upload, original_name=upload.name[:255], content_type=getattr(upload, "content_type", "") or "", size=upload.size)
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
    allowed_columns = ("company_code", "vat_code", "phone", "email", "contacts")
    default_columns = list(allowed_columns)
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
    return render(request, "companies/detail.html", {"company": company, "detail_fields": company_detail_fields(company), "tags": Tag.objects.all(), "categories": Category.objects.all(), "history": history, "activity_form": ActivityForm(), "activity_token": uuid.uuid4().hex})


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
        for upload in request.FILES.getlist("attachments"):
            Attachment.objects.create(activity=activity, file=upload, original_name=upload.name[:255], content_type=getattr(upload, "content_type", "") or "", size=upload.size)
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
    duplicate_settings = DuplicateSettings.load()
    report_duplicates = duplicate_settings.enabled and duplicate_settings.check_on_import
    for row in rows:
        first_name = _value(row, "Vardas", "first_name", "First name")
        last_name = _value(row, "Pavardė", "last_name", "Last name")
        email = _value(row, "El. paštai", "El. paštas", "email", "Email").split(";")[0].strip()
        if not first_name and not last_name:
            skipped += 1
            continue
        person = None
        if email:
            person = Person.objects.filter(emails__email__iexact=email, deleted_at__isnull=True).first()
        if not person:
            person = Person.objects.filter(first_name__iexact=first_name, last_name__iexact=last_name, deleted_at__isnull=True).first()
        if person and report_duplicates:
            possible_duplicates += 1
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
        for company_name in _import_relation_names(row, "Įmonė", "company", "Company"):
            company, _ = Company.objects.get_or_create(name=company_name)
            PersonCompanyLink.objects.get_or_create(
                person=person, company=company,
                defaults={"is_primary": not person.company_links.filter(is_primary=True).exists()},
            )
        for number in filter(None, (item.strip() for item in _value(row, "Telefonai", "Telefonas", "phone", "Phone").split(";"))):
            PhoneNumber.objects.get_or_create(person=person, number=number, defaults={"is_primary": not person.phones.exists()})
        for address in filter(None, (item.strip() for item in _value(row, "Adresai", "Adresas", "address", "Address").split(";"))):
            PostalAddress.objects.get_or_create(person=person, address=address)
        for url in filter(None, (item.strip() for item in _value(row, "URL", "url", "Website").split(";"))):
            WebLink.objects.get_or_create(person=person, url=url)
        for address in filter(None, (item.strip() for item in _value(row, "El. paštai", "El. paštas", "email", "Email").split(";"))):
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
    return {"created": created, "updated": updated, "skipped": skipped, "possible_duplicates": possible_duplicates, "duplicate_check_enabled": report_duplicates}


@login_required
def contacts_import(request):
    result = None
    if request.method == "POST":
        upload = request.FILES.get("file")
        if not upload or upload.size > 10 * 1024 * 1024:
            messages.error(request, tr("Pasirinkite iki 10 MB dydžio CSV arba XLSX failą."))
        else:
            name = upload.name.lower()
            try:
                if name.endswith(".csv"):
                    rows = list(csv.DictReader(TextIOWrapper(upload.file, encoding="utf-8-sig")))
                elif name.endswith(".xlsx"):
                    from openpyxl import load_workbook
                    sheet = load_workbook(upload, read_only=True, data_only=True).active
                    headers = [str(cell.value or "").strip() for cell in next(sheet.iter_rows())]
                    rows = [{headers[index]: cell.value for index, cell in enumerate(row)} for row in sheet.iter_rows(min_row=2)]
                else:
                    raise ValueError(tr("Netinkamas failo formatas"))
                result = _import_contact_rows(rows)
            except Exception:
                messages.error(request, tr("Nepavyko perskaityti failo. Patikrinkite stulpelius ir failo formatą."))
    return render(request, "import_export.html", {"result": result})
