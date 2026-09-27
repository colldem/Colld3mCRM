"""Personal page layouts.

The person and company cards, the dashboard and the analytics overview are
made of blocks. Each user may drag them into another order (or into the other
column of a card), and switch off the ones they never read; the fields inside
the contact and custom-field cards can be reordered and switched off the same
way. "Default view" forgets the user's choices for the page.

A page declares its blocks in the template (templatetags/crm_layout.py); the
template order is the default. What the user changed lives on
``UserProfile.layout_config``, one entry per layout key::

    {"person": {"zones": {"main": ["activity", "contact"], "rail": ["org"]},
                "hidden": ["meta"]},
     "person.contact": {"zones": {"main": ["phones", "emails"]}, "hidden": []}}

Blocks the stored entry does not mention (added in a later version, or just
switched back on) take their default place, and ids the page no longer has are
ignored, so a stored layout never breaks a page.
"""
import json
import re

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_POST

# The pages that carry layouts; nested keys ("person.contact") start with one.
PAGES = ("person", "company", "dashboard", "analytics")
KEY_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}(\.[a-z][a-z0-9_-]{0,31})?$")
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_KEYS = 60
MAX_ZONES = 6
MAX_IDS = 120


def saved_layout(user, key):
    profile = getattr(user, "crm_profile", None) if user is not None else None
    entry = (getattr(profile, "layout_config", None) or {}).get(key)
    return entry if isinstance(entry, dict) else {}


def _ids(value):
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def arrange(saved, defaults):
    """Where each block goes: ``({zone: [ids]}, [hidden ids])``.

    ``defaults`` is ``{zone: [ids]}`` in template order."""
    home = {block: zone for zone, blocks in defaults.items() for block in blocks}
    hidden = list(dict.fromkeys(block for block in _ids(saved.get("hidden")) if block in home))
    placed = set(hidden)
    zones = {zone: [] for zone in defaults}
    stored = saved.get("zones") if isinstance(saved.get("zones"), dict) else {}
    for zone, blocks in stored.items():
        if zone not in zones:
            continue
        for block in _ids(blocks):
            if block in home and block not in placed:
                zones[zone].append(block)
                placed.add(block)
    for zone, blocks in defaults.items():
        for index, block in enumerate(blocks):
            if block not in placed:
                zones[zone].insert(min(index, len(zones[zone])), block)
                placed.add(block)
    return zones, hidden


class ArrangedList:
    """A list of card fields in the user's order, the switched-off ones apart."""

    def __init__(self, key, items, hidden):
        self.key, self.items, self.hidden = key, items, hidden


def arrange_fields(user, key, items):
    by_id = {item["field"]: item for item in items}
    zones, hidden = arrange(saved_layout(user, key), {"main": list(by_id)})
    return ArrangedList(key, [by_id[field] for field in zones["main"]],
                        [(field, str(by_id[field]["label"])) for field in hidden])


def _valid_key(key):
    return isinstance(key, str) and bool(KEY_RE.match(key)) and key.split(".")[0] in PAGES


def _clean_ids(value):
    if not isinstance(value, list) or len(value) > MAX_IDS:
        raise ValueError
    if not all(isinstance(item, str) and ID_RE.match(item) for item in value):
        raise ValueError
    return list(dict.fromkeys(value))


def _keep_absent(old, new, present):
    """The page only sends the blocks it drew. A block this record did not
    draw (Regitra on a person without it) keeps its place after the block it
    followed before, instead of falling back to its default."""
    result = list(new)
    for index, block in enumerate(old):
        if block in present or block in result:
            continue
        before = next((old[j] for j in range(index - 1, -1, -1) if old[j] in result), None)
        result.insert(result.index(before) + 1 if before else 0, block)
    return result


def clean_entry(payload, previous):
    zones = payload.get("zones")
    if not isinstance(zones, dict) or not zones or len(zones) > MAX_ZONES:
        raise ValueError
    cleaned = {}
    for zone, blocks in zones.items():
        if not isinstance(zone, str) or not ID_RE.match(zone):
            raise ValueError
        cleaned[zone] = _clean_ids(blocks)
    hidden = _clean_ids(payload.get("hidden", []))
    present = set(hidden).union(*cleaned.values())
    old_zones = previous.get("zones") if isinstance(previous.get("zones"), dict) else {}
    for zone, blocks in old_zones.items():
        if zone in cleaned:
            cleaned[zone] = _keep_absent(_ids(blocks), cleaned[zone], present)[:MAX_IDS]
    return {"zones": cleaned, "hidden": hidden}


@login_required
@require_POST
def save_layout(request):
    """Stores one layout the user rearranged, or forgets layouts ("reset")."""
    from .models import UserProfile

    try:
        payload = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"ok": False}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({"ok": False}, status=400)
    with transaction.atomic():
        profile, _created = UserProfile.objects.select_for_update().get_or_create(user=request.user)
        config = dict(profile.layout_config or {})
        if "reset" in payload:
            keys = payload["reset"]
            if not isinstance(keys, list) or not all(_valid_key(key) for key in keys):
                return JsonResponse({"ok": False}, status=400)
            for key in keys:
                config.pop(key, None)
        else:
            key = payload.get("key")
            if not _valid_key(key):
                return JsonResponse({"ok": False}, status=400)
            previous = config.get(key) if isinstance(config.get(key), dict) else {}
            try:
                config[key] = clean_entry(payload, previous)
            except ValueError:
                return JsonResponse({"ok": False}, status=400)
            if len(config) > MAX_KEYS:
                return JsonResponse({"ok": False}, status=400)
        profile.layout_config = config
        profile.save(update_fields=["layout_config", "updated_at"])
    return JsonResponse({"ok": True})
