"""The public pages. Placeholders to replace with the product's own words.

They sit outside the installed app's /app/ scope, so the service worker
never caches them and they never show inside the installed app.
"""

from datetime import timedelta
from typing import Any

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.public.connector import mcp_url

# The notes the front page draws with the app's own note list (DESIGN.md,
# "The front page": the product, live, with demo data). Minutes before now,
# so the demo never looks stale. Replace with the product's own.
DEMO_NOTES = [
    ("Call the plumber back about Thursday", 12),
    ("Milk, eggs, the good bread", 95),
    ("Book Saturday's table for six", 60 * 26),
]


def demo_notes() -> list[dict[str, Any]]:
    """Return the front page's demo notes, shaped like the notes it lists."""
    now = timezone.now()
    return [
        {"text": text, "written_at": now - timedelta(minutes=minutes)}
        for text, minutes in DEMO_NOTES
    ]


@require_GET
def home(request: HttpRequest) -> HttpResponse:
    """The front page: the promise, the product, the connector and the way in."""
    return render(request, "public/home.html", {"notes": demo_notes(), "mcp_url": mcp_url()})


@require_GET
def terms(request: HttpRequest) -> HttpResponse:
    """The terms of service (placeholder)."""
    return render(request, "public/terms.html")


@require_GET
def privacy(request: HttpRequest) -> HttpResponse:
    """The privacy notice (placeholder, but true of the template as shipped)."""
    return render(request, "public/privacy.html")


@require_GET
def help_page(request: HttpRequest) -> HttpResponse:
    """Help: signing in, passkeys, installing the app, offline (placeholder)."""
    return render(request, "public/help.html", {"mcp_url": mcp_url()})
