"""Asmens kodas: shown covered, uncovered on request, and every uncovering logged.

The code identifies a person completely and for life, so it is the one field on
a card that nobody should read by accident. The card shows the last four digits
covered; the whole value is fetched only when somebody asks for it, and that ask
is written to the audit log with their name on it.
"""
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as tr
from django.views.decorators.http import require_POST

from .audit import log as audit_log
from .models import AuditLog, Person
from .permissions import can_see_person

COVERED_DIGITS = 4


def cover(value):
    """`38901011234` -> `3890101****`: enough to tell two people apart, not enough
    to fill a form in someone's name."""
    value = (value or "").strip()
    keep = len(value) - COVERED_DIGITS
    if keep <= 0:
        return "*" * len(value)
    return value[:keep] + "*" * COVERED_DIGITS


@login_required
@require_POST
def personal_code_reveal(request, pk):
    person = get_object_or_404(Person, pk=pk, deleted_at__isnull=True)
    if not can_see_person(request.user, person) or not person.personal_code:
        raise Http404
    audit_log(AuditLog.PERSONAL_CODE, request=request, target=person,
              field=str(tr("Asmens kodas")))
    return JsonResponse({"value": person.personal_code})
