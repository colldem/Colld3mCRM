from django.http import JsonResponse
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from django.utils.translation import gettext as tr

from .context_processors import reminder_count, system_settings


@never_cache
@require_GET
def reminder_snapshot(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": tr("Prisijunkite iš naujo.")}, status=401)
    context = {**reminder_count(request), **system_settings(request)}
    return JsonResponse({"count": context["active_reminder_count"],
                         "html": render_to_string("reminders/menu.html", context)})
