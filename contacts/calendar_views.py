"""Calendar module: a day/week/month grid over the current user's reminders.

Only reminders the signed-in user created are shown — this is a personal agenda,
not a shared team calendar.
"""
from datetime import date, datetime, time, timedelta

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.translation import gettext as tr
from django.views.decorators.http import require_POST

from .models import AuditLog, Company, Person, Reminder
from .audit import log as audit_log
from .permissions import visible_companies, visible_people

VIEWS = ("day", "week", "month")
MINUTES_IN_DAY = 24 * 60
SNAP_MINUTES = 15


def _anchor_date(request):
    raw = request.GET.get("date", "")
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return timezone.localdate()


def _range_for(view, anchor):
    """Inclusive first day and exclusive last day of the visible grid."""
    if view == "day":
        return anchor, anchor + timedelta(days=1)
    if view == "month":
        first = anchor.replace(day=1)
        grid_start = first - timedelta(days=first.weekday())
        next_month = (first + timedelta(days=32)).replace(day=1)
        grid_end = next_month + timedelta(days=(7 - next_month.weekday()) % 7)
        return grid_start, grid_end
    start = anchor - timedelta(days=anchor.weekday())
    return start, start + timedelta(days=7)


def _step(view, anchor, direction):
    if view == "day":
        return anchor + timedelta(days=direction)
    if view == "month":
        first = anchor.replace(day=1)
        return (first - timedelta(days=1)).replace(day=1) if direction < 0 else (first + timedelta(days=32)).replace(day=1)
    return anchor + timedelta(days=7 * direction)


def user_reminders(user, start, end):
    """The user's own reminders overlapping [start, end) in local time."""
    tz = timezone.get_current_timezone()
    begin = timezone.make_aware(datetime.combine(start, time.min), tz)
    finish = timezone.make_aware(datetime.combine(end, time.min), tz)
    return (Reminder.objects.filter(created_by=user, deleted_at__isnull=True, due_at__lt=finish)
            .filter(due_at__gte=begin - timedelta(days=1))
            .select_related("person", "company")
            .prefetch_related("person__phones", "person__addresses")
            .order_by("due_at", "pk"))


def _lay_out(events):
    """Place overlapping reminders side by side.

    Events are split into clusters of transitively overlapping slots so that a
    single busy hour does not shrink the rest of the day.
    """
    ordered = sorted(events, key=lambda item: (item["start_min"], item["end_min"]))
    cluster, cluster_end = [], None
    for item in ordered:
        if cluster and item["start_min"] >= cluster_end:
            _lay_out_cluster(cluster)
            cluster, cluster_end = [], None
        cluster.append(item)
        cluster_end = item["end_min"] if cluster_end is None else max(cluster_end, item["end_min"])
    if cluster:
        _lay_out_cluster(cluster)
    return ordered


def _lay_out_cluster(cluster):
    lanes = []
    for item in cluster:
        for index, lane_end in enumerate(lanes):
            if lane_end <= item["start_min"]:
                lanes[index] = item["end_min"]
                item["lane"] = index
                break
        else:
            item["lane"] = len(lanes)
            lanes.append(item["end_min"])
    total = max(len(lanes), 1)
    for item in cluster:
        item["width_pct"] = round(100 / total, 4)
        item["left_pct"] = round(item["lane"] * 100 / total, 4)


def _day_events(reminders, day, now):
    """Reminders that touch `day`, positioned as percentages of a 24h column."""
    tz = timezone.get_current_timezone()
    out = []
    for reminder in reminders:
        start = timezone.localtime(reminder.due_at, tz)
        end = timezone.localtime(reminder.finish_at, tz)
        if start.date() > day or end.date() < day:
            continue
        start_min = 0 if start.date() < day else start.hour * 60 + start.minute
        end_min = MINUTES_IN_DAY if end.date() > day else end.hour * 60 + end.minute
        end_min = max(end_min, start_min + SNAP_MINUTES)
        out.append({
            "reminder": reminder,
            "start_min": start_min,
            "end_min": end_min,
            "top_pct": round(start_min * 100 / MINUTES_IN_DAY, 4),
            "height_pct": round((end_min - start_min) * 100 / MINUTES_IN_DAY, 4),
            "label": start.strftime("%H:%M"),
            "is_past": reminder.finish_at < now,
            "done": reminder.completed_at is not None,
        })
    return _lay_out(out)


@login_required
def calendar_page(request):
    view = request.GET.get("view", "week")
    view = view if view in VIEWS else "week"
    anchor = _anchor_date(request)
    start, end = _range_for(view, anchor)
    reminders = list(user_reminders(request.user, start, end))
    now = timezone.now()
    today = timezone.localdate()

    days = []
    cursor = start
    while cursor < end:
        days.append({
            "date": cursor,
            "is_today": cursor == today,
            "is_other_month": view == "month" and cursor.month != anchor.replace(day=1).month,
            "events": _day_events(reminders, cursor, now),
        })
        cursor += timedelta(days=1)

    if view == "month":
        weeks = [days[i:i + 7] for i in range(0, len(days), 7)]
    else:
        weeks = []

    return render(request, "calendar/page.html", {
        "calendar_view": view,
        "anchor": anchor,
        "range_start": start,
        "range_end": end - timedelta(days=1),
        "days": days,
        "weeks": weeks,
        "hours": [f"{hour:02d}:00" for hour in range(24)],
        "prev_date": _step(view, anchor, -1),
        "next_date": _step(view, anchor, 1),
        "today": today,
        "now_pct": round((timezone.localtime(now).hour * 60 + timezone.localtime(now).minute) * 100 / MINUTES_IN_DAY, 4),
        "snap_minutes": SNAP_MINUTES,
        "default_minutes": Reminder.DEFAULT_MINUTES,
    })


@login_required
def calendar_records(request):
    """Contacts and companies for the event dialog's picker, with phone/address."""
    query = request.GET.get("q", "").strip()
    if len(query) < 2:
        return JsonResponse({"results": []})
    results = []
    people = visible_people(request.user, Person.objects.filter(deleted_at__isnull=True)).filter(
        first_name__icontains=query
    ) | visible_people(request.user, Person.objects.filter(deleted_at__isnull=True)).filter(
        last_name__icontains=query
    )
    for person in people.distinct().prefetch_related("phones", "addresses")[:8]:
        phone = person.phones.first()
        address = person.addresses.first()
        results.append({
            "kind": "person", "id": person.pk, "label": str(person),
            "sublabel": person.job_title or "",
            "phone": phone.number if phone else "",
            "address": address.address if address else "",
            "url": person.get_absolute_url(),
        })
    companies = visible_companies(request.user, Company.objects.filter(deleted_at__isnull=True, name__icontains=query))
    for company in companies[:8]:
        results.append({
            "kind": "company", "id": company.pk, "label": company.name,
            "sublabel": company.company_code or "",
            "phone": company.phone, "address": company.address,
            "url": company.get_absolute_url(),
        })
    return JsonResponse({"results": results})


def _parse_local(value):
    """Parse a 'YYYY-MM-DDTHH:MM' value from the dialog into an aware datetime."""
    try:
        naive = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if timezone.is_aware(naive):
        return naive
    return timezone.make_aware(naive, timezone.get_current_timezone())


def _resolve_record(request):
    """The contact/company chosen in the dialog, or (None, None) when blank."""
    kind = request.POST.get("record_kind", "")
    raw = request.POST.get("record_id", "").strip()
    if kind == "person" and raw:
        return visible_people(request.user, Person.objects.filter(pk=raw, deleted_at__isnull=True)).first(), None
    if kind == "company" and raw:
        return None, visible_companies(request.user, Company.objects.filter(pk=raw, deleted_at__isnull=True)).first()
    return None, None


def _back_to_calendar(request):
    view = request.POST.get("view", "week")
    anchor = request.POST.get("date", "")
    return redirect(f"/calendar/?view={view if view in VIEWS else 'week'}&date={anchor}")


@login_required
@require_POST
def calendar_event_save(request, pk=None):
    reminder = None
    if pk:
        reminder = Reminder.objects.filter(pk=pk, created_by=request.user, deleted_at__isnull=True).first()
        if reminder is None:
            return _back_to_calendar(request)
    text = request.POST.get("text", "").strip()
    start = _parse_local(request.POST.get("due_at", ""))
    end = _parse_local(request.POST.get("end_at", ""))
    if not text or start is None:
        return _back_to_calendar(request)
    if end is None or end <= start:
        end = start + timedelta(minutes=Reminder.DEFAULT_MINUTES)
    person, company = _resolve_record(request)

    if reminder is None:
        reminder = Reminder(created_by=request.user)
    reminder.text = text[:500]
    reminder.due_at = start
    reminder.end_at = end
    reminder.person = person
    reminder.company = company
    reminder.save()
    audit_log(AuditLog.UPDATE if pk else AuditLog.CREATE, request=request,
              target=reminder.record, target_type="" if reminder.record else "reminder",
              target_label="" if reminder.record else reminder.text[:80], field=str(tr("Priminimas")),
              new=f"{reminder.text[:150]} · {timezone.localtime(start):%Y-%m-%d %H:%M}")
    return _back_to_calendar(request)


@login_required
@require_POST
def calendar_event_delete(request, pk):
    reminder = Reminder.objects.filter(pk=pk, created_by=request.user, deleted_at__isnull=True).first()
    if reminder is not None:
        audit_log(AuditLog.DELETE, request=request, target=reminder.record,
                  target_type="" if reminder.record else "reminder",
                  target_label="" if reminder.record else reminder.text[:80],
                  field=str(tr("Priminimas")), old=reminder.text[:150])
        reminder.deleted_at = timezone.now()
        reminder.save(update_fields=["deleted_at", "updated_at"])
    return _back_to_calendar(request)
