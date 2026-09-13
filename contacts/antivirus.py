"""Malware scanning of uploaded files through a ClamAV daemon (clamd).

Turned on by ``CRM_CLAMAV_HOST`` (compose.clamav.yaml runs one). Every file that
enters the CRM — record attachments, attachments of fetched e-mail, avatars,
import and translation files — passes ``check_upload`` before it is stored or
parsed. Speaks clamd's INSTREAM protocol directly, so there is no extra library.

``CRM_CLAMAV_REQUIRED`` (default true) decides what happens when the scanner
cannot be reached: refuse the file (fail closed) or accept it with a warning.
Detections and outages are audited / logged to ``crm.security``.
"""
import logging
import socket
import struct
from dataclasses import dataclass

from django.conf import settings

CHUNK = 64 * 1024


class ScanUnavailable(Exception):
    """The scanner could not give a verdict."""


@dataclass
class Verdict:
    clean: bool
    signature: str = ""


def enabled():
    return bool(getattr(settings, "CRM_CLAMAV_HOST", ""))


def scan_stream(chunks):
    """Send ``chunks`` (an iterable of bytes) to clamd and return its verdict."""
    try:
        with socket.create_connection((settings.CRM_CLAMAV_HOST, settings.CRM_CLAMAV_PORT),
                                      timeout=settings.CRM_CLAMAV_TIMEOUT) as connection:
            connection.sendall(b"zINSTREAM\0")
            for chunk in chunks:
                if chunk:
                    connection.sendall(struct.pack("!L", len(chunk)) + chunk)
            connection.sendall(struct.pack("!L", 0))
            reply = b""
            while not reply.endswith(b"\0"):
                data = connection.recv(4096)
                if not data:
                    break
                reply += data
    except OSError as error:
        raise ScanUnavailable(str(error)) from None
    text = reply.rstrip(b"\0").decode("utf-8", "replace").strip()
    if text.endswith(" OK"):
        return Verdict(clean=True)
    if text.endswith(" FOUND"):
        return Verdict(clean=False, signature=text.split(":", 1)[-1].rsplit(" ", 1)[0].strip())
    raise ScanUnavailable(text or "empty reply")


def scan_file(fileobj):
    """Scan a file-like object from its start and rewind it afterwards."""
    if hasattr(fileobj, "seek"):
        fileobj.seek(0)

    def chunks():
        if hasattr(fileobj, "chunks"):
            yield from fileobj.chunks(CHUNK)
        else:
            while True:
                data = fileobj.read(CHUNK)
                if not data:
                    return
                yield data

    try:
        return scan_stream(chunks())
    finally:
        if hasattr(fileobj, "seek"):
            fileobj.seek(0)


def check_upload(fileobj, *, name, source, request=None):
    """True when the file may be stored; audits and logs anything else."""
    if not enabled():
        return True
    from .audit import log as audit_log
    from .models import AuditLog
    from .observability import security_event

    try:
        verdict = scan_file(fileobj)
    except ScanUnavailable as error:
        required = settings.CRM_CLAMAV_REQUIRED
        security_event("upload.scan_unavailable", level=logging.ERROR if required else logging.WARNING,
                       target_type="upload", reason=str(error)[:200],
                       outcome="refused" if required else "accepted_unscanned")
        return not required
    if verdict.clean:
        return True
    security_event("upload.malware", level=logging.WARNING, target_type="upload", reason=verdict.signature[:200],
                   outcome="refused")
    audit_log(AuditLog.UPDATE, request=request, target_type="upload", target_label=str(name)[:255],
              field="antivirus", new="refused", detail={"reason": "malware", "signature": verdict.signature,
                                                        "source": source})
    return False
