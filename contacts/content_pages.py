"""Internal pages: procedures, how-tos and FAQs written inside the CRM.

Whoever holds ``can_manage_pages`` writes them under Settings → Pages; everyone
reads the published ones their role is allowed to under Pages. The body is plain
text with a handful of markers, rendered here. Nothing the author types is ever
passed through as HTML:

    # Heading / ## Subheading / ### Small heading
    - bullet            1. numbered
    > a highlighted note
    **bold**  *italic*  `code`  [link text](https://… or /contacts/…)
    ``` on its own line opens and closes a block of code
"""
import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as tr

from .audit import log as audit_log
from .models import AuditLog, ContentPage
from .permissions import has_capability, role_of
from .sanitizers import safe_url


_HEADING = re.compile(r"^(#{1,3})\s+(.+)$")
_LIST_ITEM = ((re.compile(r"^[-*]\s+(?P<text>.+)$"), "ul"),
              (re.compile(r"^(?P<number>\d{1,9})[.)]\s+(?P<text>.+)$"), "ol"))
_QUOTE = re.compile(r"^>\s?(.*)$")
_CODE = re.compile(r"`([^`]+)`")
# Link text, link targets and italics stop at the next "[", "(" or "*": an
# open-ended match rescanned the rest of the line from every one of them, so a
# single long line took minutes to render. A target may hold one level of
# parentheses, as in https://lt.wikipedia.org/wiki/Vilnius_(miestas).
_LINK = re.compile(r"\[([^\[\]]+)\]\(((?:[^()\s]|\([^()\s]*\))+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![*\w])\*(?!\s)([^*]+?)(?<!\s)\*(?![*\w])")


def _href(raw):
    """A link target the page may carry: an address inside the CRM or an http(s) link."""
    if raw.startswith("/"):
        # "//host" and "/\host" both leave the site in a browser.
        if raw[1:2] in ("/", "\\") or "\\" in raw or any(ch < " " for ch in raw):
            return ""
        return raw
    return safe_url(raw)


def _emphasis(escaped):
    return _ITALIC.sub(r"<em>\1</em>", _BOLD.sub(r"<strong>\1</strong>", escaped))


def _inline(text):
    html = []
    for index, part in enumerate(_CODE.split(text)):
        if index % 2:
            html.append("<code>%s</code>" % escape(part))
            continue
        last = 0
        for match in _LINK.finditer(part):
            html.append(_emphasis(escape(part[last:match.start()])))
            label, href = _emphasis(escape(match.group(1))), _href(match.group(2))
            if href:
                rel = "" if href.startswith("/") else ' rel="noopener noreferrer"'
                html.append('<a href="%s"%s>%s</a>' % (escape(href), rel, label))
            else:
                html.append(label)
            last = match.end()
        html.append(_emphasis(escape(part[last:])))
    return "".join(html)


def render_body(text):
    """The page body as safe HTML."""
    out, paragraph, quote, items = [], [], [], []
    list_tag, list_start, code = None, 1, None

    def flush():
        nonlocal list_tag
        if paragraph:
            out.append("<p>%s</p>" % "<br>".join(_inline(line) for line in paragraph))
            paragraph.clear()
        if quote:
            out.append('<div class="doc-callout"><p>%s</p></div>' % "<br>".join(_inline(line) for line in quote))
            quote.clear()
        if items:
            # A numbered list keeps the author's first number: "3." shows as 3.
            start = ' start="%d"' % list_start if list_tag == "ol" and list_start != 1 else ""
            out.append("<%s%s>%s</%s>" % (list_tag, start, "".join("<li>%s</li>" % _inline(item) for item in items), list_tag))
            items.clear()
        list_tag = None

    for line in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.strip()
        if code is not None:
            if stripped.startswith("```"):
                out.append("<pre><code>%s</code></pre>" % escape("\n".join(code)))
                code = None
            else:
                code.append(line)
            continue
        if stripped.startswith("```"):
            flush()
            code = []
            continue
        if not stripped:
            flush()
            continue
        heading = _HEADING.match(stripped)
        if heading:
            flush()
            level = len(heading.group(1)) + 1  # the page title is the h1
            out.append("<h%d>%s</h%d>" % (level, _inline(heading.group(2)), level))
            continue
        item = next(((match, tag) for pattern, tag in _LIST_ITEM if (match := pattern.match(stripped))), None)
        if item:
            if item[1] != list_tag:
                flush()
                list_tag = item[1]
                list_start = int(item[0].group("number")) if list_tag == "ol" else 1
            items.append(item[0].group("text"))
            continue
        note = _QUOTE.match(stripped)
        if note:
            if not quote:
                flush()
            quote.append(note.group(1))
            continue
        if items or quote:
            flush()
        paragraph.append(stripped)
    if code is not None:
        out.append("<pre><code>%s</code></pre>" % escape("\n".join(code)))
    flush()
    # Every piece of the author's text went through escape() above.
    return mark_safe("\n".join(out))  # nosec B308 B703


def can_manage(user):
    return has_capability(user, "can_manage_pages")


def can_read(user, page):
    """Editors read every page, drafts included; others the published ones meant for their role."""
    if can_manage(user):
        return True
    return page.is_published and (not page.roles or role_of(user) in page.roles)


def readable_pages(user):
    # A handful of rows: the role is checked here because a JSON "contains"
    # lookup is not available on every database the CRM runs on.
    return [page for page in ContentPage.objects.all() if can_read(user, page)]


@login_required
def page_list(request):
    return render(request, "pages/list.html", {"pages": readable_pages(request.user),
                                               "can_manage_pages": can_manage(request.user)})


@login_required
def page_detail(request, slug):
    page = get_object_or_404(ContentPage.objects.select_related("updated_by"), slug=slug)
    if not can_read(request.user, page):
        raise Http404
    return render(request, "pages/detail.html", {"page": page, "body": render_body(page.body),
                                                 "can_manage_pages": can_manage(request.user)})


@login_required
def settings_pages(request):
    if not can_manage(request.user):
        raise Http404
    labels = dict(_role_choices())
    pages = list(ContentPage.objects.select_related("updated_by"))
    for page in pages:
        page.audience = ", ".join(str(labels[role]) for role in page.roles if role in labels)
    return render(request, "settings/pages.html", {"settings_section": "pages", "pages": pages})


def _role_choices():
    from .models import UserProfile

    return [(key, label) for key, label in UserProfile.ROLE_CHOICES if key != UserProfile.ROLE_ADMIN]


@login_required
def settings_page_edit(request, pk=None):
    from .forms import ContentPageForm

    if not can_manage(request.user):
        raise Http404
    page = get_object_or_404(ContentPage, pk=pk) if pk else None
    action = request.POST.get("action", "save")
    if request.method == "POST" and action == "delete":
        if page is None:
            raise Http404
        audit_log(AuditLog.DELETE, request=request, target_type="content_page", target_id=page.pk, target_label=page.title)
        page.delete()
        messages.success(request, tr("Puslapis pašalintas."))
        return redirect("contacts:settings-pages")
    form = ContentPageForm(request.POST or None, instance=page, role_choices=_role_choices())
    preview = None
    if request.method == "POST" and form.is_valid():
        if action == "preview":
            preview = render_body(form.cleaned_data["body"])
        else:
            changed = list(form.changed_data)
            saved = form.save(user=request.user)
            if page is None:
                audit_log(AuditLog.CREATE, request=request, target=saved, target_type="content_page")
                messages.success(request, tr("Puslapis sukurtas."))
            elif changed:
                audit_log(AuditLog.UPDATE, request=request, target=saved, target_type="content_page",
                          detail={"fields": changed})
                messages.success(request, tr("Puslapis išsaugotas."))
            return redirect("contacts:settings-pages")
    return render(request, "settings/page_edit.html", {
        "settings_section": "pages", "form": form, "page": page, "preview": preview,
    })
