"""Calendar module: a day/week/month grid over reminders.

Shows the reminders assigned to the signed-in user (falling back to the ones
they created while unassigned). Colleagues' calendars can be laid over it one
at a time; those are fetched on demand and never cached, so what you see is
whatever their agenda says right now.
"""
from datetime import date, datetime, time, timedelta

from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.translation import gettext as tr
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from .models import AuditLog, Company, Person, Reminder
from .audit import log as audit_log
from .permissions import assignable_users_for, user_label, visible_companies, visible_people
from .reminder_queries import mine_q as _mine_q

VIEWS = ("day", "week", "month")
MINUTES_IN_DAY = 24 * 60
SNAP_MINUTES = 15
# How many colleagues the sidebar lists before "load more".
COLLEAGUE_PAGE = 10
# One stable hue per colleague, dark enough for white text.
COLLEAGUE_COLOURS = ("#b4552d", "#2e8a6b", "#7a4fbf", "#9a6b10", "#c0447a",
                     "#3f7f8c", "#4a7f2f", "#8a4b8a", "#a35441", "#5d6bbf")
# Quick picks for the dialog's reminder lead time, in minutes before the event.
NOTIFY_QUICK_PICKS = ((2880, tr("prieš 2 d.")), (1440, tr("prieš 1 d.")), (60, tr("prieš valandą")))
# "Notify me" ticked but no time chosen: nudge just before it starts.
NOTIFY_FALLBACK_MINUTES = 5
# `Reminder.notify_before` is a small integer: roughly 22 days of lead.
NOTIFY_MAX_MINUTES = 32767


def colleague_colour(pk):
    return COLLEAGUE_COLOURS[pk % len(COLLEAGUE_COLOURS)]


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
    """The reminders `user` owns overlapping [start, end) in local time."""
    tz = timezone.get_current_timezone()
    begin = timezone.make_aware(datetime.combine(start, time.min), tz)
    finish = timezone.make_aware(datetime.combine(end, time.min), tz)
    return (Reminder.objects.filter(_mine_q(user), deleted_at__isnull=True, due_at__lt=finish)
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
            "done": reminder.is_done,
            # Under an hour there is only room for the time and the subject;
            # a third line would be sliced in half.
            "tall": end_min - start_min >= 60,
        })
    return _lay_out(out)


def _colleague_rows(user, offset):
    """One page of the colleagues whose calendars `user` may look at."""
    queryset = assignable_users_for(user).exclude(pk=user.pk)
    total = queryset.count()
    rows = [{"id": other.pk, "label": user_label(other), "colour": colleague_colour(other.pk)}
            for other in queryset[offset:offset + COLLEAGUE_PAGE]]
    return rows, total


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

    weeks = [days[i:i + 7] for i in range(0, len(days), 7)] if view == "month" else []
    colleagues, colleague_total = _colleague_rows(request.user, 0)

    return render(request, "calendar/page.html", {
        "calendar_view": view,
        "anchor": anchor,
        "range_start": start,
        "range_end": end - timedelta(days=1),
        "days": days,
        "weeks": weeks,
        "mini_month": _mini_month(anchor, today),
        "mini_prev": _step("month", anchor, -1),
        "mini_next": _step("month", anchor, 1),
        "hours": [f"{hour:02d}:00" for hour in range(24)],
        "prev_date": _step(view, anchor, -1),
        "next_date": _step(view, anchor, 1),
        "today": today,
        "now_pct": round((timezone.localtime(now).hour * 60 + timezone.localtime(now).minute)
                         * 100 / MINUTES_IN_DAY, 4),
        "snap_minutes": SNAP_MINUTES,
        "default_minutes": Reminder.DEFAULT_MINUTES,
        "event_kinds": Reminder.KIND_CHOICES,
        "notify_quick_picks": NOTIFY_QUICK_PICKS,
        "colleagues": colleagues,
        "colleague_total": colleague_total,
        "colleague_page": COLLEAGUE_PAGE,
    })


def _mini_month(anchor, today):
    """The sidebar's month picker: six rows of seven days around `anchor`."""
    first = anchor.replace(day=1)
    grid_start = first - timedelta(days=first.weekday())
    cells = []
    for offset in range(42):
        day = grid_start + timedelta(days=offset)
        cells.append({"date": day, "is_today": day == today,
                      "is_anchor": day == anchor, "is_other_month": day.month != first.month})
    return [cells[i:i + 7] for i in range(0, 42, 7)]


@login_required
@require_GET
def calendar_colleagues(request):
    """The next page of colleague names for the sidebar's "load more"."""
    try:
        offset = max(int(request.GET.get("offset", 0)), 0)
    except ValueError:
        offset = 0
    rows, total = _colleague_rows(request.user, offset)
    return JsonResponse({"results": rows, "total": total,
                         "has_more": offset + len(rows) < total})


@never_cache
@login_required
@require_GET
def calendar_colleague_events(request, pk):
    """One colleague's agenda for the visible range.

    Deliberately uncached and fetched only when their calendar is switched on:
    an overlay is a live look at somebody else's day, not a copy of it.
    """
    colleague = assignable_users_for(request.user).exclude(pk=request.user.pk).filter(pk=pk).first()
    if colleague is None:
        raise Http404
    view = request.GET.get("view", "week")
    start, end = _range_for(view if view in VIEWS else "week", _anchor_date(request))
    reminders = list(user_reminders(colleague, start, end))
    now = timezone.now()

    events = []
    cursor = start
    while cursor < end:
        for item in _day_events(reminders, cursor, now):
            reminder = item["reminder"]
            events.append({
                "id": reminder.pk, "date": cursor.isoformat(),
                "start_min": item["start_min"], "end_min": item["end_min"],
                "label": item["label"], "text": reminder.text,
                "kind": reminder.kind, "record": str(reminder.record or ""),
                "is_past": item["is_past"], "done": item["done"],
            })
        cursor += timedelta(days=1)
    return JsonResponse({"owner": user_label(colleague), "colour": colleague_colour(colleague.pk),
                         "events": events})


@login_required
def calendar_records(request):
    """Contacts and companies for the event dialog's picker.

    Each row carries what the dialog shows beside it — phone, address — and the
    obvious counterpart, so picking a contact fills in their main company and
    picking a company fills in its main contact.
    """
    query = request.GET.get("q", "").strip()
    if len(query) < 2:
        return JsonResponse({"results": []})
    results = []
    visible = visible_people(request.user, Person.objects.filter(deleted_at__isnull=True))
    people = visible.filter(first_name__icontains=query) | visible.filter(last_name__icontains=query)
    for person in people.distinct().prefetch_related(
            "phones", "addresses", "company_links__company")[:8]:
        phone = person.phones.first()
        address = person.addresses.first()
        company = person.primary_company
        results.append({
            "kind": "person", "id": person.pk, "label": str(person),
            "sublabel": person.job_title or "",
            "phone": phone.number if phone else "",
            "address": address.address if address else "",
            "url": person.get_absolute_url(),
            "partner": company.name if company else "",
        })
    companies = visible_companies(request.user, Company.objects.filter(deleted_at__isnull=True, name__icontains=query))
    for company in companies[:8]:
        contact = _primary_contact(request.user, company)
        results.append({
            "kind": "company", "id": company.pk, "label": company.name,
            "sublabel": company.company_code or "",
            "phone": company.phone, "address": company.address,
            "url": company.get_absolute_url(),
            "partner": str(contact) if contact else "",
        })
    return JsonResponse({"results": results})


def _primary_contact(user, company):
    """The company's main contact, as far as `user` is allowed to see."""
    return visible_people(user, Person.objects.filter(
        company_links__company=company, deleted_at__isnull=True,
    )).order_by("-company_links__is_primary", "last_name", "first_name").first()


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
    """The contact and company the dialog points at.

    One is chosen; the other is filled in from it — a contact's main company, a
    company's main contact — so the event lands on both cards.
    """
    kind = request.POST.get("record_kind", "")
    raw = request.POST.get("record_id", "").strip()
    if kind == "person" and raw:
        person = visible_people(request.user, Person.objects.filter(pk=raw, deleted_at__isnull=True)).first()
        return person, (person.primary_company if person else None)
    if kind == "company" and raw:
        company = visible_companies(request.user, Company.objects.filter(pk=raw, deleted_at__isnull=True)).first()
        return (_primary_contact(request.user, company) if company else None), company
    return None, None


def _notify_before(request, start):
    """Minutes before the event to send the email, or None for no email.

    The dialog asks when to remind, as a date and a time; what the row keeps is
    the lead in minutes, which is what the notifier walks.
    """
    if not request.POST.get("notify"):
        return None
    at = _parse_local(request.POST.get("notify_at", ""))
    if at is None or at >= start:
        # Asked for a reminder without saying when: just before it starts.
        return NOTIFY_FALLBACK_MINUTES
    # Capped at the column's ceiling; a lead that long is a different event.
    return min(NOTIFY_MAX_MINUTES, max(1, round((start - at).total_seconds() / 60)))


def _back_to_calendar(request):
    view = request.POST.get("view", "week")
    anchor = request.POST.get("date", "")
    return redirect(f"/calendar/?view={view if view in VIEWS else 'week'}&date={anchor}")


@login_required
@require_POST
def calendar_event_save(request, pk=None):
    reminder = None
    if pk:
        reminder = Reminder.objects.filter(_mine_q(request.user), pk=pk, deleted_at__isnull=True).first()
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
    kind = request.POST.get("kind", "")

    if reminder is None:
        reminder = Reminder(created_by=request.user, assigned_to=request.user)
    reminder.kind = kind if kind in dict(Reminder.KIND_CHOICES) else Reminder.KIND_REMINDER
    reminder.text = text[:500]
    reminder.description = request.POST.get("description", "").strip()[:5000]
    # A joining link belongs to a meeting; the field is hidden for anything else.
    reminder.meeting_url = (request.POST.get("meeting_url", "").strip()[:500]
                            if reminder.kind == Reminder.KIND_MEETING else "")
    reminder.due_at = start
    reminder.end_at = end
    reminder.person = person
    reminder.company = company
    reminder.notify_before = _notify_before(request, start)
    if pk is None:  # recurrence is only set at creation from the calendar
        freq = request.POST.get("recurrence_freq", "")
        reminder.recurrence_freq = freq if freq in dict(Reminder.FREQ_CHOICES) else ""
    reminder.save()
    if reminder.is_recurring:
        from .recurrence import apply_to_future, extend
        (extend if pk is None else apply_to_future)(reminder)
    audit_log(AuditLog.UPDATE if pk else AuditLog.CREATE, request=request,
              target=reminder.record, target_type="" if reminder.record else "reminder",
              target_label="" if reminder.record else reminder.text[:80], field=str(tr("Priminimas")),
              new=f"{reminder.text[:150]} · {timezone.localtime(start):%Y-%m-%d %H:%M}")
    return _back_to_calendar(request)


@login_required
@require_POST
def calendar_event_complete(request, pk):
    """Tick an event off from the calendar dialog."""
    reminder = Reminder.objects.filter(_mine_q(request.user), pk=pk, deleted_at__isnull=True).first()
    if reminder is not None and reminder.completed_at is None:
        reminder.completed_at = timezone.now()
        reminder.save(update_fields=["completed_at", "updated_at"])
        audit_log(AuditLog.UPDATE, request=request, target=reminder.record,
                  target_type="" if reminder.record else "reminder",
                  target_label="" if reminder.record else reminder.text[:80],
                  field=str(tr("Priminimas")), new=str(tr("Atlikta")))
    return _back_to_calendar(request)


@login_required
@require_POST
def calendar_event_delete(request, pk):
    reminder = Reminder.objects.filter(_mine_q(request.user), pk=pk, deleted_at__isnull=True).first()
    if reminder is not None:
        audit_log(AuditLog.DELETE, request=request, target=reminder.record,
                  target_type="" if reminder.record else "reminder",
                  target_label="" if reminder.record else reminder.text[:80],
                  field=str(tr("Priminimas")), old=reminder.text[:150])
        reminder.deleted_at = timezone.now()
        reminder.save(update_fields=["deleted_at", "updated_at"])
    return _back_to_calendar(request)
