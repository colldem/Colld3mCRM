"""Analytics: a personal dashboard and the relationship-care lists.

Everything is derived from data the CRM already collects (activities, reminders,
audit trail) and is scoped to what the signed-in user may see.
"""
import csv
from datetime import datetime, time, timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Max, Q
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext as tr, gettext_lazy as tr_lazy

from .models import Activity, AuditLog, Company, Person, Reminder
from .permissions import visible_companies, visible_people

SILENT_WINDOWS = (30, 60, 90)
LIST_LIMIT = 100
RECENT_LIMIT = 6


def _day_bounds(day):
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(day, time.min), tz)
    return start, start + timedelta(days=1)


def _recently_touched(user, limit=RECENT_LIMIT):
    """Contacts and companies this user changed most recently, newest first."""
    entries = (AuditLog.objects.filter(actor=user, target_type__in=("person", "company"))
               .exclude(action=AuditLog.DELETE).order_by("-created_at")
               .values_list("target_type", "target_id")[:200])
    order, seen = [], set()
    for kind, target_id in entries:
        key = (kind, target_id)
        if key in seen or not target_id.isdigit():
            continue
        seen.add(key)
        order.append(key)
        if len(order) >= limit:
            break
    person_ids = [int(pk) for kind, pk in order if kind == "person"]
    company_ids = [int(pk) for kind, pk in order if kind == "company"]
    people = {p.pk: p for p in visible_people(
        user, Person.objects.filter(pk__in=person_ids, deleted_at__isnull=True))}
    companies = {c.pk: c for c in visible_companies(
        user, Company.objects.filter(pk__in=company_ids, deleted_at__isnull=True))}
    records = []
    for kind, target_id in order:
        record = (people if kind == "person" else companies).get(int(target_id))
        if record is not None:
            records.append(record)
    return records


@login_required
def dashboard(request):
    now = timezone.now()
    today = timezone.localdate()
    day_start, day_end = _day_bounds(today)
    tomorrow_end = day_end + timedelta(days=1)
    week_start, _ = _day_bounds(today - timedelta(days=today.weekday()))

    agenda = (Reminder.objects.filter(created_by=request.user, deleted_at__isnull=True,
                                      completed_at__isnull=True)
              .select_related("person", "company"))
    counts = dict(Activity.objects.filter(created_by=request.user, deleted_at__isnull=True,
                                          created_at__gte=week_start)
                  .values_list("activity_type").annotate(total=Count("id")))
    week_activity = [{"label": label, "total": counts.get(key, 0)}
                     for key, label in Activity.TYPE_CHOICES]

    people = visible_people(request.user, Person.objects.filter(deleted_at__isnull=True))
    companies = visible_companies(request.user, Company.objects.filter(deleted_at__isnull=True))
    month_ago = now - timedelta(days=30)

    return render(request, "analytics/dashboard.html", {
        "today_events": agenda.filter(due_at__gte=day_start, due_at__lt=day_end).order_by("due_at"),
        "tomorrow_events": agenda.filter(due_at__gte=day_end, due_at__lt=tomorrow_end).order_by("due_at"),
        "overdue_events": agenda.filter(due_at__lt=now).order_by("due_at")[:10],
        "overdue_total": agenda.filter(due_at__lt=now).count(),
        "recently_touched": _recently_touched(request.user),
        "week_activity": week_activity,
        "week_activity_total": sum(item["total"] for item in week_activity),
        "new_people": people.filter(created_at__gte=month_ago).count(),
        "new_companies": companies.filter(created_at__gte=month_ago).count(),
        "people_total": people.count(),
        "companies_total": companies.count(),
    })


def _care_querysets(user, days):
    """The four relationship-care lists, before slicing."""
    base = (visible_people(user, Person.objects.filter(deleted_at__isnull=True))
            .select_related("owner").prefetch_related("company_links__company", "phones", "emails"))
    dated = base.annotate(last_contact_at=Max("activities__created_at",
                                              filter=Q(activities__deleted_at__isnull=True)))
    cutoff = timezone.now() - timedelta(days=days)
    return {
        "silent": dated.filter(last_contact_at__lt=cutoff).order_by("last_contact_at"),
        "never": dated.filter(last_contact_at__isnull=True).order_by("-created_at"),
        "no_owner": dated.filter(owner__isnull=True, responsibles__isnull=True)
                         .order_by("last_name", "first_name").distinct(),
        "no_details": dated.filter(phones__isnull=True, emails__isnull=True)
                           .order_by("last_name", "first_name").distinct(),
    }


# Lazy: this dict is built at import time, so it must not freeze one language.
CARE_LABELS = {
    "silent": tr_lazy("Nutilę kontaktai"),
    "never": tr_lazy("Niekada nebendrauta"),
    "no_owner": tr_lazy("Be atsakingo"),
    "no_details": tr_lazy("Be telefono ir el. pašto"),
}


@login_required
def relationship_care(request):
    try:
        days = int(request.GET.get("days", 60))
    except ValueError:
        days = 60
    days = days if days in SILENT_WINDOWS else 60
    lists = _care_querysets(request.user, days)

    wanted = request.GET.get("export", "")
    if wanted in lists:
        return _care_csv(wanted, lists[wanted])

    return render(request, "analytics/care.html", {
        "days": days,
        "windows": SILENT_WINDOWS,
        "groups": [{"key": key, "label": CARE_LABELS[key], "total": queryset.count(),
                    "rows": queryset[:LIST_LIMIT], "dated": key == "silent"}
                   for key, queryset in lists.items()],
        "limit": LIST_LIMIT,
    })


def _care_csv(key, queryset):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="crm-{key}.csv"'
    response.write("﻿")
    writer = csv.writer(response)
    writer.writerow([tr("Vardas"), tr("Pavardė"), tr("Įmonė"), tr("Telefonas"),
                     tr("El. paštas"), tr("Atsakingas"), tr("Paskutinis kontaktas")])
    from .permissions import user_label

    for person in queryset[:5000]:
        link = person.company_links.all()
        phone = person.phones.all()
        email = person.emails.all()
        last = getattr(person, "last_contact_at", None)
        writer.writerow([
            person.first_name, person.last_name,
            link[0].company.name if link else "",
            phone[0].number if phone else "",
            email[0].email if email else "",
            user_label(person.owner),
            timezone.localtime(last).strftime("%Y-%m-%d") if last else "",
        ])
    return response
