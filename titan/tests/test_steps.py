"""Tests for titan.steps: the loop that runs a plan and tells the view."""

from __future__ import annotations

import pytest
from conftest import RecordingView

from titan import TitanError
from titan.steps import Plan, Progress, State, execute


def test_a_dry_run_shows_but_runs_nothing() -> None:
    """Without commit nothing runs and the view draws once."""
    ran: list[str] = []
    plan = Plan()
    plan.add("done already")
    plan.add("to do", run=lambda _: ran.append("x"))
    view = RecordingView()
    execute(plan, view, commit=False)
    assert ran == []
    assert view.frames == [[("done", "done already", ""), ("todo", "to do", "")]]
    assert plan.changes == 1


def test_steps_report_progress_and_then_steps_follow() -> None:
    """Progress notes redraw the running step; `then` adds steps once the plan has run."""

    def slow(progress: Progress) -> None:
        progress("halfway")

    later = Plan()
    later.add("after", run=lambda _: None)
    plan = Plan(then=lambda: later, later="after the first")
    plan.add("first", run=slow)
    view = RecordingView()
    final = execute(plan, view, commit=True)
    assert ("running", "first", "halfway") in [row for frame in view.frames for row in frame]
    assert [(s.title, s.state) for s in final.steps] == [
        ("first", State.DONE),
        ("after", State.DONE),
    ]


def test_a_failure_marks_the_step_and_stops() -> None:
    """The failing step shows a cross and later steps never run."""
    ran: list[str] = []

    def fail(_: Progress) -> None:
        raise TitanError("nope")

    plan = Plan()
    plan.add("fails", run=fail)
    plan.add("never", run=lambda _: ran.append("x"))
    view = RecordingView()
    with pytest.raises(TitanError):
        execute(plan, view, commit=True)
    assert view.titles("failed") == ["fails"]
    assert ran == []
