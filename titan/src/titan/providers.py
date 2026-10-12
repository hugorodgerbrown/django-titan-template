"""The few calls titan makes to Render, Resend, shared-db and GitHub.

Each client takes its transport as an argument (``call`` for the HTTP APIs),
so the tests swap in fakes and nothing here is reached in a test run.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from titan import TitanError, __version__

RENDER_API = "https://api.render.com/v1"
RESEND_API = "https://api.resend.com"
# Render deploy states that end a deploy; only "live" means it worked.
DEPLOY_DONE = {
    "live",
    "deactivated",
    "build_failed",
    "update_failed",
    "canceled",
    "pre_deploy_failed",
}

# ---------------------------------------------------------------- HTTP


def open_https(req: urllib.request.Request | str, timeout: float) -> Any:
    """urlopen, refusing anything but https (no file: or custom schemes)."""
    url = req if isinstance(req, str) else req.full_url
    if not url.startswith("https://"):
        raise TitanError(f"Refusing a non-https URL: {url}")
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 - scheme checked above


def request_json(method: str, url: str, token: str, body: Any = None) -> Any:
    """One JSON request; raises TitanError with the provider's message on failure."""
    data = None if body is None else json.dumps(body).encode()
    # open_https below refuses anything but https.
    req = urllib.request.Request(url, data=data, method=method)  # noqa: S310
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", f"titan/{__version__}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with open_https(req, timeout=30) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise TitanError(f"{method} {url} failed: {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise TitanError(f"{method} {url} failed: {exc.reason}") from exc
    return json.loads(raw) if raw else None


def health(url: str) -> str:
    """GET <url>/healthz once: "200", another status, or the connection error."""
    try:
        with open_https(url.rstrip("/") + "/healthz", timeout=10) as resp:
            return str(resp.status)
    except urllib.error.HTTPError as exc:
        return str(exc.code)
    except (urllib.error.URLError, TimeoutError) as exc:
        return str(getattr(exc, "reason", exc))


def same_repo(a: str, b: str) -> bool:
    """Whether two GitHub URLs name the same repository."""

    def norm(url: str) -> str:
        return url.lower().rstrip("/").removesuffix(".git")

    return norm(a) == norm(b)


def unwrap(rows: list[dict[str, Any]] | None, key: str) -> list[dict[str, Any]]:
    """Render lists come as [{cursor, <key>: {...}}]; return the inner objects."""
    return [row.get(key, row) for row in rows or []]


# ---------------------------------------------------------------- Render


class Render:
    """The Render API calls titan needs."""

    def __init__(self, token: str, call: Callable[..., Any] = request_json) -> None:
        """Keep the token; `call` is swappable for tests."""
        self.token = token
        self.call = call

    def _get(self, path: str) -> Any:
        return self.call("GET", RENDER_API + path, self.token)

    def _paged(self, path: str, key: str, **query: Any) -> list[dict[str, Any]]:
        """Every row of a cursor-paged list."""
        rows: list[dict[str, Any]] = []
        cursor = ""
        while True:
            params = {"limit": 100, **query, **({"cursor": cursor} if cursor else {})}
            page = self._get(f"{path}?{urllib.parse.urlencode(params, doseq=True)}") or []
            rows += unwrap(page, key)
            cursor = page[-1].get("cursor", "") if len(page) == 100 else ""
            if not cursor:
                return rows

    def workspaces(self) -> list[dict[str, Any]]:
        """The workspaces (owners) this key can see: id, name."""
        return unwrap(self._get("/owners?limit=100"), "owner")

    def service(self, name: str, repo: str, kind: str) -> dict[str, Any] | None:
        """The service with this name, built from this repo; None if there is none.

        A same-named service from another repo, or more than one match (the key
        can see several workspaces), is an error: titan overwrites a service's
        credentials and deploys it, so it never guesses.
        """
        named = [s for s in self._paged("/services", "service", name=name) if s.get("name") == name]
        ours = [s for s in named if same_repo(s.get("repo", ""), repo) and s.get("type") == kind]
        if named and not ours:
            raise TitanError(
                f"A Render service named {name!r} exists but is not this app's {kind} from {repo}; "
                "refusing to change it. Pick another slug."
            )
        if len(ours) > 1:
            workspaces = ", ".join(sorted({str(s.get("ownerId")) for s in ours}))
            raise TitanError(
                f"{len(ours)} Render services named {name!r} come from {repo} "
                f"(workspaces {workspaces}); set TITAN_RENDER_WORKSPACE."
            )
        return ours[0] if ours else None

    def web_services(self, owner_id: str) -> list[dict[str, Any]]:
        """Every web service in the workspace, for picking an app by name."""
        rows = self._paged("/services", "service", type="web_service", ownerId=owner_id)
        return sorted(rows, key=lambda s: str(s.get("name")))

    def env(self, service_id: str) -> dict[str, str]:
        """The service's own env vars (not its groups')."""
        rows = self._paged(f"/services/{service_id}/env-vars", "envVar")
        return {r["key"]: r.get("value") or "" for r in rows}

    def set_env(self, service_id: str, key: str, value: str) -> None:
        """Add or update one of the service's own env vars. Takes effect on the next deploy."""
        path = f"/services/{service_id}/env-vars/{urllib.parse.quote(key)}"
        self.call("PUT", RENDER_API + path, self.token, {"value": value})

    def env_group(self, name: str, owner_id: str) -> dict[str, Any] | None:
        """The named group in the workspace, with its envVars and serviceLinks; or None."""
        rows = self._paged("/env-groups", "envGroup", name=name, ownerId=owner_id)
        matches = [g for g in rows if g.get("name") == name]
        if len(matches) > 1:
            raise TitanError(f"{len(matches)} env groups are named {name!r}; keep one.")
        if not matches:
            return None
        group: dict[str, Any] = self._get(f"/env-groups/{matches[0]['id']}")
        return group

    def create_env_group(self, name: str, owner_id: str, env: dict[str, str]) -> dict[str, Any]:
        """Make a group holding these values."""
        body = {
            "name": name,
            "ownerId": owner_id,
            "envVars": [{"key": k, "value": v} for k, v in env.items()],
        }
        group: dict[str, Any] = self.call("POST", f"{RENDER_API}/env-groups", self.token, body)
        return group

    def set_group_env(self, group_id: str, key: str, value: str) -> None:
        """Add or update one key in a group."""
        path = f"/env-groups/{group_id}/env-vars/{urllib.parse.quote(key)}"
        self.call("PUT", RENDER_API + path, self.token, {"value": value})

    def link_group(self, group_id: str, service_id: str) -> None:
        """Link a group to a service; its values apply from the next deploy."""
        self.call("POST", f"{RENDER_API}/env-groups/{group_id}/services/{service_id}", self.token)

    def custom_domains(self, service_id: str) -> list[dict[str, Any]]:
        """The service's custom domains, with verificationStatus."""
        return unwrap(self._get(f"/services/{service_id}/custom-domains"), "customDomain")

    def add_custom_domain(self, service_id: str, name: str) -> None:
        """Attach a custom domain; it stays unverified until DNS points at Render."""
        self.call(
            "POST", f"{RENDER_API}/services/{service_id}/custom-domains", self.token, {"name": name}
        )

    def verify_custom_domain(self, service_id: str, name: str) -> None:
        """Ask Render to check the domain's DNS again."""
        self.call(
            "POST", f"{RENDER_API}/services/{service_id}/custom-domains/{name}/verify", self.token
        )

    def deploy(self, service_id: str) -> str:
        """Start a deploy of the latest commit; returns its id."""
        deploy = self.call("POST", f"{RENDER_API}/services/{service_id}/deploys", self.token, {})
        return str(deploy["id"])

    def deploy_status(self, service_id: str, deploy_id: str) -> str:
        """created, build_in_progress, …, live or a failed state."""
        return str(self._get(f"/services/{service_id}/deploys/{deploy_id}")["status"])

    def latest_deploy(self, service_id: str) -> dict[str, Any] | None:
        """The service's most recent deploy (id, status), or None."""
        rows = unwrap(self._get(f"/services/{service_id}/deploys?limit=1"), "deploy")
        return rows[0] if rows else None


# ---------------------------------------------------------------- Resend


class Resend:
    """The two Resend API calls titan needs."""

    def __init__(self, token: str, call: Callable[..., Any] = request_json) -> None:
        """Keep the token; `call` is swappable for tests."""
        self.token = token
        self.call = call

    def domain_id(self, name: str) -> str:
        """The id of a verified sending domain."""
        domains = self.call("GET", f"{RESEND_API}/domains", self.token)["data"]
        match = next((d for d in domains if d["name"] == name), None)
        if match is None:
            raise TitanError(f"{name} is not a domain on this Resend account.")
        if match.get("status") != "verified":
            raise TitanError(f"{name} is not verified on Resend (status {match.get('status')}).")
        return str(match["id"])

    def create_sending_key(self, name: str, domain_id: str) -> str:
        """A key that can only send, and only from one domain. Returns the token."""
        body = {"name": name[:50], "permission": "sending_access", "domain_id": domain_id}
        return str(self.call("POST", f"{RESEND_API}/api-keys", self.token, body)["token"])


# ---------------------------------------------------------------- Postgres


class SharedDb:
    """Role and database for one app on shared-db, through its admin user."""

    def __init__(self, url: str) -> None:
        """Connect lazily, so a run that never reaches the database never connects."""
        self.url = url
        self._conn: Any = None

    @property
    def conn(self) -> Any:
        """An autocommit connection (CREATE DATABASE cannot run in a transaction)."""
        if self._conn is None:
            import psycopg

            try:
                self._conn = psycopg.connect(self.url, autocommit=True, connect_timeout=10)
            except psycopg.OperationalError as exc:
                raise TitanError(
                    f"Cannot reach shared-db: {exc}. It only accepts the IP addresses on its "
                    "allowlist (Render: shared-db, Networking)."
                ) from exc
        return self._conn

    def _one(self, query: str, *params: Any) -> Any:
        row = self.conn.execute(query, params).fetchone()
        return row[0] if row else None

    def can_provision(self) -> bool:
        """Whether the admin user can create roles and databases."""
        row = self.conn.execute(
            "select rolsuper or (rolcreaterole and rolcreatedb)"
            " from pg_roles where rolname = current_user"
        ).fetchone()
        return bool(row and row[0])

    def role_exists(self, name: str) -> bool:
        """Whether a role with this name exists."""
        return bool(self._one("select 1 from pg_roles where rolname = %s", name))

    def database_exists(self, name: str) -> bool:
        """Whether a database with this name exists."""
        return bool(self._one("select 1 from pg_database where datname = %s", name))

    def ensure(self, name: str, password: str | None) -> None:
        """Create or re-key the role, create its database, and shut everyone else out.

        `password` None leaves an existing role's password alone.
        """
        from psycopg import sql

        ident = sql.Identifier(name)
        if not self.role_exists(name):
            self.conn.execute(
                sql.SQL("create role {} login password {}").format(ident, sql.Literal(password))
            )
        elif password is not None:
            self.conn.execute(
                sql.SQL("alter role {} login password {}").format(ident, sql.Literal(password))
            )
        # Postgres 16+: the creator must be able to SET ROLE to hand a database to it.
        self.conn.execute(sql.SQL("grant {} to current_user").format(ident))
        if not self.database_exists(name):
            self.conn.execute(sql.SQL("create database {} owner {}").format(ident, ident))
        # Every role may connect to every database unless PUBLIC loses the right.
        self.conn.execute(sql.SQL("revoke all on database {} from public").format(ident))
        self.conn.execute(sql.SQL("grant connect on database {} to {}").format(ident, ident))


# ---------------------------------------------------------------- GitHub


class GitHub:
    """The repository checks and the generation step, through ``gh`` and ``uvx``."""

    template = "gh:hugorodgerbrown/django-titan-template"

    def __init__(
        self,
        run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        """`run` is swappable for tests."""
        self.run = run

    def _need(self, tool: str, hint: str) -> None:
        if shutil.which(tool) is None:
            raise TitanError(f"{tool} is not installed ({hint}).")

    def repo_exists(self, repo: str) -> bool:
        """Whether `gh` can see the repository."""
        self._need("gh", "https://cli.github.com, then `gh auth login`")
        result = self.run(["gh", "repo", "view", repo], capture_output=True, text=True, check=False)
        return result.returncode == 0

    def blueprint_declares(self, repo: str, name: str) -> bool:
        """Whether the repo's render.yaml declares a service with this name.

        If the file can't be read, the answer is yes, so a missing service
        is waited for rather than skipped.
        """
        result = self.run(
            [
                "gh",
                "api",
                f"repos/{repo}/contents/render.yaml",
                "-H",
                "Accept: application/vnd.github.raw",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return True
        pattern = rf"^\s*name:\s*['\"]?{re.escape(name)}['\"]?\s*(#.*)?$"
        return re.search(pattern, result.stdout, re.M) is not None

    def generate(self, answers: dict[str, str], repo: str, workdir: Path) -> Path:
        """Copier copy from the template with these answers, then create the repo and push.

        Copier runs with --defaults, so any question titan did not ask takes
        the template's default rather than prompting under the live display.
        """
        self._need("uvx", "https://docs.astral.sh/uv/")
        target = (workdir / answers["project_slug"]).resolve()
        if target.exists():
            raise TitanError(f"{target} already exists; move it or run from another directory.")
        data = [arg for key, value in answers.items() for arg in ("--data", f"{key}={value}")]
        steps = [
            ["uvx", "copier", "copy", "--trust", "--defaults", *data, self.template, str(target)],
            ["git", "add", "-A"],
            ["git", "commit", "--quiet", "-m", "Generate from django-titan-template"],
            ["gh", "repo", "create", repo, "--private", "--source", str(target), "--push"],
        ]
        for args in steps:
            cwd = None if args[0] == "uvx" else target
            result = self.run(args, cwd=cwd, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                tail = (result.stderr or result.stdout or "").strip().splitlines()[-3:]
                raise TitanError(f"{' '.join(args[:3])} … failed: {' / '.join(tail)}")
        return target
