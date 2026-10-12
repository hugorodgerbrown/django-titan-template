"""The terminal side: the live checklist and the questions.

The checklist redraws in place (rich's Live display) while steps run: a
spinner on the running step with what it is waiting for, a tick or a
cross when it ends. Questions use questionary, before or after the live
display, never during it.
"""

from __future__ import annotations

import webbrowser
from collections.abc import Callable, Mapping
from typing import Any

import questionary
from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from titan.steps import Plan, State, Step

MARKS = {
    State.DONE: ("✓", "green"),
    State.TODO: ("○", "dim"),
    State.FAILED: ("✗", "red"),
}


def render_plan(plan: Plan, commit: bool) -> RenderableType:
    """The checklist as rich renderables."""
    table = Table.grid(padding=(0, 1))
    table.add_column(width=1)
    table.add_column()
    for step in plan.steps:
        title = Text(step.title)
        if step.state is State.TODO and not commit:
            title = Text.assemble(("would: ", "yellow"), step.title)
        lines: list[RenderableType] = [title]
        if step.detail:
            lines.append(Text(step.detail, style="dim"))
        if step.link and step.state in (State.TODO, State.RUNNING):
            lines.append(Text.assemble((step.link, "cyan underline")))
        if step.note and step.state is State.RUNNING:
            lines.append(Text.assemble((step.note, "yellow")))
        mark: RenderableType
        if step.state is State.RUNNING:
            mark = Spinner("dots", style="yellow")
        else:
            symbol, style = MARKS[step.state]
            mark = Text(symbol, style=style)
        table.add_row(mark, Group(*lines))
    if plan.then is not None:
        table.add_row(Text("○", style="dim"), Text(plan.later, style="dim"))
    return table


class LiveView:
    """Redraws the checklist in place while a plan runs."""

    def __init__(self, console: Console, open_links: bool = True) -> None:
        """Draw on `console`; open a step's link in the browser when it starts."""
        self.console = console
        self.open_links = open_links
        self.live: Live | None = None

    def __enter__(self) -> LiveView:
        """Start the live display."""
        self.live = Live(console=self.console, refresh_per_second=8, transient=False)
        self.live.__enter__()
        return self

    def __exit__(self, *exc: object) -> None:
        """Leave the final checklist on screen."""
        if self.live is not None:
            self.live.__exit__(None, None, None)
            self.live = None

    def show(self, plan: Plan, commit: bool) -> None:
        """Redraw the checklist."""
        if self.live is None:
            self.console.print(render_plan(plan, commit))
        else:
            self.live.update(render_plan(plan, commit), refresh=True)

    def started(self, step: Step) -> None:
        """Open the step's link, e.g. the Blueprint, in the browser."""
        if step.link and self.open_links:
            webbrowser.open(step.link)


def header(console: Console, sources: Mapping[str, str], workspace: str) -> None:
    """Who titan is acting as, and where each key came from."""
    console.print(Text.assemble(("titan", "bold"), ("  Render · shared-db · Resend", "dim")))
    for key, source in sources.items():
        console.print(Text.assemble(("  ● ", "green"), (key, ""), (f"  {source}", "dim")))
    if workspace:
        console.print(
            Text.assemble(("  ● ", "green"), "Render workspace", (f"  {workspace}", "dim"))
        )
    console.print()


class Ask:
    """The questions titan asks, through questionary. Each raises on Ctrl-C."""

    @staticmethod
    def _answer(question: Any) -> Any:
        answer = question.ask()
        if answer is None:
            raise KeyboardInterrupt
        return answer

    def secret(self, label: str) -> str:
        """A hidden answer."""
        return str(self._answer(questionary.password(f"{label}:")))

    def text(
        self, label: str, default: str = "", validate: Callable[[str], Any] | None = None
    ) -> str:
        """A typed answer."""
        return str(self._answer(questionary.text(label, default=default, validate=validate)))

    def choose(self, label: str, choices: list[tuple[str, str]]) -> str:
        """One of `choices` (title, value)."""
        options = [questionary.Choice(title, value=value) for title, value in choices]
        return str(self._answer(questionary.select(label, choices=options)))

    def confirm(self, label: str, default: bool = False) -> bool:
        """Yes or no."""
        return bool(self._answer(questionary.confirm(label, default=default)))
