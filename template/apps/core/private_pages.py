"""Keep signed-in pages out of the browser's HTTP cache.

A response to a signed-in user that doesn't say how to cache itself gets
``Cache-Control: no-store`` (Django's ``never_cache`` headers), so after
signing out, Back can't show the last user's pages and nothing has to be
cleared. This replaces ``Clear-Site-Data: "cache"`` on sign-out, which
Chrome takes many seconds to honour (it walks the whole disk cache) and so
held the redirect after signing out.

- Middleware rather than a decorator, so a new signed-in page, or one a
  package serves (mcp-auth's consent page), can't forget it.
- A view that sets its own ``Cache-Control`` keeps it.
- Pages the service worker caches for offline use (inside ``SCOPE`` and
  not in ``NEVER_CACHE``) are left alone: it refuses ``no-store``
  responses, and ``pwa.js`` deletes its copies before signing out.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from django.http import HttpRequest, HttpResponse
from django.utils.cache import add_never_cache_headers

from apps.pwa import conf

logger = logging.getLogger(__name__)


def _cached_offline(path: str) -> bool:
    """True when the service worker keeps a copy of this page for offline use."""
    if not path.startswith(conf.SCOPE):
        return False
    return not any(path.startswith(prefix) for prefix in conf.NEVER_CACHE)


class PrivatePagesMiddleware:
    """Mark signed-in responses ``no-store`` unless the view or the app chose otherwise."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        """Keep the next handler in the chain."""
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Add the never-cache headers to a signed-in user's uncached response."""
        response = self.get_response(request)
        if (
            request.user.is_authenticated
            and not response.has_header("Cache-Control")
            and not _cached_offline(request.path)
        ):
            add_never_cache_headers(response)
        return response
