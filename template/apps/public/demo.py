"""The front page's demo data: one cast the product and every scene share.

DESIGN.md, "The front page": the hero draws the app's own component with
these notes, and the chat scenes talk about the same notes, so a visitor who
meets Thursday's plumber in the product meets him again in the chat.
Replace them with the product's own, keeping them specific: real-sounding
words, exact times, nothing called "Example".

A scene may be idealised but never untrue: every ``step`` names a real MCP
tool (tests/mcp/test_demo.py checks them against ``TOOLS``), and every
answer is one the app could give.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.utils import timezone

# (text, minutes before now), so the demo never looks stale.
DEMO_NOTES = [
    ("Call the plumber back about Thursday", 12),
    ("Milk, eggs, the good bread", 95),
    ("Book Saturday's table for six", 60 * 26),
]

# The note the phone scene shows written in a tunnel, waiting to send.
PENDING_NOTE = "Ask Sam about the spare key"


@dataclass(frozen=True)
class Turn:
    """One line of a chat scene.

    Attributes:
        kind: ``you`` (the person asks), ``step`` (a tool the AI called),
            ``reply`` (its answer) or ``done`` (what it changed).
        text: The words; for a ``step``, the tool's name.
    """

    kind: str
    text: str


KINDS = ("you", "step", "reply", "done")

# The hero's chat turn: the promise kept, on the product's own notes.
HERO_CHAT = [
    Turn("you", "What did I note about the plumber?"),
    Turn("step", "list_notes"),
    Turn("reply", 'One note, 12 minutes ago: "Call the plumber back about Thursday."'),
]

# A job told in a chat: ask, the tools, the answer, and what changed.
LIST_CHAT = [
    Turn("you", "Turn today's notes into a to-do list and save it."),
    Turn("step", "list_notes"),
    Turn("step", "add_note"),
    Turn("reply", "Saved: To do: call the plumber about Thursday, buy milk, eggs and bread."),
    Turn("done", "Added to your notes"),
]

CHATS = {"hero": HERO_CHAT, "list": LIST_CHAT}


def demo_notes() -> list[dict[str, Any]]:
    """Return the demo notes, shaped like the notes the app lists."""
    now = timezone.now()
    return [
        {"text": text, "written_at": now - timedelta(minutes=minutes)}
        for text, minutes in DEMO_NOTES
    ]


def scene_tools() -> set[str]:
    """Every tool any chat scene says the AI called."""
    return {turn.text for turns in CHATS.values() for turn in turns if turn.kind == "step"}
