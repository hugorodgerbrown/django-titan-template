"""Tests for titan.app: the names derived from a slug, and the shared group."""

from __future__ import annotations

import dataclasses

import pytest

from titan import TitanError
from titan.app import APP_KEYS, App, common_env
from titan.credentials import Settings


def test_names_derive_from_the_slug(app: App) -> None:
    """Every name comes from the slug."""
    assert app.name == "Tally"
    assert app.domain == "tally.ultraniche.ai"
    assert app.from_email == "Tally <tally@mail.ultraniche.ai>"
    assert app.repo == "hugorodgerbrown/tally"
    assert (app.web_service, app.cron_service, app.group) == ("tally", "tally-purge", "tally")


def test_hyphens_become_underscores_in_postgres(settings: Settings) -> None:
    """Postgres names read better without hyphens."""
    app = App.from_slug("resort-planner", settings)
    assert app.db_name == "resort_planner"
    assert app.name == "Resort Planner"


def test_display_name_with_a_comma_is_quoted(settings: Settings) -> None:
    """The sender's display name is quoted when it needs to be."""
    app = App.from_slug("notes", settings, name="Hugo, Notes")
    assert app.from_email == '"Hugo, Notes" <notes@mail.ultraniche.ai>'


@pytest.mark.parametrize("slug", ["Tally", "1app", "my_app", "", "app.x"])
def test_bad_slugs_are_refused(settings: Settings, slug: str) -> None:
    """The template's own slug rule."""
    with pytest.raises(TitanError):
        App.from_slug(slug, settings)


def test_database_url_uses_the_internal_host_and_quotes_the_password(app: App) -> None:
    """Services connect over the internal host; the password is URL-quoted."""
    assert app.database_url("a/b+c") == "postgresql://tally:a%2Fb%2Bc@dpg-abc123-a:5432/tally"


def test_internal_host_can_be_overridden(settings: Settings) -> None:
    """TITAN_DB_INTERNAL_HOST wins over the first label of the external host."""
    app = App.from_slug("tally", dataclasses.replace(settings, db_internal_host="db.internal"))
    assert app.database_url("pw").startswith("postgresql://tally:pw@db.internal:5432/")


def test_blueprint_link_points_at_the_repo(app: App) -> None:
    """Render's one-click deploy link for the repo."""
    assert (
        app.blueprint_link()
        == "https://render.com/deploy?repo=https://github.com/hugorodgerbrown/tally"
    )


def test_the_shared_group_covers_every_app_under_the_domain(settings: Settings) -> None:
    """Hosts and origins are wildcards under the parent domain, and no key is an app's."""
    env = common_env(dataclasses.replace(settings, domain="example.com"))
    assert env["DJANGO_ALLOWED_HOSTS"] == ".example.com"
    assert env["DJANGO_CSRF_TRUSTED_ORIGINS"] == "https://*.example.com"
    assert env["DJANGO_DEBUG"] == "0"
    assert not set(env) & set(APP_KEYS)
