"""Idempotency-Key request deduplication.

The server half of the offline outbox (docs/pwa.md). A state-changing
request (POST, PUT, PATCH, DELETE) carrying an ``Idempotency-Key`` header
runs at most once per key for 24 hours; a repeat gets the first response
back, marked ``Idempotent-Replayed: true``, without the view running again.

- Middleware rather than a decorator, so a new view can't forget it.
- Reserve, then execute: the key is claimed atomically before the view
  runs. A request that loses the claim never reaches the view; it gets
  the stored reply, or a 409 while the first request is still running.
- 5xx and streaming responses are not stored, so a retry runs the view.
- A repeat must match the original's method, path, user and body hash;
  otherwise it is a 409, never another request's response.
- A state-changing request without a key passes straight through, so plain
  HTML forms keep working.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from datetime import timedelta

from django.http import HttpRequest, HttpResponse

logger = logging.getLogger(__name__)

STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
MAX_KEY_LENGTH = 128
TTL = timedelta(hours=24)


class IdempotencyMiddleware:
    """Run each keyed state-changing request at most once."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Pass the request on, replay it, or refuse it (see the module docstring)."""
        key = request.headers.get("Idempotency-Key", "").strip()
        if request.method not in STATE_CHANGING_METHODS or not key:
            return self.get_response(request)
        if len(key) > MAX_KEY_LENGTH or not (key.isascii() and key.isprintable()):
            return HttpResponse("Malformed Idempotency-Key", status=400)

        from apps.core.models import IdempotencyRecord

        fingerprint = {
            "method": request.method or "",
            "path": request.path,
            "principal": _principal(request),
            "body_hash": hashlib.sha256(request.body).hexdigest(),
        }
        record, claimed = IdempotencyRecord.objects.reserve(key=key, ttl=TTL, **fingerprint)

        if not claimed or record is None:
            if record is None or not record.matches(**fingerprint):
                logger.warning("idempotency.conflict key=%s…", key[:8])
                return HttpResponse(status=409)
            if not record.is_completed():
                # The first request with this key is still in the view; the
                # outbox treats a 409 with Retry-After as "try again soon".
                busy = HttpResponse(status=409)
                busy["Retry-After"] = "1"
                return busy
            logger.info("idempotency.replay key=%s…", key[:8])
            return record.build_response()

        try:
            response = self.get_response(request)
        except Exception:
            record.release()
            raise
        if response.status_code >= 500 or getattr(response, "streaming", False):
            record.release()
        else:
            record.complete(response=response, ttl=TTL)
        return response


def _principal(request: HttpRequest) -> str:
    """Return the requester's pk as a string, or '' when signed out."""
    user = getattr(request, "user", None)
    return str(user.pk) if user is not None and user.is_authenticated else ""
