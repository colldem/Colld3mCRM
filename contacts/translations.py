"""Editable interface translations.

Wording is adjusted by exporting a CSV, editing it, and importing it back
(Settings -> Vertimai). Overrides live in the database rather than in the ``.po``
files, because those ship inside the Docker image and would be lost on the next
rebuild.

An override is applied by writing straight into Django's in-memory catalog, so
``{% translate %}`` picks it up with no restart. Two things make that work:

* Django builds a catalog object for ``lt`` even though there is no ``lt``
  ``.mo`` file, so the source language can be overridden too — the msgid stays
  as it is in the code, only what the user sees changes.
* ``_catalog`` is gettext's own mapping. It is a private attribute, so
  ``test_translation_override_reaches_gettext`` exists to fail loudly if a
  future Django release changes it.

Each gunicorn worker holds its own catalog, so ``ensure_current()`` compares a
version stamp before every request and reloads only when it has moved.
"""
import re
import threading
from pathlib import Path

from django.conf import settings
from django.utils.translation import trans_real

DOMAIN_LANGUAGES = ("lt", "en")

# Where translatable strings are marked. The .po files carry almost no "#:"
# references (they were hand-maintained), so the module column is derived by
# reading the sources instead.
_SKIP_DIRS = {".venv", ".git", "node_modules", "staticfiles", "locale", "runtime", "__pycache__"}
_SUFFIXES = (".html", ".py", ".txt")
_TAG = re.compile(r"""\{%\s*(?:translate|trans)\s+(['"])(.+?)\1""")
_CALL = re.compile(r"""\b(?:_|tr|tr_lazy|gettext|gettext_lazy|ngettext)\(\s*(['"])(.+?)\1""", re.S)
_BLOCK = re.compile(r"\{%\s*blocktranslate[^%]*%\}(.*?)\{%\s*endblocktranslate\s*%\}", re.S)
_VARIABLE = re.compile(r"\{\{\s*(\w+)[^}]*\}\}")

_lock = threading.Lock()
_defaults = {}          # language -> {msgid: msgstr} as shipped in the .po
_applied = {}           # language -> set of msgids this process wrote as overrides
_sources = None         # msgid -> sorted list of module labels
_version = None         # the override version this process has applied


def _module_label(path):
    """A short, honest location: the file, minus noise. No invented mapping."""
    text = str(path)
    for prefix in ("templates/", "./"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text[:-5] if text.endswith(".html") else text


def source_index():
    """msgid -> the modules that use it. Scanned once per process."""
    global _sources
    if _sources is not None:
        return _sources
    found = {}
    root = Path(settings.BASE_DIR)
    for path in root.rglob("*"):
        if path.is_dir() or path.suffix not in _SUFFIXES:
            continue
        if any(part in _SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        label = _module_label(path.relative_to(root))
        for pattern in (_TAG, _CALL):
            for _quote, value in pattern.findall(text):
                found.setdefault(value, set()).add(label)
        for body in _BLOCK.findall(text):
            # Django rewrites {{ name }} as %(name)s when building the msgid.
            found.setdefault(_VARIABLE.sub(r"%(\1)s", body).strip(), set()).add(label)
    _sources = {key: sorted(value) for key, value in found.items()}
    return _sources


def _catalog(language):
    return trans_real.translation(language)._catalog


def capture_defaults():
    """Remember the shipped translations before any override is applied."""
    if _defaults:
        return
    # Build the whole snapshot first, then publish it in one assignment — a
    # half-captured _defaults would make the "if _defaults" guard skip the retry.
    snapshot = {language: dict(_catalog(language)) for language in DOMAIN_LANGUAGES}
    _defaults.update(snapshot)


def default_for(language, msgid):
    """The shipped value. Lithuanian has no .mo, so its default is the msgid."""
    return _defaults.get(language, {}).get(msgid) or (msgid if language == "lt" else "")


def all_msgids():
    """Every string the interface can translate, in a stable order."""
    capture_defaults()
    return sorted(key for key in _defaults.get("en", {}) if isinstance(key, str) and key)


def rows():
    """One row per string: module, key, and the value each language shows now."""
    from .models import Translation

    overrides = {t.msgid: t for t in Translation.objects.all()}
    modules = source_index()
    result = []
    for msgid in all_msgids():
        override = overrides.get(msgid)
        used_in = modules.get(msgid) or []
        result.append({
            "msgid": msgid,
            "module": "; ".join(used_in[:3]) if used_in else "",
            "unused": not used_in,
            "lt": (override.lt if override and override.lt else default_for("lt", msgid)),
            "en": (override.en if override and override.en else default_for("en", msgid)),
            "overridden": bool(override),
        })
    return result


def apply_overrides():
    """Push the stored overrides into this process's catalogs."""
    global _version
    from .models import Translation

    capture_defaults()
    stored = list(Translation.objects.all())
    for language in DOMAIN_LANGUAGES:
        catalog = _catalog(language)
        # Reset every string we changed last time to its shipped value. For
        # Lithuanian that value is the msgid itself (there is no lt .mo), and
        # writing the msgid back is what makes gettext show it again — the
        # catalog has no delete, so a stale override cannot just be popped.
        for msgid in _applied.get(language, ()):
            catalog[msgid] = default_for(language, msgid)
        active = set()
        for row in stored:
            value = row.lt if language == "lt" else row.en
            if value:
                catalog[row.msgid] = value
                active.add(row.msgid)
        _applied[language] = active
    # The process that just saved is now current; skip a redundant reload on
    # its next request.
    _version = current_version()
    return len(stored)


def current_version():
    from .models import Translation

    return Translation.objects.version()


def ensure_current():
    """Reload if another process changed the overrides. Cheap when unchanged."""
    global _version
    stamp = current_version()
    if stamp == _version:
        return False
    with _lock:
        if stamp == _version:
            return False
        apply_overrides()
        _version = stamp
    return True
