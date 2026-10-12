"""titan's command line: interactive by default, scriptable with arguments.

    titan                         # asks what to do, then shows the plan and asks before acting
    titan new <app>               # plan for a new app; asks to apply it
    titan golive <app>            # plan the go-live (after you add the CNAME)
    titan status <app>            # what exists and what is missing; changes nothing
    titan new <app> --commit      # apply without asking (for scripts)
    titan new <app> --plan        # show the plan only

Every run reads the accounts first and shows the whole plan; nothing changes
until you say yes (or pass --commit). Each run picks up where the last
stopped, so a failed or interrupted run is fixed by running it again.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from rich.console import Console

from titan import TitanError, __version__, credentials
from titan.app import SLUG, App
from titan.credentials import Settings
from titan.plans import Context, plan_golive, plan_new
from titan.providers import GitHub, Render, Resend, SharedDb
from titan.steps import Plan, execute
from titan.ui import Ask, LiveView, header

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def parse(argv: list[str] | None) -> argparse.Namespace:
    """The arguments; none at all means interactive."""
    parser = argparse.ArgumentParser(
        prog="titan", description=__doc__.split("\n\n")[0] if __doc__ else ""
    )
    parser.add_argument("--version", action="version", version=f"titan {__version__}")
    sub = parser.add_subparsers(dest="command")
    for command, help_text in (
        ("new", "provision a new app, or finish one"),
        ("golive", "point the app's domain at it"),
        ("status", "show what exists and what is missing"),
    ):
        p = sub.add_parser(command, help=help_text)
        p.add_argument("app", help="the app's slug, e.g. gondola")
        if command != "status":
            mode = p.add_mutually_exclusive_group()
            mode.add_argument("--commit", action="store_true", help="apply without asking")
            mode.add_argument("--plan", action="store_true", help="show the plan only")
        p.add_argument("--deploy-timeout", type=float, default=900, help="seconds per deploy")
        if command == "new":
            p.add_argument("--name", default="", help="display name (default: from the slug)")
            p.add_argument(
                "--dir", type=Path, default=Path.cwd(), help="where to generate the repo"
            )
        if command == "golive":
            p.add_argument("--verify-timeout", type=float, default=600, help="seconds for DNS")
    return parser.parse_args(argv)


def pick_workspace(render: Render, settings: Settings, ask: Ask | None) -> tuple[str, str]:
    """The Render workspace (id, name) to act in."""
    workspaces = render.workspaces()
    if settings.render_workspace:
        match = [w for w in workspaces if settings.render_workspace in (w.get("id"), w.get("name"))]
        if not match:
            raise TitanError(f"No Render workspace {settings.render_workspace!r} for this key.")
        return str(match[0]["id"]), str(match[0].get("name", ""))
    if len(workspaces) == 1:
        return str(workspaces[0]["id"]), str(workspaces[0].get("name", ""))
    if not workspaces:
        raise TitanError("This Render API key sees no workspaces.")
    if ask is None:
        raise TitanError("The Render key sees several workspaces; set TITAN_RENDER_WORKSPACE.")
    chosen = ask.choose(
        "Which Render workspace?",
        [(f"{w.get('name')} ({w['id']})", str(w["id"])) for w in workspaces],
    )
    name = next(str(w.get("name", "")) for w in workspaces if w["id"] == chosen)
    return chosen, name


def ask_new_app(ask: Ask) -> tuple[str, str, dict[str, str]]:
    """Name, slug and the template answers for a new app."""
    name = ask.text("App name (what people see)", validate=lambda v: bool(v.strip()) or "A name")
    default_slug = re.sub(r"[^a-z0-9-]", "", name.lower().replace(" ", "-").replace("_", "-"))
    slug = ask.text(
        "Slug (repo, service, database, subdomain)",
        default=default_slug,
        validate=lambda v: bool(SLUG.match(v)) or "Lowercase letters, digits and hyphens",
    )
    answers = {
        "description": ask.text("One line describing it", default=f"{name}: a Django PWA"),
        "theme_colour": ask.text(
            "Brand colour (hex)",
            default="#1d4ed8",
            validate=lambda v: bool(HEX.match(v)) or "Like #1d4ed8",
        ),
        "include_mcp": "true" if ask.confirm("Serve an MCP endpoint?", default=True) else "false",
    }
    return name, slug, answers


def ask_existing_app(ask: Ask, render: Render, owner_id: str, settings: Settings) -> str:
    """Pick one of the workspace's Titan apps (web services from the GitHub owner's repos)."""
    prefix = f"https://github.com/{settings.github_owner}/".lower()
    apps = [
        str(s["name"])
        for s in render.web_services(owner_id)
        if str(s.get("repo", "")).lower().startswith(prefix)
    ]
    if not apps:
        return ask.text("App slug", validate=lambda v: bool(SLUG.match(v)) or "A slug")
    return ask.choose("Which app?", [(name, name) for name in apps])


def run(plan: Plan, console: Console, commit: bool, confirm: bool, ask: Ask | None) -> None:
    """Show the plan; run it if committed, or if asked and the answer is yes."""
    view = LiveView(console, open_links=console.is_terminal)
    if not plan.changes:
        execute(plan, view, commit=False)
        console.print("\n[green]Nothing to do.[/green]")
        if plan.finish:
            console.print(plan.finish)
        return
    if not commit:
        execute(plan, view, commit=False)
        if not (confirm and ask and ask.confirm(f"Apply {plan.changes} change(s)?")):
            console.print("\nNothing changed.")
            return
        console.print()
    with view:
        final = execute(plan, view, commit=True)
    if final.finish:
        console.print(f"\n{final.finish}")


def main(argv: list[str] | None = None) -> int:
    """Run titan; returns the exit status."""
    args = parse(argv)
    console = Console(highlight=False)
    interactive = sys.stdin.isatty() and console.is_terminal
    ask = Ask() if interactive else None
    try:
        if args.command is None and ask is None:
            raise TitanError("Not a terminal: give a command, e.g. `titan status gondola`.")

        def secret(label: str) -> str:
            if ask is None:
                raise TitanError(f"{label} is not in 1Password or the config file.")
            return ask.secret(label)

        settings = credentials.load(secret)
        render = Render(settings.render_api_key)
        owner_id, workspace = pick_workspace(render, settings, ask)
        header(console, settings.sources, workspace)

        command: str | None = args.command
        name: str = getattr(args, "name", "")
        answers: dict[str, str] = {}
        if command is None:
            if ask is None:  # unreachable: checked above
                raise TitanError("Not a terminal.")
            command = ask.choose(
                "What do you want to do?",
                [
                    ("Create a new app (or finish one)", "new"),
                    ("Go live on the custom domain", "golive"),
                    ("Status of an app", "status"),
                ],
            )
            if command == "new":
                name, slug, answers = ask_new_app(ask)
            else:
                slug = ask_existing_app(ask, render, owner_id, settings)
        else:
            slug = args.app
        app = App.from_slug(slug, settings, name)
        ctx = Context(
            app=app,
            render=render,
            resend=Resend(settings.resend_api_key),
            db=SharedDb(settings.db_admin_url),
            github=GitHub(),
            owner_id=owner_id,
            workdir=getattr(args, "dir", None) or Path.cwd(),
            answers=answers,
            deploy_timeout=getattr(args, "deploy_timeout", 900),
            verify_timeout=getattr(args, "verify_timeout", 600),
        )
        commit = bool(getattr(args, "commit", False))
        confirm = not getattr(args, "plan", False)
        if command == "status":
            console.print(f"[bold]{app.name}[/bold]  new")
            run(plan_new(ctx), console, commit=False, confirm=False, ask=None)
            if ctx.web is not None:
                console.print(f"\n[bold]{app.name}[/bold]  go-live")
                run(plan_golive(ctx), console, commit=False, confirm=False, ask=None)
        elif command == "new":
            run(plan_new(ctx), console, commit, confirm, ask)
        else:
            run(plan_golive(ctx), console, commit, confirm, ask)
    except TitanError as exc:
        console.print(f"\n[red]✗[/red] {exc}")
        return 1
    except KeyboardInterrupt:
        console.print("\nStopped. Run it again to pick up where it left off.")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
