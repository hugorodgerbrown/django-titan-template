"""Template context for the PWA shell (name, colours, version)."""

from django.conf import settings
from django.http import HttpRequest

from apps.pwa import conf


def pwa(request: HttpRequest) -> dict[str, dict[str, str]]:
    """Expose the app's identity to every template as ``pwa``."""
    return {
        "pwa": {
            "name": conf.APP_NAME,
            "theme_colour": conf.THEME_COLOUR,
            "background_colour": conf.BACKGROUND_COLOUR,
            "version": settings.APP_VERSION,
        }
    }
