"""Regitra's services, visits and requests for a contact, read live and never stored.

A contact linked to Regitra (``external_source`` "regitra" and an ``external_id``)
shows them on its card. The data stays in Regitra's client database; the card
asks its ORDS REST service for one page at a time:

    GET {CRM_REGITRA_API_URL}/persons/{external_id}/{kind}/?offset=0&limit=10
    -> {"items": [{...}, ...], "hasMore": true, "offset": 0, "limit": 10, "count": 10}

The envelope is the ORDS collection format. The fields of each item are an
assumption until Regitra publishes its API description, so they are named in
COLUMNS alone. ``scripts/fake_regitra_api.py`` serves made-up data in this shape.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.translation import gettext as tr, gettext_lazy as _

SOURCE = "regitra"
PAGE_SIZE = 10
KINDS = [("services", _("Paslaugos")), ("visits", _("Vizitai")), ("requests", _("Prašymai"))]
# The fields each kind shows, as (item key, heading), in display order.
COLUMNS = {
    "services": [("date", _("Data")), ("name", _("Paslauga")), ("office", _("Padalinys")),
                 ("status", _("Būsena"))],
    "visits": [("time", _("Laikas")), ("office", _("Padalinys")), ("purpose", _("Tikslas")),
               ("status", _("Būsena"))],
    "requests": [("submitted", _("Pateikta")), ("type", _("Prašymas")), ("number", _("Numeris")),
                 ("status", _("Būsena"))],
}


class Unavailable(Exception):
    """Regitra did not answer usefully. The message is fit to show on the card."""


def linked(person):
    """True when the API is configured and `person` is a Regitra record."""
    return bool(settings.CRM_REGITRA_API_URL and person.external_source == SOURCE and person.external_id)


def _cell(value):
    """An item value as the card shows it: {"kind": "datetime" | "date" | "text", "value": ...}."""
    if isinstance(value, str):
        # A plain date first: parse_datetime would read one as midnight.
        try:
            day = parse_date(value)
            if day:
                return {"kind": "date", "value": day}
            moment = parse_datetime(value)
            if moment:
                return {"kind": "datetime", "value": moment}
        except ValueError:
            pass
    return {"kind": "text", "value": "" if value is None else str(value)}


def page(person, kind, offset=0):
    """One page of `kind` for `person`: {"rows": [[cell, ...], ...], "more": bool, "next": int},
    each cell carrying its column's heading.

    Raises Unavailable when the service cannot be reached or answers with
    something other than an ORDS collection. A person Regitra does not know (404)
    simply has nothing to show.
    """
    query = urllib.parse.urlencode({"offset": offset, "limit": PAGE_SIZE})
    url = "%s/persons/%s/%s/?%s" % (settings.CRM_REGITRA_API_URL,
                                    urllib.parse.quote(person.external_id, safe=""), kind, query)
    headers = {"Accept": "application/json"}
    if settings.CRM_REGITRA_API_TOKEN:
        headers["Authorization"] = "Bearer " + settings.CRM_REGITRA_API_TOKEN
    request = urllib.request.Request(url, headers=headers)
    try:
        # The base URL is checked to be http(s) when the settings load.
        with urllib.request.urlopen(request, timeout=settings.CRM_REGITRA_API_TIMEOUT) as response:  # nosec B310
            data = json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return {"rows": [], "more": False, "next": offset}
        raise Unavailable(tr("Regitros sistema atsakė klaida (%(code)s).") % {"code": error.code}) from error
    except (OSError, ValueError) as error:
        # Unreachable, timed out, or not JSON.
        raise Unavailable(tr("Regitros sistema šiuo metu nepasiekiama.")) from error
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise Unavailable(tr("Regitros sistema grąžino netikėtą atsakymą."))
    rows = [[{**_cell(item.get(key)), "heading": heading} for key, heading in COLUMNS[kind]]
            for item in items if isinstance(item, dict)]
    return {"rows": rows, "more": bool(data.get("hasMore")), "next": offset + len(items)}
