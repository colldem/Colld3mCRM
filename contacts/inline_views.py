from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST
from django.utils.translation import gettext as tr

from .audit import log as audit_log
from .models import AuditLog, Company, Person
from .permissions import visible_companies, visible_people


@login_required
@require_POST
@transaction.atomic
def update_inline(request, kind, pk):
    model = Company if kind == "company" else Person
    scope = visible_companies if kind == "company" else visible_people
    record = get_object_or_404(scope(request.user, model.objects.select_for_update()), pk=pk, deleted_at__isnull=True)
    field = request.POST.get("field")
    if field == "favourite" and kind == "person":
        old = record.favourite
        record.favourite = request.POST.get("value") == "true"
        record.save(update_fields=["favourite", "updated_at"])
        if old != record.favourite:
            audit_log(AuditLog.UPDATE, request=request, target=record, field=tr("Mėgstamas"),
                      old=tr("taip") if old else tr("ne"), new=tr("taip") if record.favourite else tr("ne"))
        return JsonResponse({"ok": True, "value": record.favourite})
    if field not in ("tags", "categories"):
        return JsonResponse({"error": tr("Netinkamas laukas.")}, status=400)
    values = set(request.POST.getlist("values"))
    if len(values) > 3 or any(not value.isdecimal() for value in values):
        return JsonResponse({"error": tr("Pasirinkite ne daugiau kaip 3 reikšmes.")}, status=400)
    relation = getattr(record, field)
    choices = relation.model.objects.filter(pk__in=values)
    if choices.count() != len(values):
        return JsonResponse({"error": tr("Pasirinkta reikšmė nebeegzistuoja.")}, status=400)
    old_names = sorted(relation.values_list("name", flat=True))
    relation.set(choices)
    record.save(update_fields=["updated_at"])
    new_names = sorted(choices.values_list("name", flat=True))
    if old_names != new_names:
        label = tr("Žymos") if field == "tags" else tr("Kategorijos")
        audit_log(AuditLog.UPDATE, request=request, target=record, field=label,
                  old=", ".join(old_names), new=", ".join(new_names))
    return JsonResponse({"ok": True})
