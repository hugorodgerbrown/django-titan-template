"""Tests for apps.public.views: the homepage, terms, privacy and help."""

import re

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from apps.public import views
from apps.pwa import conf

pytestmark = pytest.mark.django_db


PAGES = ["public:home", "public:terms", "public:privacy", "public:help"]


@pytest.mark.parametrize("name", PAGES)
def test_public_pages_need_no_sign_in(client: Client, name: str) -> None:
    """Anyone can read them, and they link to each other."""
    response = client.get(reverse(name))
    assert response.status_code == 200
    content = response.content.decode()
    assert reverse("public:terms") in content
    assert reverse("public:privacy") in content
    assert reverse("public:help") in content


@pytest.mark.parametrize("name", PAGES)
def test_public_pages_are_outside_the_app(client: Client, name: str) -> None:
    """No manifest, worker or outbox: the installed app is /app/ alone."""
    content = client.get(reverse(name)).content.decode()
    assert "manifest" not in content
    assert "pwa.js" not in content


MCP_URL = "https://example.test/mcp"


@pytest.fixture
def with_mcp(monkeypatch: pytest.MonkeyPatch) -> str:
    """The front page and help as an app that serves /mcp sees them."""
    monkeypatch.setattr(views, "mcp_url", lambda: MCP_URL)
    return MCP_URL


@pytest.fixture
def without_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    """The front page and help as an app made without MCP sees them."""
    monkeypatch.setattr(views, "mcp_url", lambda: "")


def primary_actions(content: str) -> list[tuple[str, str]]:
    """The front page's primary actions, as (href, label): the block buttons."""
    pattern = r'<a class="button button--block" href="([^"]*)">([^<]*)</a>'
    return [(match[1], match[2]) for match in re.finditer(pattern, content)]


def test_home_has_one_promise(client: Client) -> None:
    """One H1, and it is the promise, not the app's name (the header says that)."""
    content = client.get(reverse("public:home")).content.decode()
    assert content.count("<h1") == 1
    h1 = re.search(r"<h1>(.*?)</h1>", content)
    assert h1
    assert h1.group(1) != conf.APP_NAME


def test_home_offers_one_way_in(client: Client) -> None:
    """Signed out, both primary actions go to sign in, onwards to the first job."""
    content = client.get(reverse("public:home")).content.decode()
    first_job = f"{reverse('accounts:sign_in')}?next={reverse('notes:list')}"
    actions = primary_actions(content)
    assert len(actions) == 2
    assert {href for href, _label in actions} == {first_job}
    assert len({label for _href, label in actions}) == 1
    assert "Create an account" not in content


def test_home_opens_the_app_when_signed_in(signed_in: Client) -> None:
    """Signed in, the header and both primary actions open the app instead."""
    content = signed_in.get(reverse("public:home")).content.decode()
    actions = primary_actions(content)
    assert actions == [(reverse("notes:list"), "Open the app")] * 2
    header = content[content.index("<header") : content.index("</header>")]
    assert "Open the app" in header
    assert "Sign in" not in content


def test_home_shows_the_product_with_demo_data(client: Client) -> None:
    """The app's own note list, drawn with demo notes, not a picture of it."""
    content = client.get(reverse("public:home")).content.decode()
    assert 'class="showcase"' in content
    assert 'class="note-list"' in content
    for text, _minutes in views.DEMO_NOTES:
        assert escape(text) in content


def test_demo_notes_are_recent() -> None:
    """Written minutes before now, so the demo never looks stale."""
    notes = views.demo_notes()
    assert len(notes) == len(views.DEMO_NOTES)
    assert all(note["written_at"] <= timezone.now() for note in notes)
    assert all(note["written_at"].tzinfo is not None for note in notes)


def test_home_shows_the_connector(client: Client, with_mcp: str) -> None:
    """With MCP: a sample chat, things to ask, the address to copy and the steps' link."""
    content = client.get(reverse("public:home")).content.decode()
    assert 'class="chat"' in content
    assert 'class="asks"' in content
    assert f'data-copy="{with_mcp}"' in content
    assert f'href="{reverse("public:help")}#use-with-ai"' in content
    assert "js/copy.js" in content


def test_home_leaves_the_connector_out_without_mcp(client: Client, without_mcp: None) -> None:
    """An app made without MCP has no AI-chat section."""
    content = client.get(reverse("public:home")).content.decode()
    assert 'class="chat"' not in content
    assert "data-copy" not in content


def test_help_gives_the_steps_for_claude_and_chatgpt(client: Client, with_mcp: str) -> None:
    """The steps every Titan app shares, around the address to copy."""
    content = client.get(reverse("public:help")).content.decode()
    assert 'id="use-with-ai"' in content
    assert "<h3>Claude</h3>" in content
    assert "<h3>ChatGPT</h3>" in content
    assert f'data-copy="{with_mcp}"' in content


def test_help_leaves_the_steps_out_without_mcp(client: Client, without_mcp: None) -> None:
    """No connector, no steps."""
    content = client.get(reverse("public:help")).content.decode()
    assert 'id="use-with-ai"' not in content
    assert "data-copy" not in content
