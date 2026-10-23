"""The public pages. Placeholders to replace with the product's own words.

They sit outside the installed app's /app/ scope, so the service worker
never caches them and they never show inside the installed app.
"""

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.views.decorators.http import require_GET

from apps.core.shortcuts import render
from apps.public.connector import mcp_url


@require_GET
def home(request: HttpRequest) -> HttpResponse:
    """The front page (placeholder): what the app is, and the way in."""
    return render(request, "public/home.html", {"mcp_url": mcp_url()})


@require_GET
def terms(request: HttpRequest) -> HttpResponse:
    """The terms of service (placeholder)."""
    return render(request, "public/terms.html")


@require_GET
def privacy(request: HttpRequest) -> HttpResponse:
    """The privacy notice (placeholder, but true of the template as shipped)."""
    return render(request, "public/privacy.html", {"keeps_email": settings.ACCOUNTS_KEEP_EMAIL})


@require_GET
def help_page(request: HttpRequest) -> HttpResponse:
    """Help: signing in, passkeys, installing the app, offline (placeholder)."""
    return render(request, "public/help.html", {"mcp_url": mcp_url()})
