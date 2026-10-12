"""Tests for titan.cli: arguments, workspaces and the scripted (non-terminal) path."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from conftest import FakeDb, FakeGitHub, FakeRender, FakeResend

from titan import TitanError, cli
from titan.credentials import Settings

KEYS = {"RENDER_API_KEY": "r", "RESEND_API_KEY": "s", "TITAN_DB_ADMIN_URL": "postgresql://h/db"}


@pytest.fixture
def accounts(monkeypatch: pytest.MonkeyPatch, checked: list[str]) -> FakeRender:
    """Point the CLI at fakes, with keys from "1Password"."""
    render = FakeRender()
    monkeypatch.setattr("titan.credentials.read_1password", lambda item, vault: KEYS)
    monkeypatch.setattr(cli, "Render", lambda token: render)
    monkeypatch.setattr(cli, "Resend", lambda token: FakeResend())
    monkeypatch.setattr(cli, "SharedDb", lambda url: FakeDb())
    monkeypatch.setattr(cli, "GitHub", lambda: FakeGitHub())
    monkeypatch.setattr("titan.plans.time.sleep", lambda _: None)
    return render


def test_main_reports_errors_and_exits_non_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No keys anywhere and no terminal to ask on: a clear error and exit 1."""
    monkeypatch.setattr("titan.credentials.read_1password", lambda item, vault: {})
    monkeypatch.setattr("titan.credentials.CONFIG_FILE", Path("/absent"))
    assert cli.main(["status", "tally"]) == 1
    assert "RENDER_API_KEY" in capsys.readouterr().out


def test_no_command_needs_a_terminal(capsys: pytest.CaptureFixture[str]) -> None:
    """Interactive mode refuses to run without a terminal."""
    assert cli.main([]) == 1
    assert "Not a terminal" in capsys.readouterr().out


def test_status_changes_nothing(accounts: FakeRender, capsys: pytest.CaptureFixture[str]) -> None:
    """Status shows both plans and writes nothing."""
    assert cli.main(["status", "tally"]) == 0
    out = capsys.readouterr().out
    assert "would: Create the shared env group 'titan'" in out
    assert "CNAME  tally" in out
    assert accounts.writes == []


def test_new_without_a_terminal_only_plans(
    accounts: FakeRender, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without --commit and no one to ask, nothing changes."""
    assert cli.main(["new", "tally"]) == 0
    assert "Nothing changed." in capsys.readouterr().out
    assert accounts.writes == []


def test_new_with_commit_applies(accounts: FakeRender, capsys: pytest.CaptureFixture[str]) -> None:
    """--commit runs the plan to the end."""
    assert cli.main(["new", "tally", "--commit"]) == 0
    assert "titan golive tally" in capsys.readouterr().out
    assert "tally" in accounts.groups


def test_workspace_is_picked_by_setting_or_alone() -> None:
    """One workspace is used; several need TITAN_RENDER_WORKSPACE without a terminal."""
    settings = Settings("r", "s", "postgresql://h/db")
    one: Any = FakeRender()
    assert cli.pick_workspace(one, settings, None) == ("tea-1", "Ultraniche")

    class Two(FakeRender):
        def workspaces(self) -> list[dict[str, Any]]:
            return [{"id": "tea-1", "name": "A"}, {"id": "tea-2", "name": "B"}]

    two: Any = Two()
    with pytest.raises(TitanError, match="TITAN_RENDER_WORKSPACE"):
        cli.pick_workspace(two, settings, None)
    chosen = Settings("r", "s", "postgresql://h/db", render_workspace="B")
    assert cli.pick_workspace(two, chosen, None) == ("tea-2", "B")
    with pytest.raises(TitanError, match="No Render workspace 'C'"):
        cli.pick_workspace(two, Settings("r", "s", "x", render_workspace="C"), None)


class ScriptedAsk:
    """Answers questions from a script, in order, and records them."""

    def __init__(self, *answers: Any) -> None:
        """The answers, in the order titan asks."""
        self.answers = list(answers)
        self.asked: list[str] = []

    def _next(self, label: str, validate: Any = None) -> Any:
        self.asked.append(label)
        answer = self.answers.pop(0)
        if validate is not None:
            assert validate(answer) is True
        return answer

    def secret(self, label: str) -> str:
        """A hidden answer."""
        return str(self._next(label))

    def text(self, label: str, default: str = "", validate: Any = None) -> str:
        """A typed answer; None takes the default."""
        answer = self._next(label)
        answer = default if answer is None else answer
        if validate is not None:
            assert validate(answer) is True
        return str(answer)

    def choose(self, label: str, choices: list[tuple[str, str]]) -> str:
        """One of the values offered."""
        answer = self._next(label)
        assert answer in [value for _, value in choices]
        return str(answer)

    def confirm(self, label: str, default: bool = False) -> bool:
        """Yes or no."""
        return bool(self._next(label))


def test_interactive_new_asks_for_the_app_then_applies(
    accounts: FakeRender, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No arguments: pick an action, describe the app, see the plan, say yes."""
    github = FakeGitHub(exists=False)
    monkeypatch.setattr(cli, "GitHub", lambda: github)
    ask = ScriptedAsk("new", "Ski Trips", None, None, None, False, True)
    monkeypatch.setattr(cli, "Ask", lambda: ask)
    monkeypatch.setattr("titan.cli.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("titan.cli.Console.is_terminal", property(lambda self: True))
    accounts.services.clear()
    accounts.blueprint_after = 2
    # The fake's services are Tally's; this app is ski-trips, so answer as Render would.
    monkeypatch.setattr(cli, "plan_new", lambda ctx: _tally_plan(ctx))
    assert cli.main([]) == 0
    assert ask.asked[0] == "What do you want to do?"
    assert ask.asked[-1].startswith("Apply ")
    assert github.generated[0]["project_slug"] == "ski-trips"
    assert github.generated[0]["include_mcp"] == "false"
    assert github.generated[0]["theme_colour"] == "#1d4ed8"


def _tally_plan(ctx: Any) -> Any:
    """Just the generation step of `new`, for the app the person described."""
    from titan.steps import Plan

    plan = Plan()
    answers = {"project_name": ctx.app.name, "project_slug": ctx.app.slug, **ctx.answers}
    plan.add("Generate", run=lambda _: ctx.github.generate(answers, ctx.app.repo, ctx.workdir))
    return plan


def test_interactive_golive_picks_an_existing_app(
    accounts: FakeRender, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Go-live offers the workspace's apps; saying no changes nothing."""
    ask = ScriptedAsk("golive", "tally", False)
    monkeypatch.setattr(cli, "Ask", lambda: ask)
    monkeypatch.setattr("titan.cli.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("titan.cli.Console.is_terminal", property(lambda self: True))
    assert cli.main([]) == 0
    assert "Nothing changed." in capsys.readouterr().out
    assert accounts.writes == []


def test_ask_existing_app_falls_back_to_typing(settings: Settings) -> None:
    """With no Titan apps in the workspace, the slug is typed."""
    empty: Any = FakeRender(services=False)
    assert cli.ask_existing_app(ScriptedAsk("gondola"), empty, "tea-1", settings) == "gondola"  # type: ignore[arg-type]


def test_several_workspaces_are_chosen_from(settings: Settings) -> None:
    """With a terminal, several workspaces become a question."""

    class Two(FakeRender):
        def workspaces(self) -> list[dict[str, Any]]:
            return [{"id": "tea-1", "name": "A"}, {"id": "tea-2", "name": "B"}]

    two: Any = Two()
    chosen = cli.pick_workspace(two, settings, ScriptedAsk("tea-2"))  # type: ignore[arg-type]
    assert chosen == ("tea-2", "B")


def test_an_interrupted_run_says_how_to_resume(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ctrl-C exits 130 and says a re-run picks up where it stopped."""

    def interrupt(*_: Any, **__: Any) -> Any:
        raise KeyboardInterrupt

    monkeypatch.setattr("titan.credentials.load", interrupt)
    assert cli.main(["status", "tally"]) == 130
    assert "pick up where it left off" in capsys.readouterr().out
