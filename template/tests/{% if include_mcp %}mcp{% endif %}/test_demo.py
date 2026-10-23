"""The front page's chat scenes against the real MCP tools.

A scene may be idealised but never untrue (DESIGN.md, "The front page"):
a tool it says the AI called has to be one the server lists, so renaming or
removing a tool fails here until the scene is changed too.
"""

from apps.mcp.tools import TOOLS
from apps.public import demo


def test_every_tool_a_scene_names_is_real() -> None:
    """Each step in every chat scene names a tool in TOOLS."""
    assert demo.scene_tools(), "the chat scenes name no tools"
    assert demo.scene_tools() <= set(TOOLS), demo.scene_tools() - set(TOOLS)


def test_a_scene_that_says_done_called_a_tool_that_writes() -> None:
    """A done chip claims a change, so its chat called a tool that isn't read-only."""
    for name, turns in demo.CHATS.items():
        if any(turn.kind == "done" for turn in turns):
            steps = [TOOLS[turn.text] for turn in turns if turn.kind == "step"]
            assert any(not tool.read_only for tool in steps), name
