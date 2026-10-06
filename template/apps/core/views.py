"""Site-wide views: the home page and the health check."""

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.views.csrf import csrf_failure as default_csrf_failure


def healthz(request: HttpRequest) -> HttpResponse:
    """Render's health check: no sign-in and no database query."""
    return HttpResponse("ok", content_type="text/plain")


@login_required
def home(request: HttpRequest) -> HttpResponse:
    """Send a signed-in user to the app's main page (the manifest's start_url)."""
    return redirect("notes:list")


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
