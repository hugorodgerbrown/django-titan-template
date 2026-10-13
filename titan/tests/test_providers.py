"""Tests for titan.providers: the API clients, with the transport faked."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from titan import TitanError
from titan.providers import Fivebar, GitHub, Render, Resend

TALLY = {"type": "web_service", "repo": "https://github.com/hugorodgerbrown/tally"}
REPO = "https://github.com/hugorodgerbrown/tally"


def test_render_unwraps_lists_and_pages_env_vars() -> None:
    """Lists are unwrapped and followed by cursor while pages are full."""

    def call(method: str, url: str, token: str, body: Any = None) -> Any:
        if "/services?" in url:
            return [
                {"cursor": "c", "service": {"id": "srv-x", "name": "tally-purge", **TALLY}},
                {"cursor": "d", "service": {"id": "srv-y", "name": "tally", **TALLY}},
            ]
        if "cursor=c99" in url:
            return [{"cursor": "z", "envVar": {"key": "LAST", "value": "1"}}]
        return [{"cursor": f"c{i}", "envVar": {"key": f"K{i}", "value": "v"}} for i in range(100)]

    render = Render("tok", call)
    assert render.service("tally", REPO, "web_service") == {"id": "srv-y", "name": "tally", **TALLY}
    env = render.env("srv-y")
    assert len(env) == 101
    assert env["LAST"] == "1"


def test_render_sends_env_values_as_json() -> None:
    """A service env var is a PUT with the value as JSON."""
    sent: list[tuple[str, str, Any]] = []
    Render("tok", lambda m, u, t, b=None: sent.append((m, u, b))).set_env(
        "srv-1", "SITE_URL", "https://x"
    )
    assert sent == [
        (
            "PUT",
            "https://api.render.com/v1/services/srv-1/env-vars/SITE_URL",
            {"value": "https://x"},
        )
    ]


def test_render_env_groups() -> None:
    """Find a group by name in the workspace, read it whole, create, write and link."""
    sent: list[tuple[str, str, Any]] = []

    def call(method: str, url: str, token: str, body: Any = None) -> Any:
        sent.append((method, url, body))
        if method == "GET" and "/env-groups?" in url:
            return [{"id": "evg-1", "name": "titan"}, {"id": "evg-2", "name": "titan-old"}]
        if method == "GET":
            return {"id": "evg-1", "name": "titan", "envVars": [], "serviceLinks": []}
        return {"id": "evg-3"}

    render = Render("tok", call)
    group = render.env_group("titan", "tea-1")
    assert group is not None
    assert group["id"] == "evg-1"
    assert "name=titan" in sent[0][1]
    assert "ownerId=tea-1" in sent[0][1]
    render.create_env_group("tally", "tea-1", {"A": "1"})
    render.set_group_env("evg-1", "B", "2")
    render.link_group("evg-1", "srv-1")
    assert sent[2:] == [
        (
            "POST",
            "https://api.render.com/v1/env-groups",
            {"name": "tally", "ownerId": "tea-1", "envVars": [{"key": "A", "value": "1"}]},
        ),
        ("PUT", "https://api.render.com/v1/env-groups/evg-1/env-vars/B", {"value": "2"}),
        ("POST", "https://api.render.com/v1/env-groups/evg-1/services/srv-1", None),
    ]


def test_render_has_no_group_by_that_name() -> None:
    """None when the workspace has no such group."""
    assert Render("tok", lambda *a, **k: []).env_group("titan", "tea-1") is None


def test_render_refuses_a_same_named_service_from_another_repo() -> None:
    """A service called tally that Tally's repo did not make is never touched."""
    rows = [
        {
            "service": {
                "id": "x",
                "name": "tally",
                "type": "web_service",
                "repo": "https://github.com/o/e",
            }
        }
    ]
    with pytest.raises(TitanError, match="refusing to change it"):
        Render("tok", lambda *a, **k: rows).service("tally", REPO, "web_service")


def test_render_refuses_matches_in_two_workspaces() -> None:
    """Two matching services means the key sees two workspaces: stop, don't guess."""
    service = {"name": "tally", "type": "web_service", "repo": REPO + ".git"}
    rows = [
        {"service": {**service, "id": "a", "ownerId": "tea-1"}},
        {"service": {**service, "id": "b", "ownerId": "tea-2"}},
    ]
    with pytest.raises(TitanError, match="workspaces tea-1, tea-2"):
        Render("tok", lambda *a, **k: rows).service("tally", REPO, "web_service")


def test_render_matches_on_repo_and_type() -> None:
    """The web service and the cron job share a repo; the type tells them apart."""
    repo = "https://github.com/HugoRodgerBrown/tally/"
    rows = [
        {"service": {"id": "w", "name": "tally", "type": "web_service", "repo": repo}},
        {"service": {"id": "c", "name": "tally", "type": "cron_job", "repo": repo}},
    ]
    found = Render("tok", lambda *a, **k: rows).service("tally", REPO, "cron_job")
    assert found is not None
    assert found["id"] == "c"


def test_resend_makes_a_sending_only_key_for_one_domain() -> None:
    """The per-app key can only send, and only from the shared domain."""
    sent: list[Any] = []

    def call(method: str, url: str, token: str, body: Any = None) -> Any:
        if method == "GET":
            return {"data": [{"id": "dom-1", "name": "mail.ultraniche.ai", "status": "verified"}]}
        sent.append(body)
        return {"id": "key-1", "token": "re_new"}

    resend = Resend("re_full", call)
    assert resend.create_sending_key("tally", resend.domain_id("mail.ultraniche.ai")) == "re_new"
    assert sent == [{"name": "tally", "permission": "sending_access", "domain_id": "dom-1"}]


@pytest.mark.parametrize(
    ("domains", "message"),
    [
        ([], "not a domain"),
        ([{"id": "d", "name": "mail.ultraniche.ai", "status": "pending"}], "not verified"),
    ],
)
def test_resend_refuses_a_missing_or_unverified_domain(
    domains: list[dict[str, str]], message: str
) -> None:
    """Only a verified domain can carry an app's mail."""
    with pytest.raises(TitanError, match=message):
        Resend("re_full", lambda *a, **k: {"data": domains}).domain_id("mail.ultraniche.ai")


class Recorder:
    """A subprocess.run stand-in."""

    def __init__(self, code: int = 0, stdout: str = "") -> None:
        """Answer every call the same way."""
        self.code, self.stdout = code, stdout
        self.calls: list[tuple[list[str], Path | None]] = []

    def __call__(self, args: list[str], cwd: Path | None = None, **_: Any) -> Any:
        """Record and answer."""
        self.calls.append((args, cwd))
        return subprocess.CompletedProcess(args, self.code, stdout=self.stdout, stderr="boom")


def test_blueprint_declares_reads_render_yaml() -> None:
    """The service must appear as a name: line; an unreadable file counts as declared."""
    run = Recorder(
        stdout="services:\n  - type: web\n    name: tally\n  - type: cron\n    name: tally-purge\n"
    )
    github = GitHub(run)
    assert github.blueprint_declares("o/tally", "tally-purge")
    run.stdout = "services:\n  - type: web\n    name: tally\n"
    assert not github.blueprint_declares("o/tally", "tally-purge")
    run.stdout = "services:\n  - type: cron\n    name: 'tally-purge'  # clean-up\n"
    assert github.blueprint_declares("o/tally", "tally-purge")
    run.code = 1
    assert github.blueprint_declares("o/tally", "tally-purge")


def test_generate_passes_the_answers_and_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Copier gets every answer, then the checkout is committed; nothing is pushed."""
    monkeypatch.setattr("titan.providers.shutil.which", lambda name: f"/bin/{name}")
    monkeypatch.chdir(tmp_path)
    run = Recorder()
    target = GitHub(run).generate({"project_name": "Tally", "project_slug": "tally"}, Path("."))
    assert target == tmp_path / "tally"
    copier, _ = run.calls[0]
    assert copier[:5] == ["uvx", "copier", "copy", "--trust", "--defaults"]
    assert "project_name=Tally" in copier
    assert [args[:2] for args, _ in run.calls[1:]] == [["git", "add"], ["git", "commit"]]
    assert all(cwd == tmp_path / "tally" for _, cwd in run.calls[1:])


def test_publish_creates_the_private_repo_from_the_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The repo is created from, and pushed from, the absolute checkout path."""
    monkeypatch.setattr("titan.providers.shutil.which", lambda name: f"/bin/{name}")
    run = Recorder()
    GitHub(run).publish("o/tally", tmp_path / "tally")
    ((gh_args, gh_cwd),) = run.calls
    assert gh_args[:4] == ["gh", "repo", "create", "o/tally"]
    assert "--private" in gh_args
    assert "--push" in gh_args
    assert gh_args[gh_args.index("--source") + 1] == str(tmp_path / "tally")
    assert gh_cwd == tmp_path / "tally"


def test_generate_reports_a_failed_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failing command stops generation with its last lines."""
    monkeypatch.setattr("titan.providers.shutil.which", lambda name: f"/bin/{name}")
    with pytest.raises(TitanError, match="uvx copier copy … failed: boom"):
        GitHub(Recorder(code=1)).generate({"project_slug": "tally"}, tmp_path)


def test_render_domains_deploys_and_workspaces() -> None:
    """The remaining Render calls hit the documented paths."""
    sent: list[tuple[str, str]] = []

    def call(method: str, url: str, token: str, body: Any = None) -> Any:
        sent.append((method, url.removeprefix("https://api.render.com/v1")))
        if url.endswith("/deploys") and method == "POST":
            return {"id": "dep-9"}
        if "/deploys/" in url:
            return {"status": "live"}
        if "/deploys?" in url:
            return [{"cursor": "x", "deploy": {"id": "dep-8", "status": "build_in_progress"}}]
        if "/owners" in url:
            return [{"cursor": "x", "owner": {"id": "tea-1", "name": "Ultraniche"}}]
        if "/services?" in url:
            return [
                {"service": {"id": "b", "name": "zeta"}},
                {"service": {"id": "a", "name": "alpha"}},
            ]
        return [{"cursor": "x", "customDomain": {"name": "x.ultraniche.ai"}}]

    render = Render("tok", call)
    assert render.workspaces() == [{"id": "tea-1", "name": "Ultraniche"}]
    assert [s["name"] for s in render.web_services("tea-1")] == ["alpha", "zeta"]
    assert render.custom_domains("srv-1") == [{"name": "x.ultraniche.ai"}]
    render.add_custom_domain("srv-1", "x.ultraniche.ai")
    render.verify_custom_domain("srv-1", "x.ultraniche.ai")
    assert render.deploy("srv-1") == "dep-9"
    assert render.deploy_status("srv-1", "dep-9") == "live"
    assert render.latest_deploy("srv-1") == {"id": "dep-8", "status": "build_in_progress"}
    assert ("POST", "/services/srv-1/custom-domains/x.ultraniche.ai/verify") in sent


def test_open_https_refuses_other_schemes() -> None:
    """Only https URLs are ever opened."""
    from titan.providers import open_https

    with pytest.raises(TitanError, match="non-https"):
        open_https("file:///etc/passwd", timeout=1)


class FakeConn:
    """A psycopg connection that records statements as text."""

    def __init__(self, roles: set[str], databases: set[str]) -> None:
        """Start with these roles and databases."""
        self.roles, self.databases = roles, databases
        self.statements: list[str] = []

    def execute(self, query: Any, params: tuple[Any, ...] = ()) -> Any:
        """Answer the lookups; record everything else."""
        text = query if isinstance(query, str) else query.as_string(None)
        self.statements.append(text)
        name = params[0] if params else None
        found = {
            "rolsuper": True,
            "pg_roles where rolname": name in self.roles,
            "pg_database": name in self.databases,
        }
        row = next(((v,) for k, v in found.items() if k in text), None)
        return type("Cursor", (), {"fetchone": lambda self: row if row and row[0] else None})()


def test_shared_db_creates_and_locks_down_a_database() -> None:
    """A new role, its own database, and PUBLIC's connect right revoked."""
    from titan.providers import SharedDb

    db = SharedDb("postgresql://admin@h/db")
    conn = FakeConn(set(), set())
    db._conn = conn
    assert db.can_provision()
    db.ensure("tally", "secret")
    joined = "\n".join(conn.statements)
    assert "create role \"tally\" login password 'secret'" in joined
    assert 'create database "tally" owner "tally"' in joined
    assert 'revoke all on database "tally" from public' in joined


def test_shared_db_rekeys_an_existing_role() -> None:
    """An existing role gets the new password; None leaves it alone."""
    from titan.providers import SharedDb

    db = SharedDb("postgresql://admin@h/db")
    conn = FakeConn({"tally"}, {"tally"})
    db._conn = conn
    db.ensure("tally", "new")
    assert any("alter role" in s for s in conn.statements)
    conn.statements.clear()
    db.ensure("tally", None)
    assert not any("alter role" in s or "create" in s for s in conn.statements)


def test_render_looks_for_services_in_the_chosen_workspace_only() -> None:
    """With a workspace, the query names it and a service from another is ignored."""
    urls: list[str] = []
    service = {"name": "tally", "type": "web_service", "repo": REPO}
    rows = [
        {"service": {**service, "id": "a", "ownerId": "tea-1"}},
        {"service": {**service, "id": "b", "ownerId": "tea-2"}},
    ]

    def call(method: str, url: str, token: str, body: Any = None) -> Any:
        urls.append(url)
        return rows

    found = Render("tok", call).service("tally", REPO, "web_service", "tea-2")
    assert found is not None
    assert found["id"] == "b"
    assert "ownerId=tea-2" in urls[0]


def test_fivebar_finds_and_adds_a_site() -> None:
    """The site list is read for the domain; adding one is a POST of the domain."""
    sent: list[tuple[str, str, Any]] = []

    def call(method: str, url: str, token: str, body: Any = None) -> Any:
        sent.append((method, url, body))
        assert token == "fivebar_tok"
        if method == "GET":
            return {"sites": [{"domain": "traintrackr.live"}], "count": 1}
        return {"site": {"domain": body["domain"]}, "tag": "<script ...>"}

    fivebar = Fivebar("fivebar_tok", call)
    assert fivebar.has_site("traintrackr.live")
    assert not fivebar.has_site("tally.ultraniche.ai")
    fivebar.add_site("tally.ultraniche.ai")
    assert sent[-1] == (
        "POST",
        "https://fiveb.ar/api/sites",
        {"domain": "tally.ultraniche.ai"},
    )


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        ('409 {"error": "domain taken"}', "a fivebar site on another account"),
        ('403 {"error": "token cannot add sites"}', "cannot add sites: allow it"),
        ('502 {"error": "site could not be added"}', "502"),
    ],
)
def test_fivebar_says_why_a_site_was_not_added(failure: str, message: str) -> None:
    """A taken domain or a read-only token is named; anything else passes through."""

    def call(method: str, url: str, token: str, body: Any = None) -> Any:
        raise TitanError(f"{method} {url} failed: {failure}")

    with pytest.raises(TitanError, match=message):
        Fivebar("fivebar_tok", call).add_site("tally.ultraniche.ai")
