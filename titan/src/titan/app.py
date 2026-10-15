"""Every name titan derives from an app's slug, and the two env groups.

Each app's services link two Render environment groups, both made by
titan and neither declared in render.yaml (so a Blueprint sync never
overwrites them):

* ``titan``: settings every Titan app shares (debug off, Python version,
  allowed hosts and trusted origins under the parent domain, the SMTP
  relay). titan adds missing keys and never overwrites one that was
  changed in the dashboard.
* ``<slug>``: the app's own values (its database URL, secret key, mail key
  and sender, and SITE_URL and FIVEBAR_DOMAIN at go-live).

A key belongs to one group only. To override a shared value for one app,
set it on the service itself: Render gives a service's own env vars
precedence over its groups'.
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from email.utils import formataddr

from titan import TitanError
from titan.credentials import Settings

SLUG = re.compile(r"^[a-z][a-z0-9-]*$")
COMMON_GROUP = "titan"
# The keys an app's own group holds; nothing else goes in it.
APP_KEYS = (
    "DATABASE_URL",
    "DJANGO_SECRET_KEY",
    # Keys every account's email address; never regenerated (docs/accounts.md).
    "ACCOUNTS_EMAIL_KEY",
    "EMAIL_HOST_PASSWORD",
    "DEFAULT_FROM_EMAIL",
    "SITE_URL",
    # The site's domain in fivebar, which turns the visitor counts on.
    "FIVEBAR_DOMAIN",
)
# Where a site is added to fivebar by hand, when titan has no token to do it.
FIVEBAR_SITES = "https://fiveb.ar/sites"


def common_env(settings: Settings) -> dict[str, str]:
    """The shared group's values. The hosts cover every app under the parent domain."""
    return {
        "DJANGO_DEBUG": "0",
        "PYTHON_VERSION": "3.14",
        # The service's own onrender.com name is added by the settings
        # (RENDER_EXTERNAL_HOSTNAME); these cover the custom domains.
        "DJANGO_ALLOWED_HOSTS": f".{settings.domain}",
        "DJANGO_CSRF_TRUSTED_ORIGINS": f"https://*.{settings.domain}",
        "EMAIL_HOST": "smtp.resend.com",
        "EMAIL_PORT": "587",
        "EMAIL_HOST_USER": "resend",
        "EMAIL_USE_TLS": "True",
    }


@dataclass(frozen=True)
class App:
    """Every name derived from the app's slug."""

    slug: str
    name: str
    settings: Settings

    @classmethod
    def from_slug(cls, slug: str, settings: Settings, name: str = "") -> App:
        """Validate the slug (the template's own rule) and derive the rest."""
        if not SLUG.match(slug):
            raise TitanError(
                f"{slug!r}: lowercase letters, digits and hyphens, starting with a letter."
            )
        return cls(slug=slug, name=name or slug.replace("-", " ").title(), settings=settings)

    @property
    def domain(self) -> str:
        """The app's public host, e.g. tally.ultraniche.ai."""
        return f"{self.slug}.{self.settings.domain}"

    @property
    def db_name(self) -> str:
        """Role and database name: Postgres identifiers read better without hyphens."""
        return self.slug.replace("-", "_")

    @property
    def from_email(self) -> str:
        """DEFAULT_FROM_EMAIL, e.g. Tally <tally@mail.ultraniche.ai>."""
        return formataddr((self.name, f"{self.slug}@{self.settings.mail_domain}"))

    @property
    def repo(self) -> str:
        """owner/slug on GitHub."""
        return f"{self.settings.github_owner}/{self.slug}"

    @property
    def repo_url(self) -> str:
        """The repository's URL, as Render records it on a service."""
        return f"https://github.com/{self.repo}"

    @property
    def web_service(self) -> str:
        """The web service's name in render.yaml."""
        return self.slug

    @property
    def cron_service(self) -> str:
        """The clean-up cron job's name in render.yaml (optional)."""
        return f"{self.slug}-purge"

    @property
    def group(self) -> str:
        """The app's own env group."""
        return self.slug

    def database_url(self, password: str) -> str:
        """The internal connection URL Render services use."""
        admin = urllib.parse.urlsplit(self.settings.db_admin_url)
        host = self.settings.db_internal_host or (admin.hostname or "").split(".")[0]
        if not host:
            raise TitanError("TITAN_DB_ADMIN_URL has no host.")
        quoted = urllib.parse.quote(password, safe="")
        return f"postgresql://{self.db_name}:{quoted}@{host}:5432/{self.db_name}"

    def blueprint_link(self) -> str:
        """Render's deploy link for the repo's render.yaml."""
        return "https://render.com/deploy?repo=" + urllib.parse.quote(self.repo_url, safe=":/")
