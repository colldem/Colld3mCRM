"""The purposeful search: the way a record gets into someone's list.

There is no browsing here. One field, one reason, and either the one record
that answers or nothing at all — deliberately no list of near misses, because
a list of names is the browsing this build exists to replace.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils.translation import gettext as tr

from .audit import log as audit_log
from .models import AuditLog, RecordAccess
from .permissions import ACTIVE_VISIBILITIES, record_visibility
from .record_access import LONG_LEASE_DAYS, find, grant, live_for, take_into_work


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
