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
def user_initials(user):
    initials = f"{(user.first_name or '')[:1]}{(user.last_name or '')[:1]}".strip()
    return (initials or user.get_username()[:2]).upper()
