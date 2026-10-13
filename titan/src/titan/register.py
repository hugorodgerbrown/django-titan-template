"""The register of Titan apps: ``apps.json`` at the root of the template repo.

One entry per app made from the template, so anything that has to reach
every app (the routine that runs ``copier update`` in each) reads one file
rather than guessing from GitHub. titan writes it: ``new`` adds the app at
stage ``new``, and ``golive`` moves it to ``live``. Nobody has to keep it
by hand, though anyone can edit it in a PR.

titan owns ``slug``, ``repo``, ``domain`` and ``stage``. ``name`` is set
once, and ``updates`` (whether the routine opens copier update PRs for the
app) starts true and is never changed by titan, so a hand edit pausing an
app's updates survives every later run.
"""

from __future__ import annotations

import json
from typing import Any

from titan import TitanError
from titan.app import App

# Where the register lives: next to the template it registers apps of.
REPO = "hugorodgerbrown/django-titan-template"
PATH = "apps.json"
STAGES = ("new", "live")
FIELDS = ("slug", "name", "repo", "domain", "stage", "updates")


def parse(text: str) -> list[dict[str, Any]]:
    """The register's entries; an empty or missing file is an empty register."""
    if not text.strip():
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TitanError(f"{PATH} in {REPO} is not valid JSON: {exc}.") from None
    apps = data.get("apps") if isinstance(data, dict) else None
    if not isinstance(apps, list):
        raise TitanError(f'{PATH} in {REPO} should be {{"apps": [...]}}.')
    for entry in apps:
        missing = [key for key in FIELDS if key not in entry]
        if missing:
            raise TitanError(f"{PATH}: {entry.get('slug', '?')} has no {', '.join(missing)}.")
        if entry["stage"] not in STAGES:
            raise TitanError(f"{PATH}: {entry['slug']}'s stage should be one of {STAGES}.")
    return apps


def render(apps: list[dict[str, Any]]) -> str:
    """The file's text: sorted by slug, fields in a fixed order, so diffs stay small."""
    rows = [
        {key: entry[key] for key in FIELDS} | {k: v for k, v in entry.items() if k not in FIELDS}
        for entry in sorted(apps, key=lambda e: str(e["slug"]))
    ]
    return json.dumps({"apps": rows}, indent=2, ensure_ascii=False) + "\n"


def find(apps: list[dict[str, Any]], slug: str) -> dict[str, Any] | None:
    """The app's entry, if it has one."""
    return next((entry for entry in apps if entry["slug"] == slug), None)


def record(apps: list[dict[str, Any]], app: App, stage: str) -> list[dict[str, Any]]:
    """The register with the app at this stage; ``live`` never goes back to ``new``."""
    current = find(apps, app.slug)
    entry = dict(current or {"name": app.name, "updates": True})
    entry.update(slug=app.slug, repo=app.repo, domain=app.domain)
    entry["stage"] = "live" if "live" in (stage, entry.get("stage")) else stage
    return [e for e in apps if e["slug"] != app.slug] + [entry]


def is_current(apps: list[dict[str, Any]], app: App, stage: str) -> bool:
    """Whether recording the app at this stage would change nothing."""
    return find(record(apps, app, stage), app.slug) == find(apps, app.slug)
