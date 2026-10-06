"""The MCP tools. Each is a function of (user, arguments) returning JSON-able data.

Add a tool by writing a function and listing it in TOOLS with its JSON
Schema. Raise ToolError for a mistake the model should see and correct.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from apps.notes.forms import NoteForm
from apps.notes.models import Note


class ToolError(Exception):
    """A problem with the call that the model can fix and retry."""


@dataclass(frozen=True)
class Tool:
    """One MCP tool: its name, description, input schema and implementation."""

    name: str
    description: str
    input_schema: dict[str, Any]
    func: Callable[[Any, dict[str, Any]], dict[str, Any]]
    read_only: bool = True

    def describe(self) -> dict[str, Any]:
        """Return the tool as tools/list lists it."""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
            "annotations": {"readOnlyHint": self.read_only},
        }


def list_notes(user: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Return the user's latest notes, newest first."""
    limit = args.get("limit", 20)
    if not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ToolError("limit must be a whole number from 1 to 100.")
    notes = Note.objects.for_user(user)[:limit]
    return {
        "notes": [
            {"uuid": str(n.uuid), "text": n.text, "written_at": n.written_at.isoformat()}
            for n in notes
        ]
    }


def add_note(user: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Add a note for the user."""
    form = NoteForm({"text": args.get("text", "")})
    if not form.is_valid():
        raise ToolError("; ".join(f"{k}: {' '.join(map(str, v))}" for k, v in form.errors.items()))
    note = form.save(commit=False)
    note.owner = user
    note.save()
    return {"uuid": str(note.uuid), "text": note.text, "written_at": note.written_at.isoformat()}


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool(
            name="list_notes",
            description="List the user's latest notes, newest first.",
            input_schema={
                "type": "object",
                "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}},
            },
            func=list_notes,
        ),
        Tool(
            name="add_note",
            description="Add a note for the user.",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string", "maxLength": 2000}},
                "required": ["text"],
            },
            func=add_note,
            read_only=False,
        ),
    ]
}
