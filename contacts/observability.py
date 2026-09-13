"""Structured logs for a SIEM, correlated by request id.

* ``RequestIdMiddleware`` gives every request an id — the caller's ``X-Request-ID``
  when it looks sane (a reverse proxy or load balancer usually sets one), else a
  fresh one — and returns it in the response header.
* ``JsonFormatter`` writes one JSON object per line with that id attached, so web,
  worker and access logs can be joined with the audit trail (which stores the
  same id in ``detail.request_id``).
* ``security_event`` is the single place security-relevant events are logged, to
  the ``crm.security`` logger. It carries ids, types and IP — never names, values
  or other personal data from the records themselves.
"""
import json
import logging
import re
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

from django.core.signals import request_finished

_request_id = ContextVar("crm_request_id", default="")
_VALID_ID = re.compile(r"^[A-Za-z0-9._-]{8,128}$")

security_logger = logging.getLogger("crm.security")

# Structured fields copied from a record's ``extra`` into the JSON line.
EXTRA_FIELDS = ("event", "action", "actor_id", "target_type", "target_id", "field", "ip", "outcome", "reason",
                "method", "path", "status")


def current_request_id():
    return _request_id.get()


class RequestIdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if _VALID_ID.match(incoming) else uuid.uuid4().hex
        request.request_id = request_id
        # Cleared on request_finished, not here: Django logs "Not Found" and 5xx
        # responses after the middleware chain has returned.
        _request_id.set(request_id)
        response = self.get_response(request)
        response["X-Request-ID"] = request_id
        return response


def _clear_request_id(**kwargs):
    _request_id.set("")


request_finished.connect(_clear_request_id, dispatch_uid="crm-clear-request-id")


class RequestIdFilter(logging.Filter):
    def filter(self, record):
        record.request_id = getattr(record, "request_id", "") or current_request_id()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", "")
        if request_id:
            payload["request_id"] = request_id
        for name in EXTRA_FIELDS:
            value = getattr(record, name, None)
            if value not in (None, ""):
                payload[name] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def security_event(event, *, level=logging.INFO, **fields):
    """Log one security event. Pass only ids, types, outcomes and IPs."""
    extra = {name: fields[name] for name in EXTRA_FIELDS if fields.get(name) not in (None, "")}
    extra["event"] = event
    security_logger.log(level, event, extra=extra)
