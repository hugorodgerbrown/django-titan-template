"""Tests for build.py: the reveal rules and the config checks."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import build

CONFIG = json.loads((build.ROOT / "apps.json").read_text(encoding="utf-8"))


def opened_config(opened: int) -> dict:
    """Return the real config with ``opened`` apps open and every app filled in.

    Args:
        opened: How many apps are open.

    Returns:
        A config that passes ``build.load``.
    """
    config = copy.deepcopy(CONFIG)
    config["opened"] = opened
    for app in config["titan"]:
        slug = app["name"].lower()
        app["tagline"] = app["tagline"] or f"What {app['name']} does."
        app["url"] = app["url"] or f"https://{slug}.ultraniche.ai"
    return config


def write(tmp_path: Path, config: dict) -> Path:
    """Write ``config`` as apps.json under ``tmp_path``.

    Args:
        tmp_path: The pytest temporary folder.
        config: The config to write.

    Returns:
        The file written.
    """
    path = tmp_path / "apps.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def page(config: dict) -> str:
    """Render the page for ``config``.

    Args:
        config: A valid config.

    Returns:
        The page's HTML.
    """
    return build.render(config, (build.SRC / "index.html").read_text(encoding="utf-8"))


def test_committed_config_builds(tmp_path: Path) -> None:
    """The apps.json in the repo builds a page with its assets beside it."""
    index = build.build(out=tmp_path / "dist")
    assert index.exists()
    assert (tmp_path / "dist" / "styles.css").exists()
    assert (tmp_path / "dist" / "mark.svg").exists()
    assert "$" not in index.read_text(encoding="utf-8").split("<body>")[1]


@pytest.mark.parametrize("opened", [0, 1, 5, 10])
def test_states_follow_the_opened_count(opened: int) -> None:
    """Apps up to the count are open, the next shows its brand, the rest are sealed."""
    states = [t.state for t in build.tiles(opened_config(opened))]
    assert states[:opened] == ["open"] * opened
    if opened < 10:
        assert states[opened] == "next"
    assert states[opened + 1 :] == ["sealed"] * (9 - opened if opened < 10 else 0)


def test_nothing_leaks_before_its_time() -> None:
    """A sealed app's name, and the next app's tagline and link, stay out of the page."""
    html = page(opened_config(1))
    assert "Shift" in html and "shift.ultraniche.ai" in html
    assert "Flight" in html
    assert "What Flight does." not in html
    assert "flight.ultraniche.ai" not in html
    for name in ("Pack", "Cook", "Checklist", "Maintain", "Last", "Score", "Shop", "Clock"):
        assert name not in html


def test_progress_lines() -> None:
    """The count and the next app read correctly at the start and the end."""
    assert "None open yet" in page(opened_config(0))
    assert "Coming next: Shift" in page(opened_config(0))
    finished = page(opened_config(10))
    assert "10 of 10 open" in finished
    assert "All 10 are open." in finished
    assert "Still under wraps</h3>" not in finished


def test_phone_order_puts_next_then_newest_first() -> None:
    """The phone list starts with the next app, then the newest open one."""
    html = page(opened_config(2))
    narrow = html.split('class="grid grid--narrow"')[1].split("</ol>")[0]
    assert narrow.index("Pack") < narrow.index("Flight") < narrow.index("Shift")


def test_story_link_only_when_given() -> None:
    """An open app without a story has no story link."""
    config = opened_config(1)
    assert "Read the story" not in page(config)
    config["titan"][0]["story"] = "https://example.com/shift"
    assert "Read the story" in page(config)


def test_text_is_escaped() -> None:
    """Names and taglines are escaped, never trusted as HTML."""
    config = opened_config(1)
    config["titan"][0]["tagline"] = "<script>alert(1)</script>"
    html = page(config)
    assert "<script>alert(1)" not in html
    assert "&lt;script&gt;" in html


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda c: c.update(opened=11), "opened must be"),
        (lambda c: c.update(opened=-1), "opened must be"),
        (lambda c: c.update(opened=True), "opened must be"),
        (lambda c: c.update(opened="1"), "opened must be"),
        (lambda c: c["titan"][1].update(colour="blue"), "colour must be"),
        (lambda c: c["titan"][1].update(name=""), "needs a name"),
        (lambda c: c.update(titan=[]), "non-empty"),
        (lambda c: c["earlier"][0].update(url=None), "earlier app needs a url"),
    ],
)
def test_invalid_config_is_refused(tmp_path: Path, change, message: str) -> None:
    """A config that cannot make a sensible page is refused with a reason."""
    config = opened_config(1)
    change(config)
    with pytest.raises(build.ConfigError, match=message):
        build.load(write(tmp_path, config))


def test_opening_an_app_needs_its_tagline_and_link(tmp_path: Path) -> None:
    """Raising the count past an app with no tagline or link is refused."""
    config = copy.deepcopy(CONFIG)
    config["opened"] = 2
    with pytest.raises(build.ConfigError, match="Flight is open, so it needs a tagline"):
        build.load(write(tmp_path, config))


def test_main_reports_a_bad_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """main() exits non-zero on a bad config and zero on a good one."""
    monkeypatch.setattr(build, "DIST", tmp_path / "dist")
    assert build.main() == 0
    bad = write(tmp_path, {**CONFIG, "opened": 99})
    monkeypatch.setattr(build, "ROOT", tmp_path)
    monkeypatch.setattr(build.build, "__defaults__", (bad, tmp_path / "dist"))
    assert build.main() == 1
