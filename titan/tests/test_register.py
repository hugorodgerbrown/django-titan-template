"""Tests for titan.register: reading, recording and writing apps.json."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from titan import TitanError, register
from titan.app import App
from titan.credentials import Settings

ROOT = Path(__file__).resolve().parents[2]


def test_the_checked_in_register_is_valid() -> None:
    """The real apps.json parses, and is in the form titan writes it."""
    text = (ROOT / register.PATH).read_text()
    apps = register.parse(text)
    assert register.render(apps) == text
    assert len({e["slug"] for e in apps}) == len(apps)


def test_an_empty_register_has_no_apps() -> None:
    """A missing or blank file is an empty register."""
    assert register.parse("") == []
    assert register.parse('{"apps": []}') == []


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("{nope", "not valid JSON"),
        ("[]", r'should be \{"apps"'),
        ('{"apps": [{"slug": "a"}]}', "a has no name, repo"),
        (
            '{"apps": [{"slug": "a", "name": "A", "repo": "r", "domain": "d",'
            ' "stage": "gone", "updates": true}]}',
            "stage should be one of",
        ),
    ],
)
def test_a_malformed_register_is_an_error(text: str, message: str) -> None:
    """A register titan cannot read is never rewritten."""
    with pytest.raises(TitanError, match=message):
        register.parse(text)


def test_record_never_moves_a_live_app_back_to_new(settings: Settings) -> None:
    """`titan new` on a live app's repo keeps it live."""
    app = App.from_slug("tally", settings)
    live = register.record([], app, "live")
    assert register.find(register.record(live, app, "new"), "tally")["stage"] == "live"  # type: ignore[index]
    assert register.is_current(live, app, "new")


def test_render_sorts_and_keeps_extra_fields(settings: Settings) -> None:
    """Entries sort by slug; a field added by hand is kept, after titan's own."""
    apps = register.record([], App.from_slug("zebra", settings), "new")
    apps = register.record(apps, App.from_slug("atlas", settings), "new")
    apps[0]["notes"] = "kept"
    rows = json.loads(register.render(apps))["apps"]
    assert [r["slug"] for r in rows] == ["atlas", "zebra"]
    assert list(rows[1])[-1] == "notes"
