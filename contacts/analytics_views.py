"""Analytics: a personal dashboard and the relationship-care lists.

Everything is derived from data the CRM already collects (activities, reminders,
audit trail) and is scoped to what the signed-in user may see.
"""
import csv
from datetime import datetime, time, timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Count, F, Max, Min, Q
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext as tr, gettext_lazy as tr_lazy

from . import charts
from .models import Activity, AuditLog, Category, Company, Person, Reminder, Tag
from .permissions import visible_companies, visible_people, visible_reminders

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
        "section": "care",
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


# --- G1 part 2: statistics pages -------------------------------------------

PERIODS = (30, 90, 365)


def _period(request):
    try:
        days = int(request.GET.get("days", 90))
    except ValueError:
        days = 90
    return days if days in PERIODS else 90


def _buckets(start, end, monthly):
    """Ordered (key, label) time buckets covering [start, end]."""
    out, cursor = [], start
    if monthly:
        cursor = start.replace(day=1)
        while cursor <= end:
            out.append(((cursor.year, cursor.month), cursor.strftime("%Y-%m")))
            cursor = (cursor + timedelta(days=32)).replace(day=1)
    else:
        cursor = start - timedelta(days=start.weekday())
        while cursor <= end:
            out.append((cursor.isocalendar()[:2], cursor.strftime("%m-%d")))
            cursor += timedelta(days=7)
    return out


def _bucket_key(moment, monthly):
    local = timezone.localtime(moment)
    return (local.year, local.month) if monthly else local.isocalendar()[:2]


@login_required
def communication(request):
    days = _period(request)
    monthly = days > 120
    since = timezone.now() - timedelta(days=days)
    today = timezone.localdate()

    people_ids = visible_people(request.user, Person.objects.filter(deleted_at__isnull=True))
    company_ids = visible_companies(request.user, Company.objects.filter(deleted_at__isnull=True))
    activities = Activity.objects.filter(deleted_at__isnull=True, created_at__gte=since).filter(
        Q(person__in=people_ids) | Q(company__in=company_ids))

    keys = [key for key, _label in Activity.TYPE_CHOICES]
    slots = _buckets(since.date(), today, monthly)
    tally = {key: {series: 0 for series in keys} for key, _label in slots}
    for moment, kind in activities.values_list("created_at", "activity_type"):
        slot = tally.get(_bucket_key(moment, monthly))
        if slot is not None:
            slot[kind] = slot.get(kind, 0) + 1
    buckets = [{"label": label, "values": tally[key]} for key, label in slots]

    legend = [{"label": label, "colour": charts.SERIES_COLOURS[index % len(charts.SERIES_COLOURS)],
               "total": sum(bucket["values"].get(key, 0) for bucket in buckets)}
              for index, (key, label) in enumerate(Activity.TYPE_CHOICES)]

    top_people = charts.share_rows([
        {"label": str(row), "total": row.total, "url": row.get_absolute_url()}
        for row in people_ids.filter(activities__in=activities)
        .annotate(total=Count("activities")).order_by("-total")[:10]])
    top_companies = charts.share_rows([
        {"label": row.name, "total": row.total, "url": row.get_absolute_url()}
        for row in company_ids.filter(activities__in=activities)
        .annotate(total=Count("activities")).order_by("-total")[:10]])
    by_user = charts.share_rows([
        {"label": row["created_by__username"] or str(tr("Nežinomas")), "total": row["total"]}
        for row in activities.values("created_by__username").annotate(total=Count("id")).order_by("-total")[:10]])

    spans = (people_ids.annotate(total=Count("activities", filter=Q(activities__deleted_at__isnull=True)),
                                 first_at=Min("activities__created_at"),
                                 last_at=Max("activities__created_at"))
             .filter(total__gte=2))
    gaps = [(row.last_at - row.first_at).days / (row.total - 1) for row in spans]
    average_gap = round(sum(gaps) / len(gaps), 1) if gaps else None

    return render(request, "analytics/communication.html", {
        "section": "communication", "days": days, "periods": PERIODS,
        "chart": charts.stacked_bars(buckets, keys), "legend": legend,
        "total": sum(item["total"] for item in legend),
        "top_people": top_people, "top_companies": top_companies, "by_user": by_user,
        "average_gap": average_gap, "monthly": monthly,
    })


@login_required
def reminder_stats(request):
    days = _period(request)
    since = timezone.now() - timedelta(days=days)
    now = timezone.now()
    scope = visible_reminders(request.user, Reminder.objects.filter(
        deleted_at__isnull=True, due_at__gte=since))

    done = scope.filter(completed_at__isnull=False)
    overdue = scope.filter(completed_at__isnull=True, due_at__lt=now)
    upcoming = scope.filter(completed_at__isnull=True, due_at__gte=now)
    total = scope.count()

    late = [(row.completed_at - row.due_at).total_seconds() / 86400
            for row in done.filter(completed_at__gt=F("due_at")).only("completed_at", "due_at")]

    rows = []
    for entry in (scope.values("created_by__username")
                  .annotate(total=Count("id"), finished=Count("id", filter=Q(completed_at__isnull=False)))
                  .order_by("-total")[:10]):
        rows.append({"label": entry["created_by__username"] or str(tr("Nežinomas")),
                     "total": entry["total"], "finished": entry["finished"],
                     "percent": round(entry["finished"] * 100 / entry["total"]) if entry["total"] else 0})

    return render(request, "analytics/reminders.html", {
        "section": "reminders", "days": days, "periods": PERIODS,
        "total": total, "done": done.count(), "overdue": overdue.count(), "upcoming": upcoming.count(),
        "ring": charts.donut(done.count(), total),
        "average_late": round(sum(late) / len(late), 1) if late else None,
        "by_user": rows,
    })


@login_required
def growth(request):
    today = timezone.localdate()
    months = 12
    start = (today.replace(day=1) - timedelta(days=31 * (months - 1))).replace(day=1)
    slots = _buckets(start, today, monthly=True)

    people = visible_people(request.user, Person.objects.filter(deleted_at__isnull=True))
    companies = visible_companies(request.user, Company.objects.filter(deleted_at__isnull=True))

    created = {key: 0 for key, _label in slots}
    for moment in people.values_list("created_at", flat=True):
        key = _bucket_key(moment, monthly=True)
        if key in created:
            created[key] += 1
    new_per_month = [{"label": label, "values": {"people": created[key]}} for key, label in slots]

    running = people.filter(created_at__lt=timezone.make_aware(
        datetime.combine(start, time.min), timezone.get_current_timezone())).count()
    cumulative = []
    for key, label in slots:
        running += created[key]
        cumulative.append({"label": label, "value": running})

    total_people = people.count()
    quality = [
        {"label": tr("Su el. paštu"), "total": people.filter(emails__isnull=False).distinct().count()},
        {"label": tr("Su telefonu"), "total": people.filter(phones__isnull=False).distinct().count()},
        {"label": tr("Su įmone"), "total": people.filter(company_links__isnull=False).distinct().count()},
        {"label": tr("Su atsakingu"), "total": people.exclude(owner__isnull=True, responsibles__isnull=True).distinct().count()},
    ]
    for row in quality:
        row["percent"] = round(row["total"] * 100 / total_people) if total_people else 0

    return render(request, "analytics/growth.html", {
        "section": "growth",
        "curve": charts.line_series(cumulative),
        "new_chart": charts.stacked_bars(new_per_month, ["people"]),
        "total_people": total_people, "total_companies": companies.count(),
        "by_category": charts.share_rows([
            {"label": row.name, "total": row.total} for row in
            Category.objects.filter(people__in=people).annotate(total=Count("people")).order_by("-total")[:10]]),
        "by_tag": charts.share_rows([
            {"label": row.name, "total": row.total} for row in
            Tag.objects.filter(people__in=people).annotate(total=Count("people")).order_by("-total")[:10]]),
        "by_owner": charts.share_rows([
            {"label": row["owner__username"] or str(tr("Be atsakingo")), "total": row["total"]}
            for row in people.values("owner__username").annotate(total=Count("id")).order_by("-total")[:10]]),
        "quality": quality,
    })


@login_required
def system_usage(request):
    from .permissions import is_admin

    if not is_admin(request.user):
        raise Http404
    days = _period(request)
    since = timezone.now() - timedelta(days=days)
    entries = AuditLog.objects.filter(created_at__gte=since)
    labels = dict(AuditLog.ACTION_CHOICES)

    return render(request, "analytics/system.html", {
        "section": "system", "days": days, "periods": PERIODS,
        "logins": entries.filter(action=AuditLog.LOGIN).count(),
        "failed": entries.filter(action=AuditLog.LOGIN_FAILED).count(),
        "imports": entries.filter(action=AuditLog.IMPORT).count(),
        "exports": entries.filter(action=AuditLog.EXPORT).count(),
        "by_action": charts.share_rows([
            {"label": str(labels.get(row["action"], row["action"])), "total": row["total"]}
            for row in entries.values("action").annotate(total=Count("id")).order_by("-total")]),
        # Group by the account, not the stored label — a renamed user is still one user.
        "by_actor": charts.share_rows([
            {"label": row["actor__username"] or str(tr("Nežinomas")), "total": row["total"]}
            for row in entries.exclude(actor__isnull=True).values("actor__username")
            .annotate(total=Count("id")).order_by("-total")[:10]]),
    })
