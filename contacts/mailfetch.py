"""Pull messages from the CRM dropbox mailbox and file them as email activities (G6).

Users BCC the CRM address; the periodic worker calls :func:`fetch`. Matching:
a contact is found by any To/Cc address, the author by the From address (falling
back to the oldest active admin). Unmatched messages land in ``IncomingMail`` for
an admin to assign. Deduplication is by RFC ``Message-ID``.
"""
import email
import re
from email.header import decode_header, make_header
from email.utils import getaddresses, parsedate_to_datetime

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.utils import timezone

ATTACH_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".pdf", ".txt",
              ".doc", ".docx", ".xls", ".xlsx"}
ATTACH_MAX = 10 * 1024 * 1024


def _dec(value):
    try:
        return str(make_header(decode_header(value or "")))
    except Exception:
        return value or ""


def _addrs(msg, *headers):
    raw = []
    for header in headers:
        raw += msg.get_all(header, [])
    return [addr.lower() for _name, addr in getaddresses(raw) if addr]


def _body(msg):
    parts = msg.walk() if msg.is_multipart() else [msg]
    html = ""
    for part in parts:
        ctype = part.get_content_type()
        disp = str(part.get("Content-Disposition", ""))
        if "attachment" in disp:
            continue
        try:
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            text = payload.decode(part.get_content_charset() or "utf-8", "replace")
        except Exception:
            continue
        if ctype == "text/plain":
            return text
        if ctype == "text/html" and not html:
            html = re.sub(r"<[^>]+>", " ", text)
    return html


def _default_author():
    User = get_user_model()
    return (User.objects.filter(is_active=True, is_superuser=True).order_by("pk").first()
            or User.objects.filter(is_active=True).order_by("pk").first())


def _save_attachments(msg, activity):
    from .models import Attachment
    import os

    if not msg.is_multipart():
        return
    for part in msg.walk():
        name = _dec(part.get_filename())
        if not name or "attachment" not in str(part.get("Content-Disposition", "")):
            continue
        if os.path.splitext(name)[1].lower() not in ATTACH_EXT:
            continue
        payload = part.get_payload(decode=True) or b""
        if not payload or len(payload) > ATTACH_MAX:
            continue
        Attachment.objects.create(
            activity=activity, file=ContentFile(payload, name=name[:255]),
            original_name=name[:255], content_type=part.get_content_type() or "", size=len(payload),
        )


def process_message(raw):
    """Parse and file one raw RFC822 message.
    Returns 'activity' / 'unmatched' / 'duplicate' / 'skipped'."""
    from .models import Activity, IncomingMail, Person

    msg = email.message_from_bytes(raw)
    message_id = _dec(msg.get("Message-ID")).strip()[:255]
    if not message_id:
        return "skipped"
    if (Activity.objects.filter(message_id=message_id).exists()
            or IncomingMail.objects.filter(message_id=message_id).exists()):
        return "duplicate"

    subject = _dec(msg.get("Subject"))[:500]
    body = (_body(msg) or "").strip()
    from_list = _addrs(msg, "From")
    from_addr = (from_list[0] if from_list else "unknown")[:320]
    recipients = _addrs(msg, "To", "Cc")
    try:
        received = parsedate_to_datetime(msg.get("Date"))
        received = received if received and received.tzinfo else timezone.now()
    except Exception:
        received = timezone.now()

    own = (settings.IMAP_USER or "").lower()
    candidates = [addr for addr in recipients if addr and addr != own]
    person = Person.objects.filter(deleted_at__isnull=True, emails__email__in=candidates).distinct().first()
    User = get_user_model()
    author = User.objects.filter(is_active=True, email__iexact=from_addr).first() or _default_author()

    if person and author:
        activity = Activity.objects.create(
            person=person, activity_type=Activity.EMAIL,
            text=((subject + "\n\n" + body).strip() or "(be teksto)")[:9000],
            created_by=author, message_id=message_id,
        )
        _save_attachments(msg, activity)
        return "activity"

    IncomingMail.objects.create(
        message_id=message_id, from_addr=from_addr, to_addrs=", ".join(recipients)[:1000],
        subject=subject, body=body[:9000], received_at=received,
    )
    return "unmatched"


def fetch():
    if not settings.IMAP_HOST:
        return {}
    import imaplib

    counts = {}
    conn = imaplib.IMAP4_SSL(settings.IMAP_HOST, settings.IMAP_PORT)
    try:
        conn.login(settings.IMAP_USER, settings.IMAP_PASSWORD)
        conn.select(settings.IMAP_FOLDER)
        _typ, data = conn.search(None, "UNSEEN")
        for num in (data[0] or b"").split():
            _typ, msg_data = conn.fetch(num, "(RFC822)")
            raw = next((part[1] for part in msg_data if isinstance(part, tuple)), None)
            if raw is None:
                continue
            outcome = process_message(raw)
            counts[outcome] = counts.get(outcome, 0) + 1
            conn.store(num, "+FLAGS", "\\Seen")
    finally:
        try:
            conn.logout()
        except Exception:
            pass
    return counts
