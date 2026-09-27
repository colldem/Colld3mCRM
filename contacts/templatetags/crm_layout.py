"""Template side of the personal page layouts (contacts/layouts.py).

    <div class="record-detail" data-layout="person">
      {% layout "person" %}
        <div class="rec-main" data-layout-zone="main">{% layoutzone "main" %}
          {% layoutblock "contact" _("Kontaktinė informacija") %}<section>…</section>{% endlayoutblock %}
        {% endlayoutzone %}</div>
      {% endlayout %}
    </div>

The template order is the default. A zone draws its blocks in the user's
order, and may draw a block written in another zone of the same layout, so
blocks sit directly in their zone, never inside a ``{% for %}`` or ``{% with %}``
of their own. A switched-off block is not rendered at all. The block's first
element receives ``data-layout-item``; static/js/layout.js does the rest.
"""
import re

from django import template
from django.template.base import Node
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe

from contacts.layouts import arrange, arrange_fields, saved_layout

register = template.Library()

_FIRST_TAG = re.compile(r"^(<[a-zA-Z][a-zA-Z0-9-]*)")


def _user(context):
    request = context.get("request")
    return getattr(request, "user", None)


def _markers(hidden):
    """The switched-off entries, for the "show again" list in edit mode."""
    return format_html_join("", '<template data-layout-hidden="{}" data-layout-label="{}"></template>', hidden)


def _find(nodelist, kind):
    """Nodes of `kind` in this layout, not looking into nested layouts or blocks."""
    found = []
    for node in nodelist:
        if isinstance(node, kind):
            found.append(node)
        elif not isinstance(node, (LayoutNode, LayoutBlockNode)):
            for attr in node.child_nodelists:
                child = getattr(node, attr, None)
                if child:
                    found.extend(_find(child, kind))
    return found


class LayoutNode(Node):
    def __init__(self, key, nodelist):
        self.key, self.nodelist = key, nodelist
        self.zones = _find(nodelist, LayoutZoneNode)

    def render(self, context):
        key = self.key.resolve(context)
        blocks = {block.name: block for zone in self.zones for block in zone.blocks}
        zones, hidden = arrange(saved_layout(_user(context), key),
                                {zone.name: [block.name for block in zone.blocks] for zone in self.zones})
        markers = _markers((name, blocks[name].label.resolve(context)) for name in hidden)
        with context.push(crm_layout_zones=zones, crm_layout_blocks=blocks):
            return markers + self.nodelist.render(context)


class LayoutZoneNode(Node):
    def __init__(self, name, nodelist):
        self.name, self.nodelist = name, nodelist
        self.blocks = _find(nodelist, LayoutBlockNode)

    def render(self, context):
        blocks = context.get("crm_layout_blocks", {})
        names = context.get("crm_layout_zones", {}).get(self.name, [])
        return format_html_join("", "{}", ((blocks[name].render(context),) for name in names))


class LayoutBlockNode(Node):
    def __init__(self, name, label, nodelist):
        self.name, self.label, self.nodelist = name, label, nodelist

    def render(self, context):
        html = self.nodelist.render(context)  # already safe: the template's own escaped output
        if not html.strip():
            return ""
        attrs = format_html(' data-layout-item="{}" data-layout-label="{}"', self.name, self.label.resolve(context))
        if not _FIRST_TAG.match(html.lstrip()):
            return format_html("<div{}>{}</div>", attrs, html)
        # Escaped attributes spliced into that output, after the first tag name.
        return mark_safe(_FIRST_TAG.sub(lambda match: match.group(1) + attrs, html.lstrip(), count=1))  # nosec B308 B703


def _name(bits, index, tag):
    if len(bits) <= index or bits[index][0] not in "\"'" or bits[index][0] != bits[index][-1]:
        raise template.TemplateSyntaxError("%s needs a quoted name" % tag)
    return bits[index][1:-1]


@register.tag("layout")
def do_layout(parser, token):
    bits = token.split_contents()
    if len(bits) != 2:
        raise template.TemplateSyntaxError("layout takes one argument, the layout key")
    nodelist = parser.parse(("endlayout",))
    parser.delete_first_token()
    return LayoutNode(parser.compile_filter(bits[1]), nodelist)


@register.tag("layoutzone")
def do_layoutzone(parser, token):
    bits = token.split_contents()
    name = _name(bits, 1, "layoutzone")
    nodelist = parser.parse(("endlayoutzone",))
    parser.delete_first_token()
    return LayoutZoneNode(name, nodelist)


@register.tag("layoutblock")
def do_layoutblock(parser, token):
    bits = token.split_contents()
    if len(bits) != 3:
        raise template.TemplateSyntaxError("layoutblock takes a quoted id and a label")
    name = _name(bits, 1, "layoutblock")
    nodelist = parser.parse(("endlayoutblock",))
    parser.delete_first_token()
    return LayoutBlockNode(name, parser.compile_filter(bits[2]), nodelist)


@register.simple_tag(takes_context=True)
def layoutfields(context, items, key):
    """Card fields in the user's order: ``{% layoutfields contact_info_fields "person.contact" as lines %}``."""
    return arrange_fields(_user(context), key, items)


@register.simple_tag
def layouthidden(arranged):
    return _markers(arranged.hidden)
