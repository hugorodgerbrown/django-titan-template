"""Where titan's account-wide keys come from.

In order: a 1Password item (``Titan`` by default, one field per key, read
with the ``op`` CLI), then ``~/.config/titan/env`` (KEY=value lines), then
a hidden prompt. Never the environment: a shell inside an app's checkout
often exports that app's own RESEND_API_KEY or a DATABASE_URL-style value,
and titan must not pick those up by mistake.

The non-secret TITAN_* overrides (domain, mail domain, GitHub owner,
1Password item and vault) may come from the environment or the file.

FIVEBAR_API_KEY is optional: it comes from 1Password or the file, and is
never asked for. Without it, `golive` lists adding the fivebar site as a
step to do by hand.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from titan import TitanError

CONFIG_FILE = Path.home() / ".config" / "titan" / "env"
OP_ITEM = "Titan"
# Field label (in 1Password, and key in the file) → what it is.
SECRET_KEYS = {
    "RENDER_API_KEY": "Render API key",
    "RESEND_API_KEY": "Resend full-access API key",
    "TITAN_DB_ADMIN_URL": "shared-db External Database URL",
}
# Read like the secrets above, but never asked for: titan works without them.
OPTIONAL_SECRET_KEYS = {
    "FIVEBAR_API_KEY": "fivebar API token that can add sites",
}
OPTION_KEYS = (
    "TITAN_DOMAIN",
    "TITAN_MAIL_DOMAIN",
    "TITAN_GITHUB_OWNER",
    "TITAN_DB_INTERNAL_HOST",
    "TITAN_RENDER_WORKSPACE",
    "TITAN_OP_ITEM",
    "TITAN_OP_VAULT",
)

Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def run_capture(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a command and capture its output; never raises on a non-zero exit."""
    return subprocess.run(args, capture_output=True, text=True, check=False)


@dataclass(frozen=True)
class Settings:
    """Credentials and defaults, plus where each key came from."""

    render_api_key: str
    resend_api_key: str
    db_admin_url: str
    domain: str = "ultraniche.ai"
    mail_domain: str = "mail.ultraniche.ai"
    github_owner: str = "hugorodgerbrown"
    db_internal_host: str = ""
    render_workspace: str = ""
    fivebar_api_key: str = ""
    sources: Mapping[str, str] = field(default_factory=dict)


def read_env_file(path: Path) -> dict[str, str]:
    """Parse KEY=value lines; blank lines and # comments are skipped."""
    if not path.exists():
        return {}
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    return values


def field_key(label: str) -> str:
    """A field label as titan's key: ``render api key`` and ``Render-API-Key`` match."""
    return "_".join(label.replace("-", " ").upper().split())


def op_hint(error: str, item: str) -> str:
    """What to do about an ``op`` error, or "" when there is nothing useful to add."""
    lowered = error.lower()
    if "desktop app" in lowered:
        return (
            "open and unlock the 1Password app, and turn on Settings > Developer > "
            "Integrate with 1Password CLI"
        )
    if "not currently signed in" in lowered or "no accounts" in lowered or "sign in" in lowered:
        return (
            "run `op signin`, or turn on Settings > Developer > "
            "Integrate with 1Password CLI in the 1Password app"
        )
    if "unknown flag" in lowered:
        return "update the 1Password CLI (`brew upgrade 1password-cli`); titan needs op 2.21+"
    if "more than one item" in lowered:
        return "set TITAN_OP_VAULT to the vault that holds it"
    if "isn't an item" in lowered or "not found" in lowered:
        return f"name the item {item!r}, or set TITAN_OP_ITEM (and TITAN_OP_VAULT)"
    return ""


def read_1password(
    item: str, vault: str = "", run: Runner = run_capture
) -> tuple[dict[str, str], str]:
    """The item's fields whose labels are titan's keys, and why any are missing.

    One ``op item get`` call, so 1Password asks to unlock once. A missing
    ``op``, a locked app the user declines, or no such item all mean "not
    from 1Password", and the next source is tried; the second value says
    which it was ("" when every required key was there), so titan can say
    why before it asks.
    """
    if shutil.which("op") is None:
        return {}, "the 1Password CLI `op` is not on the PATH"
    args = ["op", "item", "get", item, "--format", "json", "--reveal"]
    if vault:
        args += ["--vault", vault]
    result = run(args)
    if result.returncode != 0:
        lines = (result.stderr or "").strip().splitlines()
        # op prefixes its errors with "[ERROR] 2026/11/18 14:28:01 ".
        error = re.sub(r"^\[ERROR\]\s+\S+\s+\S+\s+", "", lines[0]) if lines else ""
        error = error or f"exit status {result.returncode}"
        hint = op_hint(error, item)
        return {}, f"`op item get {item}` failed: {error}" + (f" ({hint})" if hint else "")
    try:
        fields = json.loads(result.stdout).get("fields", [])
    except (json.JSONDecodeError, AttributeError):
        return {}, f"`op item get {item}` did not return JSON"
    values = {}
    labels = []
    for item_field in fields:
        label = str(item_field.get("label", ""))
        labels.append(label)
        key = field_key(label)
        value = str(item_field.get("value") or "")
        if (key in SECRET_KEYS or key in OPTIONAL_SECRET_KEYS) and value:
            values[key] = value
    missing = [key for key in SECRET_KEYS if key not in values]
    if not missing:
        return values, ""
    found = ", ".join(repr(label) for label in labels if label) or "none"
    return values, (
        f"1Password item {item!r} has no filled-in field labelled {', '.join(missing)} "
        f"(its fields: {found})"
    )


def load(
    ask: Callable[[str], str],
    environ: Mapping[str, str] | None = None,
    path: Path | None = None,
    op: Callable[[str, str], tuple[dict[str, str], str]] | None = None,
    warn: Callable[[str], None] | None = None,
) -> Settings:
    """Gather the keys from 1Password, the file, or ``ask`` (hidden), in that order.

    Before the first prompt, ``warn`` is told why 1Password didn't supply
    the key, so a broken ``op`` set-up never looks like a silent prompt.
    """
    path = path or CONFIG_FILE
    op = op or read_1password
    environ = os.environ if environ is None else environ
    file_values = read_env_file(path)
    options = {k: file_values.get(k, "") for k in OPTION_KEYS}
    options.update({k: environ[k] for k in OPTION_KEYS if environ.get(k)})

    values: dict[str, str] = {}
    sources: dict[str, str] = {}
    item = options["TITAN_OP_ITEM"] or OP_ITEM
    op_values, op_problem = op(item, options["TITAN_OP_VAULT"])
    for key, value in op_values.items():
        values[key], sources[key] = value, f"1Password item {item!r}"
    for key in (*SECRET_KEYS, *OPTIONAL_SECRET_KEYS):
        if not values.get(key) and file_values.get(key):
            values[key], sources[key] = file_values[key], str(path)
    unfilled = [key for key in SECRET_KEYS if not values.get(key)]
    if unfilled and op_problem and warn is not None:
        warn(f"Not from 1Password: {op_problem}.")
    for key, label in SECRET_KEYS.items():
        if not values.get(key):
            values[key] = ask(f"{label} ({key})").strip()
            sources[key] = "typed in"
        if not values[key]:
            raise TitanError(
                f"No {key} given. Add it as a field named {key} on the 1Password item "
                f"{item!r}, or to {path}."
            )
    return Settings(
        render_api_key=values["RENDER_API_KEY"],
        resend_api_key=values["RESEND_API_KEY"],
        db_admin_url=values["TITAN_DB_ADMIN_URL"],
        domain=options["TITAN_DOMAIN"] or Settings.domain,
        mail_domain=options["TITAN_MAIL_DOMAIN"] or Settings.mail_domain,
        github_owner=options["TITAN_GITHUB_OWNER"] or Settings.github_owner,
        db_internal_host=options["TITAN_DB_INTERNAL_HOST"],
        render_workspace=options["TITAN_RENDER_WORKSPACE"],
        fivebar_api_key=values.get("FIVEBAR_API_KEY", ""),
        sources=sources,
    )
