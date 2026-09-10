import re

from django import template
from django.utils.html import conditional_escape, urlize
from django.utils.safestring import mark_safe


register = template.Library()


@register.filter(is_safe=True)
def rich_text(value):
    """Render the small, documented Markdown subset used by CRM notes safely."""
    text = conditional_escape(value or "")
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"<em>\1</em>", text)
    # The input has already been escaped above, so urlize must not escape the
    # deliberately generated formatting tags a second time.
    text = urlize(text, autoescape=False)
    return mark_safe(text.replace("\n", "<br>"))


@register.filter
def get_item(mapping, key):
    try:
        return mapping.get(key, "")
    except AttributeError:
        return ""


@register.filter
def user_initials(user):
    initials = f"{(user.first_name or '')[:1]}{(user.last_name or '')[:1]}".strip()
    return (initials or user.get_username()[:2]).upper()


@register.filter
def user_display_name(user):
    return user.get_full_name().strip() or user.get_username()


@register.filter
def record_initials(record):
    """Up to two letters for a contact or company tile.

    People read best as first + last initial; a company as the initials of its
    first two words ("UAB Pavyzdys" -> "UP"), so the legal-form prefix does not
    make every tile identical.
    """
    first = getattr(record, "first_name", "")
    if first or getattr(record, "last_name", ""):
        letters = f"{first[:1]}{getattr(record, 'last_name', '')[:1]}"
    else:
        words = str(record).split()
        letters = "".join(word[:1] for word in words[:2])
    return (letters.strip() or str(record)[:2]).upper()


@register.filter
def record_tone(record):
    """A stable 0-5 palette index, so a record keeps the same tile colour."""
    return sum(str(record).encode("utf-8")) % 6


@register.filter
def short_since(value):
    """How long ago, in one unit — "prieš 3 d.", not "3 dienos, 4 valandos".

    Activity feeds are scanned, not read: one unit is enough, and the exact
    stamp stays in the element's title attribute. The wording goes through the
    CRM's own catalogue (not Django's) so it stays editable in Settings →
    Vertimai like every other string.
    """
    if not value:
        return ""
    from django.utils import timezone
    from django.utils.translation import gettext

    seconds = (timezone.now() - value).total_seconds()
    if seconds < 60:
        return gettext("ką tik")
    for limit, divisor, phrase in (
        (3600, 60, gettext("prieš %(count)s min.")),
        (86400, 3600, gettext("prieš %(count)s val.")),
        (2592000, 86400, gettext("prieš %(count)s d.")),
        (31536000, 2592000, gettext("prieš %(count)s mėn.")),
    ):
        if seconds < limit:
            return phrase % {"count": int(seconds // divisor)}
    return gettext("prieš %(count)s m.") % {"count": int(seconds // 31536000)}
