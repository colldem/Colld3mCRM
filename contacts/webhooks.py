"""Outbound webhooks (H4).

``emit(event, obj)`` queues a :class:`WebhookDelivery` for every active webhook
subscribed to ``event`` — it never makes an HTTP call, so it is safe to run from
a signal inside a request. ``deliver_pending()`` (the worker) does the POSTs:
JSON body, ``X-CRM-Signature: sha256=<hmac>`` header, 10 s timeout, exponential
backoff, and auto-disable after a long failure streak.
"""
import hashlib
import hmac
import ipaddress
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import Webhook, WebhookDelivery

MAX_ATTEMPTS = 6
BACKOFF_SECONDS = [60, 300, 900, 3600, 10800, 21600]
AUTO_DISABLE_STREAK = 20
RETENTION_DAYS = 30
BATCH = 200


def _serializer(kind):
    from . import api

    return {"contact": api.serialize_person, "company": api.serialize_company,
            "activity": api.serialize_activity, "reminder": api.serialize_reminder}[kind]


def emit(event, obj):
    if settings.CRM_ISOLATED:  # a clone must not queue deliveries to real endpoints
        return
    hooks = [h for h in Webhook.objects.filter(active=True) if event in (h.events or [])]
    if not hooks:
        return
    try:
        data = _serializer(event.split(".")[0])(obj)
    except Exception:  # a serializer error must never break the write that triggered us
        return
    payload = {"event": event, "occurred_at": timezone.now().isoformat(), "data": data}
    now = timezone.now()
    WebhookDelivery.objects.bulk_create(
        [WebhookDelivery(webhook=hook, event=event, payload=payload, next_attempt_at=now) for hook in hooks])


def _sign(secret, body):
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A webhook target that 3xx-redirects could point the request at an
    internal host after the safety check — so we refuse to follow redirects."""

    def redirect_request(self, *args, **kwargs):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def target_is_allowed(url):
    """Reject loopback and link-local (cloud metadata) targets. Private LAN
    ranges are allowed on purpose — legitimate internal webhooks are common
    in this single-tenant deployment."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror:
        return True  # unresolvable now; let the delivery attempt fail normally
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast:
            return False
    return True


def post_once(webhook, event, payload):
    """Deliver one payload now. Returns (ok, status_text)."""
    from .crypto import decrypt

    if settings.CRM_ISOLATED:
        # A restored production dump brings its own queue of pending deliveries;
        # refuse here too so they can never go out from a clone.
        return False, "isolated tier"
    if not target_is_allowed(webhook.target_url):
        return False, "blocked target"
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json", "X-CRM-Event": event}
    secret = decrypt(webhook.secret)
    if secret:
        headers["X-CRM-Signature"] = _sign(secret, body)
    request = urllib.request.Request(webhook.target_url, data=body, headers=headers, method="POST")
    try:
        with _OPENER.open(request, timeout=10) as response:
            code = response.status
        return 200 <= code < 300, str(code)
    except urllib.error.HTTPError as error:
        return False, "HTTP %s" % error.code
    except Exception as error:
        return False, type(error).__name__


def deliver_pending(now=None):
    now = now or timezone.now()
    WebhookDelivery.objects.filter(created_at__lt=now - timedelta(days=RETENTION_DAYS)).delete()
    pending = (WebhookDelivery.objects
               .filter(delivered_at__isnull=True, next_attempt_at__lte=now)
               .select_related("webhook")[:BATCH])
    sent = 0
    for delivery in pending:
        ok, status = post_once(delivery.webhook, delivery.event, delivery.payload)
        delivery.attempts += 1
        if ok:
            delivery.delivered_at = now
            delivery.status = status
            Webhook.objects.filter(pk=delivery.webhook_id).update(
                failure_streak=0, last_delivery_at=now, last_status="ok %s" % status)
            sent += 1
        elif delivery.attempts >= MAX_ATTEMPTS:
            delivery.status = "failed: %s" % status
            streak = delivery.webhook.failure_streak + 1
            Webhook.objects.filter(pk=delivery.webhook_id).update(
                failure_streak=streak, last_delivery_at=now, last_status="failed: %s" % status,
                active=delivery.webhook.active and streak < AUTO_DISABLE_STREAK)
        else:
            delivery.status = "retry: %s" % status
            delivery.next_attempt_at = now + timedelta(
                seconds=BACKOFF_SECONDS[min(delivery.attempts, len(BACKOFF_SECONDS) - 1)])
        delivery.save()
    return sent
