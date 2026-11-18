"""Tests for titan.credentials: 1Password, then the file, then a prompt; never the environment."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from titan import TitanError
from titan.credentials import SECRET_KEYS, load, read_1password

KEYS = {
    "RENDER_API_KEY": "rnd_op",
    "RESEND_API_KEY": "re_op",
    "TITAN_DB_ADMIN_URL": "postgresql://h/db",
}


def never_asked(prompt: str) -> str:
    """Fail the test if titan prompts."""
    raise AssertionError(f"asked: {prompt}")


def no_op(item: str, vault: str) -> tuple[dict[str, str], str]:
    """1Password has nothing, and no reason to give."""
    return {}, ""


def test_keys_come_from_1password_first(tmp_path: Path) -> None:
    """1Password wins over the file, and says so."""
    path = tmp_path / "env"
    path.write_text("RENDER_API_KEY=from-file\n")
    asked_for: list[tuple[str, str]] = []

    def op(item: str, vault: str) -> tuple[dict[str, str], str]:
        asked_for.append((item, vault))
        return KEYS, ""

    loaded = load(never_asked, {"TITAN_OP_VAULT": "Infra"}, path, op)
    assert loaded.render_api_key == "rnd_op"
    assert asked_for == [("Titan", "Infra")]
    assert loaded.sources["RENDER_API_KEY"] == "1Password item 'Titan'"


def test_keys_come_from_the_file_never_the_environment(tmp_path: Path) -> None:
    """The file's keys win; an app's key exported in the shell is ignored."""
    path = tmp_path / "env"
    path.write_text(
        "# titan\nRENDER_API_KEY=from-file\nRESEND_API_KEY='re_x'\n"
        "TITAN_DB_ADMIN_URL=postgresql://h/db\nTITAN_MAIL_DOMAIN=mail.example.com\n"
    )
    loaded = load(
        never_asked, {"RENDER_API_KEY": "from-env", "TITAN_DOMAIN": "example.com"}, path, no_op
    )
    assert loaded.render_api_key == "from-file"
    assert loaded.resend_api_key == "re_x"
    assert loaded.domain == "example.com"
    assert loaded.mail_domain == "mail.example.com"
    assert loaded.sources["RESEND_API_KEY"] == str(path)


def test_missing_keys_are_asked_for_not_read_from_the_environment(tmp_path: Path) -> None:
    """With neither source each key is asked for, even if the shell exports it."""
    asked: list[str] = []

    def ask(prompt: str) -> str:
        asked.append(prompt)
        return f" typed-{len(asked)} "

    loaded = load(ask, {"RESEND_API_KEY": "re_some_apps_key"}, tmp_path / "absent", no_op)
    assert [p.split("(")[1].rstrip(")") for p in asked] == list(SECRET_KEYS)
    assert (loaded.render_api_key, loaded.resend_api_key, loaded.db_admin_url) == (
        "typed-1",
        "typed-2",
        "typed-3",
    )


def test_the_fivebar_token_is_optional_and_never_asked_for(tmp_path: Path) -> None:
    """From 1Password or the file when there; otherwise empty, with no prompt."""
    path = tmp_path / "env"
    path.write_text("FIVEBAR_API_KEY=fivebar_file\n")
    assert load(never_asked, {}, path, lambda item, vault: (KEYS, "")).fivebar_api_key == (
        "fivebar_file"
    )
    with_op = load(
        never_asked, {}, path, lambda item, vault: ({**KEYS, "FIVEBAR_API_KEY": "fb_op"}, "")
    )
    assert with_op.fivebar_api_key == "fb_op"
    assert load(never_asked, {}, tmp_path / "absent", lambda i, v: (KEYS, "")).fivebar_api_key == ""


def test_a_blank_answer_stops_the_run(tmp_path: Path) -> None:
    """An empty answer is an error naming the key and where to put it."""
    with pytest.raises(TitanError, match=r"No RENDER_API_KEY given\..*1Password item 'Titan'"):
        load(lambda prompt: "", {}, tmp_path / "absent", no_op)


def completed(code: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    """A finished `op` call."""
    return subprocess.CompletedProcess([], code, stdout=stdout, stderr=stderr)


def test_read_1password_picks_the_labelled_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """One `op item get`; only fields labelled with titan's keys are kept."""
    monkeypatch.setattr("titan.credentials.shutil.which", lambda name: "/usr/bin/op")
    calls: list[list[str]] = []
    item = {
        "fields": [
            {"label": "RENDER_API_KEY", "value": "rnd"},
            {"label": "notes", "value": "ignore me"},
            {"label": "RESEND_API_KEY", "value": ""},
        ]
    }

    def run(args: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return completed(0, json.dumps(item))

    values, problem = read_1password("Titan", "Infra", run)
    assert values == {"RENDER_API_KEY": "rnd"}
    assert problem == (
        "1Password item 'Titan' has no filled-in field labelled RESEND_API_KEY, "
        "TITAN_DB_ADMIN_URL (its fields: 'RENDER_API_KEY', 'notes', 'RESEND_API_KEY')"
    )
    assert calls == [
        ["op", "item", "get", "Titan", "--format", "json", "--reveal", "--vault", "Infra"]
    ]


@pytest.mark.parametrize(
    ("installed", "result", "problem"),
    [
        (False, completed(0, "{}"), "the 1Password CLI `op` is not on the PATH"),
        (True, completed(1), "`op item get Titan` failed: exit status 1"),
        (
            True,
            completed(1, stderr="[ERROR] 2026/11/18 14:28:01 You are not currently signed in.\n"),
            "`op item get Titan` failed: You are not currently signed in. (run `op signin`, "
            "or turn on Settings > Developer > Integrate with 1Password CLI in the "
            "1Password app)",
        ),
        (
            True,
            completed(1, stderr="[ERROR] 2026/11/18 14:28:01 unknown flag: --reveal\n"),
            "`op item get Titan` failed: unknown flag: --reveal (update the 1Password CLI "
            "(`brew upgrade 1password-cli`); titan needs op 2.21+)",
        ),
        (
            True,
            completed(
                1,
                stderr='[ERROR] 2026/11/18 14:28:01 "Titan" isn\'t an item. Specify the '
                "item with its UUID, name, or domain.\n",
            ),
            '`op item get Titan` failed: "Titan" isn\'t an item. Specify the item with its '
            "UUID, name, or domain. (name the item 'Titan', or set TITAN_OP_ITEM "
            "(and TITAN_OP_VAULT))",
        ),
        (
            True,
            completed(1, stderr="[ERROR] 2026/11/18 14:28:01 More than one item matches.\n"),
            "`op item get Titan` failed: More than one item matches. "
            "(set TITAN_OP_VAULT to the vault that holds it)",
        ),
        (True, completed(0, "not json"), "`op item get Titan` did not return JSON"),
    ],
)
def test_read_1password_falls_through_and_says_why(
    monkeypatch: pytest.MonkeyPatch,
    installed: bool,
    result: subprocess.CompletedProcess[str],
    problem: str,
) -> None:
    """No op, a locked or missing item, or bad output: try the next source, with a reason."""
    monkeypatch.setattr(
        "titan.credentials.shutil.which", lambda name: "/usr/bin/op" if installed else None
    )
    assert read_1password("Titan", "", lambda args: result) == ({}, problem)


def test_read_1password_matches_labels_loosely(monkeypatch: pytest.MonkeyPatch) -> None:
    """A label typed as words or in lower case still names the key; every key there, no problem."""
    monkeypatch.setattr("titan.credentials.shutil.which", lambda name: "/usr/bin/op")
    item = {
        "fields": [
            {"label": "Render API key", "value": "rnd"},
            {"label": "resend-api-key", "value": "re"},
            {"label": " TITAN_DB_ADMIN_URL ", "value": "postgresql://h/db"},
        ]
    }
    assert read_1password("Titan", "", lambda args: completed(0, json.dumps(item))) == (
        {
            "RENDER_API_KEY": "rnd",
            "RESEND_API_KEY": "re",
            "TITAN_DB_ADMIN_URL": "postgresql://h/db",
        },
        "",
    )


def test_why_1password_failed_is_said_before_the_first_prompt(tmp_path: Path) -> None:
    """The reason comes once, before asking; nothing is said when the file has every key."""
    events: list[str] = []

    def op(item: str, vault: str) -> tuple[dict[str, str], str]:
        return {}, "`op item get Titan` failed: not signed in"

    def ask(prompt: str) -> str:
        events.append("ask")
        return "typed"

    load(ask, {}, tmp_path / "absent", op, events.append)
    assert events == [
        "Not from 1Password: `op item get Titan` failed: not signed in.",
        *["ask"] * 3,
    ]

    path = tmp_path / "env"
    path.write_text("".join(f"{key}={value}\n" for key, value in KEYS.items()))
    said: list[str] = []
    load(never_asked, {}, path, op, said.append)
    assert said == []
