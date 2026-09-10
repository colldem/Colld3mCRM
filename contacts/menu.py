"""The side menu, per user.

Three bands, in this order:

1. **Core** — always visible, the things every CRM day starts with.
2. **Shortcuts** — up to five entries the user picked themselves: another CRM
   page, a specific contact or company, or an action.
3. **"Daugiau"** — a fold holding every optional entry the user switched off.
   Nothing ever disappears; it only moves out of the way.

The stored shape lives on ``UserProfile.menu_config``::

    {"hidden": ["archive", "duplicates"],
     "shortcuts": [{"kind": "page", "value": "duplicates"},
                   {"kind": "person", "value": "12"},
                   {"kind": "action", "value": "person-create"}]}
"""
from django.urls import NoReverseMatch, reverse
from django.utils.translation import gettext_lazy as tr_lazy

MAX_SHORTCUTS = 5

# key -> (label, url name, capability required or None, icon path data)
_ICONS = {
    "home": "M3 12l9-8 9 8M5 10v10h14V10",
    "contacts": "M16 20v-1.5a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4V20M9 3a4 4 0 1 1 0 8 4 4 0 0 1 0-8",
    "companies": "M3 21h18M5 21V4h10v17M15 9h4v12M8 7h4M8 11h4M8 15h4",
    "calendar": "M3 5h18v16H3zM3 10h18M8 3v4M16 3v4",
    "analytics": "M3 21h18M7 21V11M12 21V4M17 21v-7",
    "import-export": "M12 3v13M7 8l5-5 5 5M12 21V8M17 16l-5 5-5-5",
    "archive": "M3 7h18M9 11v6M15 11v6M5 7l1 14h12l1-14M9 7V4h6v3",
    "duplicates": "M8 8h12v12H8zM4 16V4h12",
    "settings": "M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6M4 12h1M19 12h1M12 4v1M12 19v1M6 6l1 1M17 17l1 1M18 6l-1 1M7 17l-1 1",
    "record": "M6 3h9l4 4v14H6zM8 9h8M8 13h8M8 17h5",
    "action": "M12 5v14M5 12h14",
}


class Item:
    """One rendered menu row."""

    def __init__(self, key, label, url, icon, active=False, fixed=False):
        self.key, self.label, self.url = key, label, url
        self.icon, self.active, self.fixed = icon, active, fixed


# Entries a user may fold away. `home`, `contacts` and `companies` are not here:
# a CRM without them is not a CRM. `settings` always sits at the bottom.
OPTIONAL_KEYS = ("calendar", "analytics", "import-export", "archive", "duplicates")

_PAGES = {
    "home": (tr_lazy("Darbastalis"), "contacts:home", None),
    "contacts": (tr_lazy("Kontaktai"), "contacts:list", None),
    "companies": (tr_lazy("Įmonės"), "contacts:company-list", None),
    "calendar": (tr_lazy("Kalendorius"), "contacts:calendar", None),
    "analytics": (tr_lazy("Analitika"), "contacts:analytics-overview", None),
    "import-export": (tr_lazy("Importas / eksportas"), "contacts:import-export", "can_import_or_export"),
    "archive": (tr_lazy("Archyvas"), "contacts:archive-list", None),
    "duplicates": (tr_lazy("Galimi dublikatai"), "contacts:duplicate-list", None),
    "settings": (tr_lazy("Nustatymai"), "contacts:settings", None),
}

# Shortcut targets that are an action rather than a place.
ACTIONS = {
    "person-create": (tr_lazy("Naujas kontaktas"), "contacts:person-create"),
    "company-create": (tr_lazy("Nauja įmonė"), "contacts:company-create"),
    "calendar-new": (tr_lazy("Naujas įvykis"), "contacts:calendar"),
}


def page_choices(capabilities):
    """(key, label) for every page the user may put in the menu."""
    return [(key, _PAGES[key][0]) for key in _PAGES
            if key not in ("home", "settings") and _allowed(key, capabilities)]


def _allowed(key, capabilities):
    need = _PAGES[key][2]
    if need == "can_import_or_export":
        return bool(capabilities.get("can_import") or capabilities.get("can_export"))
    return need is None or bool(capabilities.get(need))


def _config(profile):
    raw = getattr(profile, "menu_config", None) or {}
    hidden = [key for key in raw.get("hidden", []) if key in OPTIONAL_KEYS]
    shortcuts = [item for item in raw.get("shortcuts", []) if isinstance(item, dict)]
    return hidden, shortcuts[:MAX_SHORTCUTS]


def _shortcut_item(entry, capabilities):
    """Resolve one stored shortcut, or None if its target is gone."""
    from .models import Company, Person

    kind, value = entry.get("kind"), str(entry.get("value", ""))
    try:
        if kind == "page" and value in _PAGES and _allowed(value, capabilities):
            label, url_name, _ = _PAGES[value]
            return Item(f"s-{value}", label, reverse(url_name), _ICONS.get(value, _ICONS["record"]))
        if kind == "action" and value in ACTIONS:
            label, url_name = ACTIONS[value]
            return Item(f"s-{value}", label, reverse(url_name), _ICONS["action"])
        if kind in ("person", "company") and value.isdigit():
            model = Person if kind == "person" else Company
            record = model.objects.filter(pk=int(value), deleted_at__isnull=True).first()
            if record is not None:
                return Item(f"s-{kind}-{value}", str(record), record.get_absolute_url(), _ICONS["record"])
    except NoReverseMatch:
        return None
    return None


def build(request):
    """The three bands, ready to render."""
    from .permissions import CAPABILITY_KEYS, has_capability

    user = request.user
    capabilities = {key: has_capability(user, key) for key in CAPABILITY_KEYS}
    profile = getattr(user, "crm_profile", None)
    hidden, shortcuts = _config(profile)
    current = getattr(request.resolver_match, "url_name", "") or ""

    def make(key, fixed=False):
        label, url_name, _ = _PAGES[key]
        try:
            url = reverse(url_name)
        except NoReverseMatch:
            return None
        target = url_name.split(":")[-1]
        active = current == target or (key == "contacts" and current == "detail") \
            or (key == "companies" and current.startswith("company")) \
            or (key == "analytics" and "analytics" in current) \
            or (key == "settings" and current.startswith("settings"))
        return Item(key, label, url, _ICONS.get(key, _ICONS["record"]), active, fixed)

    core = [make(key, fixed=True) for key in ("home", "contacts", "companies")]
    core += [make(key) for key in OPTIONAL_KEYS
             if key not in hidden and _allowed(key, capabilities)]
    more = [make(key) for key in OPTIONAL_KEYS
            if key in hidden and _allowed(key, capabilities)]
    picked = [_shortcut_item(entry, capabilities) for entry in shortcuts]
    return {
        "core": [item for item in core if item],
        "shortcuts": [item for item in picked if item],
        "more": [item for item in more if item],
        "settings_item": make("settings", fixed=True),
    }
