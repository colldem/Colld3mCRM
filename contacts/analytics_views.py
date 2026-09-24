"""Analytics: a personal dashboard and the relationship-care lists.

Everything is derived from data the CRM already collects (activities, reminders,
audit trail) and is scoped to what the signed-in user may see.
"""
import csv
import logging
from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError, transaction
from django.db.models import (Avg, Count, DurationField, Exists, ExpressionWrapper, F, Max, Min, OuterRef, Q,
                              Subquery)
from django.db.models.functions import TruncDate, TruncMonth, TruncWeek
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext as tr, gettext_lazy as tr_lazy

from . import charts
from .models import (Activity, AnalyticsSnapshot, AuditLog, Category, Company, EmailAddress, Person,
                     PersonCompanyLink, PhoneNumber, Reminder, Tag, UserProfile)
from .permissions import (in_any_team, record_visibility, responsible_company_ids,
                          responsible_person_ids, sees_all_records, teammate_ids,
                          visible_activities, visible_companies, visible_people, visible_reminders)
from .reminder_queries import open_q

logger = logging.getLogger(__name__)

# Short month names for the dashboard's six-month chart. Indexed by month - 1;
# lazy so the list is not frozen into one language at import time.
_MONTH_LABELS = [tr_lazy("Sau"), tr_lazy("Vas"), tr_lazy("Kov"), tr_lazy("Bal"),
                 tr_lazy("Geg"), tr_lazy("Bir"), tr_lazy("Lie"), tr_lazy("Rgp"),
                 tr_lazy("Rgs"), tr_lazy("Spa"), tr_lazy("Lap"), tr_lazy("Gru")]

SILENT_WINDOWS = (30, 60, 90)
LIST_LIMIT = 100
# Dashboard lists: how many rows a card shows before "show more", and how many
# are fetched at all. The cards share a height, so the visible count is fixed.
DASH_VISIBLE = 5
DASH_FETCH = 12
# How many rows a card's popup lists before it starts scrolling past usefulness.
POPUP_LIMIT = 50


# The dashboard's scope picker: whose records the page is about.
SCOPE_MINE, SCOPE_TEAM, SCOPE_ALL = "mine", "team", "all"


def dashboard_scopes(user):
    """The scopes `user` may choose between, as [(key, label)].

    Everyone has their own records. A team scope means something only for
    someone who is in a team and whose visibility reaches past themselves, and
    everyone's records only for someone who may see everyone's. A list of one
    is no choice at all, and the page then offers no picker.
    """
    scopes = [(SCOPE_MINE, tr("Mano"))]
    if in_any_team(user) and record_visibility(user) != UserProfile.VISIBILITY_OWN:
        scopes.append((SCOPE_TEAM, tr("Mano komandos")))
    if sees_all_records(user):
        scopes.append((SCOPE_ALL, tr("Visi")))
    return scopes


def _scope_owners(scope, user):
    """The user ids whose records the scope covers, or None for everybody's."""
    if scope == SCOPE_ALL:
        return None
    if scope == SCOPE_TEAM:
        return teammate_ids(user)
    return {user.pk}


def _owned_reminders(owners):
    """Reminders owned by `owners` — assigned to them, or theirs and unassigned."""
    if owners is None:
        return Q()
    return Q(assigned_to_id__in=owners) | Q(assigned_to__isnull=True, created_by_id__in=owners)


# The two cards that are about people rather than records say whose they are.
_ACTIVITY_LABELS = {SCOPE_MINE: tr_lazy("Mano veiklos šią savaitę"),
                    SCOPE_TEAM: tr_lazy("Komandos veiklos šią savaitę"),
                    SCOPE_ALL: tr_lazy("Visos veiklos šią savaitę")}
_AGENDA_LABELS = {SCOPE_MINE: tr_lazy("Mano įvykiai"),
                  SCOPE_TEAM: tr_lazy("Komandos įvykiai"),
                  SCOPE_ALL: tr_lazy("Visi įvykiai")}


def _day_bounds(day):
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(day, time.min), tz)
    return start, start + timedelta(days=1)


def _month_starts(today, count):
    """The first day of each of the last `count` months, oldest first."""
    starts, year, month = [], today.year, today.month
    for _ in range(count):
        starts.append(today.replace(year=year, month=month, day=1))
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return list(reversed(starts))


def _monthly_counts(queryset, today, months=6):
    """New records per calendar month, as [{"label": "Rgs", "value": n}]."""
    starts = _month_starts(today, months)
    window_start, _ = _day_bounds(starts[0])
    rows = []
    for index, first in enumerate(starts):
        start, _ = _day_bounds(first)
        if index + 1 < len(starts):
            end, _ = _day_bounds(starts[index + 1])
            total = queryset.filter(created_at__gte=start, created_at__lt=end).count()
        else:
            total = queryset.filter(created_at__gte=start).count()
        rows.append({"label": _MONTH_LABELS[first.month - 1], "value": total})
    return rows, window_start


def _card_rows(rows, total=None):
    """A dashboard list, twice over: the few rows the card has room for, and the
    fuller list its popup shows. Evaluates the queryset once."""
    rows = list(rows[:POPUP_LIMIT])
    # `total` is passed in when the real count is larger than what we fetched.
    return {"visible": rows[:DASH_VISIBLE], "all": rows,
            "total": len(rows) if total is None else total}


def _daily_counts(queryset, today, days=30):
    """One count per day, oldest first — the shape behind a card's sparkline."""
    start, _ = _day_bounds(today - timedelta(days=days - 1))
    per_day = dict(queryset.filter(created_at__gte=start)
                   .annotate(day=TruncDate("created_at"))
                   .values_list("day").annotate(total=Count("id")))
    return [per_day.get(today - timedelta(days=offset), 0)
            for offset in range(days - 1, -1, -1)]


@login_required
def dashboard(request):
    now = timezone.now()
    today = timezone.localdate()
    day_start, day_end = _day_bounds(today)
    week_start, _ = _day_bounds(today - timedelta(days=today.weekday()))
    # "This week" runs from today to the end of the current week: a superset of
    # today, and disjoint from what is already overdue.
    week_end = week_start + timedelta(days=7)

    scopes = dashboard_scopes(request.user)
    scope = request.GET.get("scope", SCOPE_MINE)
    if scope not in dict(scopes):
        scope = SCOPE_MINE
    owners = _scope_owners(scope, request.user)

    agenda = (Reminder.objects.filter(_owned_reminders(owners), open_q(now), deleted_at__isnull=True)
              # An agenda row shows the subject, the record it sits on and the
              # time: the record's own details are a click away, not here.
              .select_related("person", "company")
              .order_by("due_at"))
    scoped_activities = Activity.objects.filter(deleted_at__isnull=True)
    people = visible_people(request.user, Person.objects.filter(deleted_at__isnull=True))
    companies = visible_companies(request.user, Company.objects.filter(deleted_at__isnull=True))
    if owners is not None:
        scoped_activities = scoped_activities.filter(created_by_id__in=owners)
        people = people.filter(Q(owner_id__in=owners) | Q(pk__in=responsible_person_ids(owners)))
        companies = companies.filter(Q(owner_id__in=owners) | Q(pk__in=responsible_company_ids(owners)))

    counts = dict(scoped_activities.filter(created_at__gte=week_start)
                  .values_list("activity_type").annotate(total=Count("id")))
    week_activity = [{"label": label, "total": counts.get(key, 0)}
                     for key, label in Activity.TYPE_CHOICES]

    month_ago = now - timedelta(days=30)
    overdue = agenda.filter(due_at__lt=now)

    # "This month" for the type ring, six calendar months for the growth chart.
    month_start, _ = _day_bounds(today.replace(day=1))
    month_counts = dict(scoped_activities.filter(created_at__gte=month_start)
                        .values_list("activity_type").annotate(total=Count("id")))
    by_type = [{"label": label, "total": month_counts.get(key, 0)}
               for key, label in Activity.TYPE_CHOICES]

    people_months, _ = _monthly_counts(people, today)
    company_months, _ = _monthly_counts(companies, today)
    growth = [{"label": row["label"],
               "values": {"people": row["value"], "companies": company_months[index]["value"]}}
              for index, row in enumerate(people_months)]

    month_activities = scoped_activities.filter(created_at__gte=month_start)
    week_activities = scoped_activities.filter(created_at__gte=week_start)
    new_people = people.filter(created_at__gte=month_ago)
    new_companies = companies.filter(created_at__gte=month_ago)
    overdue_rows = _card_rows(overdue)
    return render(request, "analytics/dashboard.html", {
        "dash_scope": scope,
        # One option is no choice: the picker only appears when there is one.
        "dash_scopes": scopes if len(scopes) > 1 else [],
        "activity_kpi_label": _ACTIVITY_LABELS[scope],
        "agenda_label": _AGENDA_LABELS[scope],
        # The agenda card: one tab per horizon, plus a type filter over the rows.
        # "Today" is the one that opens, because it is the one people act on.
        "event_tabs": [
            {"key": "all", "label": tr("Visi"), "rows": _card_rows(agenda),
             "empty": tr("Suplanuotų įvykių nėra.")},
            {"key": "today", "label": tr("Šiandien"), "active": True,
             "rows": _card_rows(agenda.filter(due_at__gte=day_start, due_at__lt=day_end)),
             "empty": tr("Šiandien įvykių nėra.")},
            {"key": "week", "label": tr("Šią savaitę"),
             "rows": _card_rows(agenda.filter(due_at__gte=day_start, due_at__lt=week_end)),
             "empty": tr("Šią savaitę įvykių nėra.")},
            {"key": "overdue", "label": tr("Vėluojantys"), "tone": "warn", "rows": overdue_rows,
             "empty": tr("Vėluojančių įvykių nėra.")},
        ],
        "event_kinds": Reminder.KIND_CHOICES,
        "overdue_events": overdue_rows,
        "overdue_total": overdue.count(),
        "week_activity": week_activity,
        "week_activity_total": sum(item["total"] for item in week_activity),
        "new_people": new_people.count(),
        "new_companies": new_companies.count(),
        "people_total": people.count(),
        "companies_total": companies.count(),
        # Summary-card trends: the shape behind each number over the last 30 days.
        "spark_people": charts.sparkline(_daily_counts(people, today)),
        "spark_companies": charts.sparkline(_daily_counts(companies, today)),
        "spark_activity": charts.sparkline(_daily_counts(scoped_activities, today)),
        "spark_overdue": charts.sparkline(_daily_counts(overdue, today)),
        "activity_ring": charts.donut_multi(by_type),
        "activity_by_type": by_type,
        "activity_month_total": sum(row["total"] for row in by_type),
        "growth_chart": charts.grouped_bars(growth, ["people", "companies"], width=460, height=230),
        "recent_people": _card_rows(people.order_by("-created_at")
                                    .prefetch_related("phones", "company_links__company")),
        "recent_companies": _card_rows(companies.order_by("-created_at")),
        "recent_activities": _card_rows(
            scoped_activities.select_related("person", "company", "created_by").order_by("-created_at")),
        # Each summary card opens a popup listing what its number is made of.
        "week_activity_rows": _card_rows(
            week_activities.select_related("person", "company", "created_by").order_by("-created_at")),
        "month_activity_rows": _card_rows(
            month_activities.select_related("person", "company", "created_by").order_by("-created_at")),
        "new_people_rows": _card_rows(
            new_people.order_by("-created_at").prefetch_related("phones", "company_links__company")),
        "new_companies_rows": _card_rows(new_companies.order_by("-created_at")),
    })

def _with_last_contact(people):
    """Annotate each contact's latest activity date, looked up per row returned."""
    latest = Activity.objects.filter(deleted_at__isnull=True, person=OuterRef("pk")).order_by("-created_at")
    return people.annotate(last_contact_at=Subquery(latest.values("created_at")[:1]))


def _care_querysets(user, days):
    """The four relationship-care lists, before slicing.

    Membership is decided with EXISTS / NOT EXISTS (index lookups the database
    can turn into joins) rather than by grouping every contact's whole history;
    the last-contact date is looked up only for the rows that are shown."""
    history = Activity.objects.filter(deleted_at__isnull=True, person=OuterRef("pk"))
    cutoff = timezone.now() - timedelta(days=days)
    base = _with_last_contact(visible_people(user, Person.objects.filter(deleted_at__isnull=True))
                              .select_related("owner").prefetch_related("company_links__company", "phones", "emails"))
    return {
        "silent": base.filter(Exists(history), ~Exists(history.filter(created_at__gte=cutoff)))
                      .order_by("last_contact_at"),
        "never": base.filter(~Exists(history)).order_by("-created_at"),
        "no_owner": base.filter(~Exists(Person.responsibles.through.objects.filter(person=OuterRef("pk"))),
                                owner__isnull=True).order_by("last_name", "first_name"),
        "no_details": base.filter(~Exists(PhoneNumber.objects.filter(person=OuterRef("pk"))),
                                  ~Exists(EmailAddress.objects.filter(person=OuterRef("pk"))))
                          .order_by("last_name", "first_name"),
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


DEFAULT_PERIOD = 90


def _period(request):
    try:
        days = int(request.GET.get("days", DEFAULT_PERIOD))
    except ValueError:
        days = DEFAULT_PERIOD
    return days if days in PERIODS else DEFAULT_PERIOD


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


# The statistics below are counted by the database (GROUP BY a week or month)
# rather than by fetching every row into Python: with millions of activities
# that loop was most of a minute and hundreds of megabytes per request.

def _activity_buckets(activities, slots, monthly):
    """Per time slot, how many activities of each type."""
    keys = [key for key, _label in Activity.TYPE_CHOICES]
    tally = {key: {series: 0 for series in keys} for key, _label in slots}
    rows = (activities.annotate(bucket=(TruncMonth if monthly else TruncWeek)("created_at"))
            .values("bucket", "activity_type").annotate(total=Count("id")).order_by())
    for row in rows:
        slot = tally.get(_bucket_key(row["bucket"], monthly))
        if slot is not None:
            slot[row["activity_type"]] = slot.get(row["activity_type"], 0) + row["total"]
    return [{"label": label, "values": tally[key]} for key, label in slots]


def _created_per_month(records, slots):
    """{(year, month): new records} for the given monthly slots."""
    created = {key: 0 for key, _label in slots}
    for row in records.annotate(month=TruncMonth("created_at")).values("month").annotate(total=Count("id")).order_by():
        key = _bucket_key(row["month"], monthly=True)
        if key in created:
            created[key] += row["total"]
    return created


def _data_quality(people, total):
    """Share of contacts with an e-mail, a phone, a company and someone responsible."""
    responsible = Person.responsibles.through.objects.values("person_id")
    rows = [
        {"label": tr("Su el. paštu"), "total": people.filter(pk__in=EmailAddress.objects.values("person_id")).count()},
        {"label": tr("Su telefonu"), "total": people.filter(pk__in=PhoneNumber.objects.values("person_id")).count()},
        {"label": tr("Su įmone"), "total": people.filter(pk__in=PersonCompanyLink.objects.values("person_id")).count()},
        {"label": tr("Su atsakingu"),
         "total": people.filter(Q(owner__isnull=False) | Q(pk__in=responsible)).count()},
    ]
    for row in rows:
        row["percent"] = round(row["total"] * 100 / total) if total else 0
    return rows


def _by_creator(activities, limit):
    """[[user id, activities]] for the busiest authors (None: author deleted)."""
    return [[row["created_by"], row["total"]] for row in
            activities.values("created_by").annotate(total=Count("id")).order_by("-total", "created_by")[:limit]]


def _creator_rows(pairs):
    users = get_user_model().objects.in_bulk([pk for pk, _total in pairs if pk])
    unknown = str(tr("Nežinomas"))
    return [{"label": users[pk].username if pk in users else unknown, "total": total} for pk, total in pairs]


# Heavy analytics numbers are kept in AnalyticsSnapshot: for everyone who sees
# every record they are shared and refreshed in the background
# (refresh_analytics); anyone else gets their own, computed on first view.
SNAPSHOT_MAX_AGE = timedelta(minutes=30)
SNAPSHOT_REFRESH_AFTER = timedelta(minutes=20)


def _snapshot_key(name, days, user):
    return "%s:%d:%s" % (name, days, "all" if user is None or sees_all_records(user) else "user-%d" % user.pk)


def _snapshot(user, name, days, compute):
    """(numbers, computed_at) — stored ones while fresh, otherwise computed and stored."""
    key = _snapshot_key(name, days, user)
    now = timezone.now()
    stored = AnalyticsSnapshot.objects.filter(key=key, computed_at__gte=now - SNAPSHOT_MAX_AGE).first()
    if stored:
        return stored.payload, stored.computed_at
    # The shared "all" numbers are computed without a user, exactly as the worker does.
    numbers = compute(None if key.endswith(":all") else user, days)
    # Keeping them is only a saving: if another request holds the row (or SQLite
    # is busy), show the numbers just counted rather than fail the page.
    try:
        with transaction.atomic():
            AnalyticsSnapshot.objects.update_or_create(key=key, defaults={"payload": numbers, "computed_at": now})
    except DatabaseError:
        logger.warning("analytics snapshot %s not stored", key, exc_info=True)
    return numbers, now


def _communication_numbers(user, days):
    """The heavy part of the communication page: counts and record ids only."""
    monthly = days > 120
    since = timezone.now() - timedelta(days=days)
    people = visible_people(user, Person.objects.filter(deleted_at__isnull=True))
    companies = visible_companies(user, Company.objects.filter(deleted_at__isnull=True))
    activities = visible_activities(user, Activity.objects.filter(deleted_at__isnull=True, created_at__gte=since))

    def top(field, records):
        return [[row[field], row["total"]] for row in activities.filter(**{field + "__in": records}).values(field)
                .annotate(total=Count("id")).order_by("-total", field)[:10]]

    # Average days between contacts, per contact with at least two, over their whole history.
    spans = (Activity.objects.filter(deleted_at__isnull=True, person__in=people)
             .values("person_id").annotate(total=Count("id"), first_at=Min("created_at"), last_at=Max("created_at"))
             .filter(total__gte=2).order_by())
    gap = spans.aggregate(gap=Avg(ExpressionWrapper((F("last_at") - F("first_at")) / (F("total") - 1),
                                                    output_field=DurationField())))["gap"]
    return {
        "buckets": _activity_buckets(activities, _buckets(since.date(), timezone.localdate(), monthly), monthly),
        "top_people": top("person", people), "top_companies": top("company", companies),
        "by_user": _by_creator(activities, 10),
        "average_gap": round(gap.total_seconds() / 86400, 1) if gap is not None else None,
    }


@login_required
def communication(request):
    days = _period(request)
    numbers, computed_at = _snapshot(request.user, "communication", days, _communication_numbers)
    keys = [key for key, _label in Activity.TYPE_CHOICES]
    buckets = numbers["buckets"]
    legend = [{"label": label, "colour": charts.SERIES_COLOURS[index % len(charts.SERIES_COLOURS)],
               "total": sum(bucket["values"].get(key, 0) for bucket in buckets)}
              for index, (key, label) in enumerate(Activity.TYPE_CHOICES)]

    def ranked(pairs, records):
        found = records.in_bulk([pk for pk, _total in pairs])
        return [(found[pk], total) for pk, total in pairs if pk in found]

    people = visible_people(request.user, Person.objects.filter(deleted_at__isnull=True))
    companies = visible_companies(request.user, Company.objects.filter(deleted_at__isnull=True))
    return render(request, "analytics/communication.html", {
        "section": "communication", "days": days, "periods": PERIODS,
        "chart": charts.stacked_bars(buckets, keys), "legend": legend,
        "total": sum(item["total"] for item in legend),
        "top_people": charts.share_rows([
            {"label": str(person), "total": total, "url": person.get_absolute_url()}
            for person, total in ranked(numbers["top_people"], people)]),
        "top_companies": charts.share_rows([
            {"label": company.name, "total": total, "url": company.get_absolute_url()}
            for company, total in ranked(numbers["top_companies"], companies)]),
        "by_user": charts.share_rows(_creator_rows(numbers["by_user"])),
        "average_gap": numbers["average_gap"], "monthly": days > 120, "computed_at": computed_at,
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

    created = _created_per_month(people, slots)
    new_per_month = [{"label": label, "values": {"people": created[key]}} for key, label in slots]

    running = people.filter(created_at__lt=timezone.make_aware(
        datetime.combine(start, time.min), timezone.get_current_timezone())).count()
    cumulative = []
    for key, label in slots:
        running += created[key]
        cumulative.append({"label": label, "value": running})

    total_people = people.count()
    quality = _data_quality(people, total_people)

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


@login_required
def analytics_overview(request):
    """One scrolling page: a condensed band per detail section, dashboard styling.

    Self-contained — it re-queries a teaser slice (top 5, no CSV, no per-tag
    breakdowns) rather than calling the detail views. The period picker drives
    the communication, reminder and system bands; relationship care keeps its
    60-day window and growth its 12 months.
    """
    from .permissions import is_admin

    days = _period(request)
    now = timezone.now()
    today = timezone.localdate()
    since = now - timedelta(days=days)
    month_ago = now - timedelta(days=30)
    unknown = str(tr("Nežinomas"))

    people = visible_people(request.user, Person.objects.filter(deleted_at__isnull=True))
    companies = visible_companies(request.user, Company.objects.filter(deleted_at__isnull=True))
    reminders = visible_reminders(request.user, Reminder.objects.filter(deleted_at__isnull=True))
    overdue = reminders.filter(completed_at__isnull=True, due_at__lt=now)
    numbers, computed_at = _snapshot(request.user, "overview", days, _overview_numbers)

    people_total = people.count()
    kpis = {
        "people_total": people_total,
        "companies_total": companies.count(),
        "new_people": people.filter(created_at__gte=month_ago).count(),
        "new_companies": companies.filter(created_at__gte=month_ago).count(),
        "activity_total": numbers["activity_total"],
        "overdue_total": overdue.count(),
        "spark_people": charts.sparkline(_daily_counts(people, today)),
        "spark_companies": charts.sparkline(_daily_counts(companies, today)),
        "spark_activity": charts.sparkline(numbers["spark_activity"]),
        "spark_overdue": charts.sparkline(_daily_counts(overdue, today)),
    }

    # --- Communication band ---------------------------------------------
    keys = [key for key, _label in Activity.TYPE_CHOICES]
    comm_buckets = numbers["buckets"]
    comm_legend = [{"label": label,
                    "colour": charts.SERIES_COLOURS[index % len(charts.SERIES_COLOURS)],
                    "total": sum(bucket["values"].get(key, 0) for bucket in comm_buckets)}
                   for index, (key, label) in enumerate(Activity.TYPE_CHOICES)]
    comm = {
        "chart": charts.stacked_bars(comm_buckets, keys),
        "legend": comm_legend,
        "total": sum(item["total"] for item in comm_legend),
        "monthly": days > 120,
        "by_user": charts.share_rows(_creator_rows(numbers["by_user"])),
    }

    # --- Reminder band -------------------------------------------------
    r_scope = reminders.filter(due_at__gte=since)
    r_total = r_scope.count()
    r_done = r_scope.filter(completed_at__isnull=False).count()
    rem = {
        "ring": charts.donut(r_done, r_total),
        "total": r_total, "done": r_done,
        "overdue": r_scope.filter(completed_at__isnull=True, due_at__lt=now).count(),
        "upcoming": r_scope.filter(completed_at__isnull=True, due_at__gte=now).count(),
        "by_user": [
            {"label": entry["created_by__username"] or unknown,
             "total": entry["total"], "finished": entry["finished"],
             "percent": round(entry["finished"] * 100 / entry["total"]) if entry["total"] else 0}
            for entry in (r_scope.values("created_by__username")
                          .annotate(total=Count("id"),
                                    finished=Count("id", filter=Q(completed_at__isnull=False)))
                          .order_by("-total")[:5])],
    }

    # --- Growth band (fixed 12 months) --------------------------------
    start = (today.replace(day=1) - timedelta(days=31 * 11)).replace(day=1)
    month_slots = _buckets(start, today, monthly=True)
    created = _created_per_month(people, month_slots)
    running = people.filter(created_at__lt=timezone.make_aware(
        datetime.combine(start, time.min), timezone.get_current_timezone())).count()
    cumulative = []
    for key, label in month_slots:
        running += created[key]
        cumulative.append({"label": label, "value": running})
    quality = _data_quality(people, people_total)
    base = {"curve": charts.line_series(cumulative), "quality": quality,
            "total_people": people_total, "total_companies": kpis["companies_total"]}

    # --- Relationship care band (fixed 60-day window) -----------------
    counts = numbers["care_counts"]
    silent = _with_last_contact(people.filter(pk__in=numbers["silent_ids"])).in_bulk()
    care = {
        "silent": [silent[pk] for pk in numbers["silent_ids"] if pk in silent],
        "silent_total": counts["silent"],
        "counts": charts.share_rows([
            {"label": tr("Nutilę > 60 d."), "total": counts["silent"]},
            {"label": tr("Niekada nebendrauta"), "total": counts["never"]},
            {"label": tr("Be telefono ir el. pašto"), "total": counts["no_details"]},
            {"label": tr("Be atsakingo"), "total": counts["no_owner"]},
        ]),
    }

    # --- System band (admin only) ------------------------------------
    system = None
    if is_admin(request.user):
        entries = AuditLog.objects.filter(created_at__gte=since)
        system = {
            "counts": charts.share_rows([
                {"label": tr("Prisijungimai"), "total": entries.filter(action=AuditLog.LOGIN).count()},
                {"label": tr("Eksportai"), "total": entries.filter(action=AuditLog.EXPORT).count()},
                {"label": tr("Importai"), "total": entries.filter(action=AuditLog.IMPORT).count()},
                {"label": tr("Nepavykę prisijungimai"),
                 "total": entries.filter(action=AuditLog.LOGIN_FAILED).count()},
            ]),
            "by_actor": charts.share_rows([
                {"label": row["actor__username"] or unknown, "total": row["total"]}
                for row in entries.exclude(actor__isnull=True).values("actor__username")
                .annotate(total=Count("id")).order_by("-total")[:5]]),
        }

    return render(request, "analytics/overview.html", {
        "section": "overview", "days": days, "periods": PERIODS,
        "kpis": kpis, "comm": comm, "rem": rem, "base": base, "care": care, "system": system,
        "computed_at": computed_at,
    })


def _overview_numbers(user, days):
    """The heavy part of the overview: activity counts and the relationship-care band."""
    today = timezone.localdate()
    since = timezone.now() - timedelta(days=days)
    monthly = days > 120
    activities = visible_activities(user, Activity.objects.filter(deleted_at__isnull=True))
    recent = activities.filter(created_at__gte=since)
    care = _care_querysets(user, 60)
    return {
        "activity_total": recent.count(),
        "spark_activity": _daily_counts(activities, today),
        "buckets": _activity_buckets(recent, _buckets(since.date(), today, monthly), monthly),
        "by_user": _by_creator(recent, 5),
        "silent_ids": list(care["silent"].values_list("pk", flat=True)[:5]),
        "care_counts": {key: care[key].count() for key in ("silent", "never", "no_details", "no_owner")},
    }
