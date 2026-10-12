"""Steps, plans and the loop that runs them.

A plan is read from the accounts first and shown in full; nothing changes
until the run is committed. A step whose ``run`` is None is already done.
A plan can end in a ``then``: steps that can only be worked out once an
earlier step has happened (the services exist only after the Blueprint is
deployed), shown as one pending line until then.

The loop knows nothing about the terminal. It tells a ``View`` what
changed, and the view redraws (titan.ui) or records (the tests).
"""

from __future__ import annotations

import enum
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from titan import TitanError

Progress = Callable[[str], None]


class State(enum.Enum):
    """Where a step is, as the checklist shows it."""

    DONE = "done"
    TODO = "todo"
    RUNNING = "running"
    FAILED = "failed"


@dataclass
class Step:
    """One thing a command will do, or found already done."""

    title: str
    detail: str = ""
    # Its return value is ignored.
    run: Callable[[Progress], object] | None = None
    # A link the person has to open for this step (the Blueprint).
    link: str = ""
    # Set while it runs, e.g. "build_in_progress · 1m12s".
    note: str = ""
    state: State = State.TODO

    def __post_init__(self) -> None:
        """A step with nothing to run is done from the start."""
        if self.run is None and self.state is State.TODO:
            self.state = State.DONE


@dataclass
class Plan:
    """The ordered steps, what comes after them, and the closing line."""

    steps: list[Step] = field(default_factory=list)
    then: Callable[[], Plan] | None = None
    later: str = ""
    finish: str = ""

    def add(
        self,
        title: str,
        detail: str = "",
        run: Callable[[Progress], object] | None = None,
        link: str = "",
    ) -> Step:
        """Append a step and return it."""
        step = Step(title, detail, run, link)
        self.steps.append(step)
        return step

    @property
    def changes(self) -> int:
        """How many steps would change something."""
        return sum(1 for s in self.steps if s.run is not None) + (1 if self.then else 0)


class View(Protocol):
    """What the loop tells the screen."""

    def show(self, plan: Plan, commit: bool) -> None:
        """Draw (or redraw) the whole checklist."""

    def started(self, step: Step) -> None:
        """A step began; open its link if it has one."""


def execute(plan: Plan, view: View, commit: bool) -> Plan:
    """Show the plan, and run it when committing. A failure stops the run.

    Returns the plan as finally shown, with any ``then`` steps folded in.
    """
    view.show(plan, commit)
    if not commit:
        return plan
    while True:
        for step in plan.steps:
            if step.run is None or step.state is State.DONE:
                continue
            step.state = State.RUNNING
            view.started(step)
            view.show(plan, commit)

            def progress(note: str, step: Step = step, plan: Plan = plan) -> None:
                step.note = note
                view.show(plan, commit)

            try:
                step.run(progress)
            except (TitanError, KeyboardInterrupt):
                step.state = State.FAILED
                view.show(plan, commit)
                raise
            step.state, step.note = State.DONE, ""
            view.show(plan, commit)
        if plan.then is None:
            return plan
        following = plan.then()
        plan = Plan(
            steps=plan.steps + following.steps,
            then=following.then,
            later=following.later,
            finish=following.finish or plan.finish,
        )
        view.show(plan, commit)
