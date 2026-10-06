"""Site-wide views: the health check and the CSRF failure page."""

from django.http import HttpRequest, HttpResponse
from django.views.csrf import csrf_failure as default_csrf_failure


def healthz(request: HttpRequest) -> HttpResponse:
    """Render's health check: no sign-in and no database query."""
    return HttpResponse("ok", content_type="text/plain")


def csrf_failure(request: HttpRequest, reason: str = "") -> HttpResponse:
    """Django's CSRF failure page, marked so the outbox can tell it apart.

    A queued write can carry a CSRF token that went stale while it waited
    (the user signed in again in another tab). The outbox keeps a 403
    with ``X-CSRF-Failure`` and retries after the next page load refreshes
    the token, rather than throwing the write away as forbidden.
    """
    response = default_csrf_failure(request, reason=reason)
    response["X-CSRF-Failure"] = "1"
    return response
