"""How a record gets into someone's list, and how it leaves it again.

Two ways in: the purposeful search, where a user finds one record and says why
— no browsing, no list of near misses, because a list of names is what this
build replaces — and an assignment, where a lead puts a record in front of one
of their people. Both are the same row, and both carry a reason.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as tr
from django.views.decorators.http import require_POST

from .audit import log as audit_log
from .models import AuditLog, Company, Person, RecordAccess
from .permissions import ACTIVE_VISIBILITIES, record_visibility
from .record_access import (LONG_LEASE_DAYS, assign, assignable_users, end, find, grant,
                            live_for, live_on, take_into_work)


@login_required
def record_search(request):
    """Find one record, say why, and put it in your list."""
    query = request.POST.get("q", "") if request.method == "POST" else ""
    purpose = request.POST.get("purpose", "")
    note = request.POST.get("note", "").strip()[:200]
    long_lease = request.POST.get("long") == "1"

    if request.method == "POST":
        if purpose not in dict(RecordAccess.PURPOSES):
            messages.error(request, tr("Pasirinkite, kodėl atveriate įrašą."))
        else:
            record = find(query)
            if record is None:
                # No hints, no near misses: not finding someone must not become
                # a way of asking whether they are in the base at all.
                messages.error(request, tr("Pagal šią užklausą įrašo nerasta."))
            else:
                opener = take_into_work if long_lease else grant
                opener(request.user, record, purpose, note=note)
                audit_log(AuditLog.ACCESS, request=request, target=record,
                          field=str(dict(RecordAccess.PURPOSES)[purpose]), new=note)
                return redirect(record)

    return render(request, "contacts/record_search.html", {
        "purposes": RecordAccess.PURPOSES,
        "query": query, "purpose": purpose, "note": note, "long_lease": long_lease,
        "long_days": LONG_LEASE_DAYS,
        "open_now": _open_now(request.user),
        # Someone who sees the whole base has nothing to unlock; the page still
        # works for them, and says so rather than pretending otherwise.
        "unlocks_nothing": record_visibility(request.user) not in ACTIVE_VISIBILITIES,
    })


def _open_now(user):
    """What the user already has open, newest first — their working list."""
    return (live_for(user).select_related("person", "company", "granted_by")
            .order_by("-created_at")[:25])


def _record(kind, pk):
    model = Company if kind == "company" else Person
    return get_object_or_404(model, pk=pk, deleted_at__isnull=True)


def assignment_context(actor, record):
    """The card's "who is working on this" panel, or nothing to show.

    Only for someone who may assign: who else has a record open is a fact about
    colleagues, not a detail of the record.
    """
    people = assignable_users(actor)
    if not people.exists():
        return {}
    return {"access_rows": live_on(record), "assignable_users": people,
            "access_purposes": RecordAccess.PURPOSES}


@login_required
@require_POST
def record_assign(request, kind, pk):
    """A lead puts a record in one of their people's lists."""
    record = _record(kind, pk)
    people = assignable_users(request.user)
    if not people.exists():
        # Assigning is what leading a team is for; someone who leads none has
        # no business at this address at all.
        raise Http404
    target = people.filter(pk=request.POST.get("user", "")).first()
    purpose = request.POST.get("purpose", "")
    note = request.POST.get("note", "").strip()[:200]
    if target is None:
        messages.error(request, tr("Neturite teisės priskirti šiam darbuotojui."))
    elif purpose not in dict(RecordAccess.PURPOSES):
        messages.error(request, tr("Pasirinkite, kodėl priskiriate įrašą."))
    else:
        assign(request.user, target, record, purpose, note=note)
        audit_log(AuditLog.ACCESS, request=request, target=record,
                  field=str(dict(RecordAccess.PURPOSES)[purpose]),
                  old=str(tr("priskirta")), new=target.get_username())
        messages.success(request, tr("Įrašas priskirtas."))
    return redirect(record)


@login_required
@require_POST
def record_access_end(request, pk):
    """Close someone's access early — theirs to give up, a lead's to withdraw."""
    access = get_object_or_404(RecordAccess, pk=pk, ended_at__isnull=True)
    mine = access.user_id == request.user.pk
    if not mine and not assignable_users(request.user).filter(pk=access.user_id).exists():
        messages.error(request, tr("Neturite teisės nutraukti šios prieigos."))
    else:
        end(access)
        messages.success(request, tr("Prieiga nutraukta."))
    record = access.company or access.person
    return redirect(record) if record and not mine else redirect("contacts:record-search")
