"""Tests for titan.ui: the checklist as drawn."""

from __future__ import annotations

from rich.console import Console

from titan.steps import Plan, State
from titan.ui import LiveView, header, render_plan


def draw(plan: Plan, commit: bool) -> str:
    """The checklist as plain text."""
    console = Console(record=True, width=100, color_system=None)
    console.print(render_plan(plan, commit))
    return console.export_text()


def test_a_plan_marks_what_would_change() -> None:
    """Done steps tick; pending ones say "would:"; the link and the later line show."""
    plan = Plan(then=lambda: Plan(), later="Then: deploy")
    plan.add("Repo")
    plan.add("Deploy the Blueprint", "one click", run=lambda _: None, link="https://render.com/x")
    text = draw(plan, commit=False)
    assert "✓ Repo" in text
    assert "○ would: Deploy the Blueprint" in text
    assert "one click" in text
    assert "https://render.com/x" in text
    assert "○ Then: deploy" in text


def test_a_running_step_shows_its_note_and_a_failed_one_a_cross() -> None:
    """While running, the note shows; a failure is a cross."""
    plan = Plan()
    running = plan.add("Deploy", run=lambda _: None)
    running.state, running.note = State.RUNNING, "build in progress · 12s"
    failed = plan.add("Check", run=lambda _: None)
    failed.state = State.FAILED
    text = draw(plan, commit=True)
    assert "build in progress · 12s" in text
    assert "✗ Check" in text


def test_the_view_prints_without_a_live_display() -> None:
    """Outside `with`, show prints once; links never open when told not to."""
    console = Console(record=True, width=100, color_system=None)
    view = LiveView(console, open_links=False)
    plan = Plan()
    step = plan.add("Blueprint", run=lambda _: None, link="https://render.com/x")
    view.show(plan, commit=False)
    view.started(step)
    with view:
        view.show(plan, commit=True)
    assert "Blueprint" in console.export_text()


def test_the_header_names_each_source() -> None:
    """Where every key came from, and the workspace."""
    console = Console(record=True, width=100, color_system=None)
    header(console, {"RENDER_API_KEY": "1Password item 'Titan'"}, "Ultraniche")
    text = console.export_text()
    assert "RENDER_API_KEY  1Password item 'Titan'" in text
    assert "Render workspace  Ultraniche" in text
