from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from .models import Company, Person


@login_required
@require_POST
@transaction.atomic
def update_inline(request, kind, pk):
    model = Company if kind == "company" else Person
    record = get_object_or_404(model.objects.select_for_update(), pk=pk, deleted_at__isnull=True)
    field = request.POST.get("field")
    if field == "favourite" and kind == "person":
        record.favourite = request.POST.get("value") == "true"
        record.save(update_fields=["favourite", "updated_at"])
        return JsonResponse({"ok": True, "value": record.favourite})
    if field not in ("tags", "categories"):
        return JsonResponse({"error": "Netinkamas laukas."}, status=400)
    values = set(request.POST.getlist("values"))
    if len(values) > 3 or any(not value.isdecimal() for value in values):
        return JsonResponse({"error": "Pasirinkite ne daugiau kaip 3 reikšmes."}, status=400)
    relation = getattr(record, field)
    choices = relation.model.objects.filter(pk__in=values)
    if choices.count() != len(values):
        return JsonResponse({"error": "Pasirinkta reikšmė nebeegzistuoja."}, status=400)
    relation.set(choices)
    record.save(update_fields=["updated_at"])
    return JsonResponse({"ok": True})
