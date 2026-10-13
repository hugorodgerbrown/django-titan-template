"""The page frame and offline rules in DESIGN.md (sections 8 to 10).

The mark top left goes home, the website ends with its footer (the app has
none), and every script a page under /app/ loads is there offline.
"""

import re
from pathlib import Path

from django.conf import settings
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.design.conf import NEEDS_NETWORK
from apps.pwa import conf as pwa_conf

BASE = Path(settings.BASE_DIR)
TEMPLATES = BASE / "templates"


def first_header_link(html: str) -> str:
    """The href of the first link in the page's header."""
    header = re.search(r"<header\b.*?</header>", html, re.DOTALL)
    assert header, "the page has no <header>"
    link = re.search(r"<a\b[^>]*\bhref=\"([^\"]*)\"", header.group(0))
    assert link, "the header has no link"
    return link.group(1)


def footer(html: str) -> str:
    """The page's site footer."""
    found = re.search(r"<footer\b.*?</footer>", html, re.DOTALL)
    assert found, "the page has no <footer>"
    return found.group(0)


def start_url(client: Client) -> str:
    """The installed app's start page, as its manifest gives it."""
    url: str = client.get(reverse("pwa:manifest")).json()["start_url"]
    return url


def test_the_mark_on_a_public_page_goes_to_the_front_page(client: Client, db: None) -> None:
    """On a public page, the mark goes to the front page."""
    html = client.get(reverse("public:terms")).content.decode()
    assert first_header_link(html) == reverse("public:home")


def test_the_mark_in_the_app_goes_to_the_front_page(signed_in: Client) -> None:
    """Inside /app/ too, the mark goes to the front page."""
    html = signed_in.get(start_url(signed_in)).content.decode()
    assert first_header_link(html) == reverse("public:home")


def test_the_front_page_shows_to_people_signed_in(signed_in: Client) -> None:
    """The mark's destination is the front page itself, not a redirect back into the app."""
    assert signed_in.get(reverse("public:home")).status_code == 200


def test_public_pages_end_with_the_links_and_the_copyright(client: Client, db: None) -> None:
    """The website's footer is the links and the copyright, and nothing else."""
    links = footer(client.get(reverse("public:home")).content.decode())
    for name in ("public:terms", "public:privacy", "public:help"):
        assert f'href="{reverse(name)}"' in links, name
    assert f"© {timezone.localdate().year} Ultraniche" in links
    assert f'href="{reverse("public:home")}"' not in links, "no mark or name in the footer"


def test_the_app_has_no_footer_and_its_links_are_on_the_account_page(signed_in: Client) -> None:
    """Under /app/ there's no footer; the account page carries its links instead."""
    assert "<footer" not in signed_in.get(start_url(signed_in)).content.decode()
    account = signed_in.get(reverse("accounts:account")).content.decode()
    for name in ("public:terms", "public:privacy", "public:help"):
        assert f'href="{reverse(name)}"' in account, name
    assert f"© {timezone.localdate().year} Ultraniche" in account


def test_every_page_fits_the_screen() -> None:
    """Both base templates carry the viewport meta."""
    head = (TEMPLATES / "includes" / "_head.html").read_text()
    assert 'name="viewport" content="width=device-width' in head
    for base in ("base.html", "public_base.html"):
        assert '{% include "includes/_head.html" %}' in (TEMPLATES / base).read_text()


def test_the_app_frame_shows_when_its_offline() -> None:
    """The app's frame has the offline banner."""
    assert "data-offline-banner" in (TEMPLATES / "base.html").read_text()


def find_template(name: str) -> Path | None:
    """A template by the name an include gives it, in templates/ or an app's templates/."""
    for folder in [TEMPLATES, *sorted((BASE / "apps").glob("*/templates"))]:
        if (folder / name).is_file():
            return folder / name
    return None


def app_templates() -> list[Path]:
    """The app's frame, every page that extends it, and every template they include."""
    found = [TEMPLATES / "base.html"]
    found += [
        path
        for path in sorted((BASE / "apps").glob("*/templates/**/*.html"))
        if re.search(r"{%\s*extends\s+[\"']base\.html[\"']", path.read_text())
    ]
    for path in found:  # grows as includes are found, so includes of includes count too
        for name in re.findall(r"{%\s*include\s+[\"']([^\"']+)[\"']", path.read_text()):
            include = find_template(name)
            if include and include not in found:
                found.append(include)
    return found


def loaded_static(path: Path) -> set[str]:
    """The scripts and stylesheets a template loads with {% static %}."""
    return set(re.findall(r"{%\s*static\s+[\"']([^\"']+\.(?:js|css))[\"']", path.read_text()))


def test_the_app_opens_offline() -> None:
    """Every script and stylesheet a page under /app/ loads is precached, or needs the network."""
    missing = sorted(
        f"{path.name}: {name}"
        for path in app_templates()
        for name in loaded_static(path)
        if name not in pwa_conf.PRECACHE_STATIC and name not in NEEDS_NETWORK
    )
    assert not missing, "precache these, or list them in NEEDS_NETWORK: " + "; ".join(missing)


def test_what_needs_the_network_is_still_loaded() -> None:
    """An entry in NEEDS_NETWORK for a file no app page loads is stale."""
    loaded = set().union(*(loaded_static(path) for path in app_templates()))
    stale = sorted(set(NEEDS_NETWORK) - loaded)
    assert not stale, stale
