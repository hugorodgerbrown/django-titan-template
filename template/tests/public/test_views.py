"""Tests for apps.public.views: the homepage, terms, privacy and help."""

import pytest
from django.test import Client
from django.urls import reverse

from apps.public import views

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


def test_home_offers_one_way_in(client: Client) -> None:
    """Signed out, the one action goes to sign in, onwards to the app."""
    content = client.get(reverse("public:home")).content.decode()
    assert f'href="{reverse("accounts:sign_in")}?next={reverse("notes:list")}"' in content
    assert "Create an account" not in content


def test_home_opens_the_app_when_signed_in(signed_in: Client) -> None:
    """Signed in, the header and the action open the app instead."""
    content = signed_in.get(reverse("public:home")).content.decode()
    header = content[content.index("<header") : content.index("</header>")]
    assert "Open the app" in header
    assert f'href="{reverse("notes:list")}">Open the app</a>' in content.split("</header>")[1]
    assert "Sign in" not in content


def test_home_links_to_the_connector_steps(client: Client, with_mcp: str) -> None:
    """With MCP, the front page points at the help page's steps."""
    content = client.get(reverse("public:home")).content.decode()
    assert f'href="{reverse("public:help")}#use-with-ai"' in content.split("</header>")[1]


def test_home_leaves_the_connector_out_without_mcp(client: Client, without_mcp: None) -> None:
    """An app made without MCP says nothing about connecting."""
    content = client.get(reverse("public:home")).content.decode()
    assert 'id="mcp"' not in content


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
