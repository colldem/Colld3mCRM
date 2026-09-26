"""Pull messages from the CRM dropbox mailbox and file them as email activities (G6).

Users BCC the CRM address; the periodic worker calls :func:`fetch`. Matching:
a contact is found by any To/Cc address, the author by the From address (falling
back to the oldest active admin). Unmatched messages land in ``IncomingMail`` for
an admin to assign, and so does a message whose sender the receiving server
could not authenticate (:func:`sender_failed_authentication`): the From header
is the sender's to write, and it decides whose name the activity carries.
Deduplication is by RFC ``Message-ID``.
"""
import email
import re
from email.header import decode_header, make_header
from email.utils import getaddresses, parsedate_to_datetime

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


_AUTH_RESULT = re.compile(r"\b(dmarc|compauth|spf|dkim)\s*=\s*([a-z]+)", re.I)


def sender_failed_authentication(msg):
    """True when the receiving mail server says the From address was forged.

    Only the topmost Authentication-Results header counts: the receiving server
    adds it above everything the sender wrote. A DMARC or Microsoft composite
    (compauth) failure, or an SPF failure no DKIM signature makes up for, is a
    failure. No header, or "none", is not: many internal messages carry no
    verdict at all, and those are what the CRM mailbox mostly receives.
    """
    headers = msg.get_all("Authentication-Results") or []
    if not headers:
        return False
    verdicts = {}
    for method, result in _AUTH_RESULT.findall(str(headers[0])):
        verdicts.setdefault(method.lower(), set()).add(result.lower())
    if "fail" in verdicts.get("dmarc", set()) or "fail" in verdicts.get("compauth", set()):
        return True
    return bool(verdicts.get("spf", set()) & {"fail", "softfail"}) and "pass" not in verdicts.get("dkim", set())


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
        # An undecodable part is skipped; the next one may do.
        except Exception:  # nosec B112
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
        from io import BytesIO

        from .antivirus import check_upload

        if not check_upload(BytesIO(payload), name=name, source="incoming_mail"):
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

    from .integrations import imap_config

    own = (imap_config().user or "").lower()
    candidates = [addr for addr in recipients if addr and addr != own]
    person = Person.objects.filter(deleted_at__isnull=True, emails__email__in=candidates).distinct().first()
    if person and sender_failed_authentication(msg):
        # Held for an admin, who sees the claimed sender, instead of filed under a colleague's name.
        from .observability import security_event

        security_event("mail.sender_unauthenticated", target_type="incoming_mail", outcome="held")
        person = None
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
    from .integrations import imap_config

    cfg = imap_config()
    if not cfg.active:
        return {}
    import imaplib

    counts = {}
    conn = imaplib.IMAP4_SSL(cfg.host, cfg.port)
    try:
        conn.login(cfg.user, cfg.password)
        conn.select(cfg.folder)
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
        # The session is being torn down anyway.
        except Exception:  # nosec B110
            pass
    return counts
