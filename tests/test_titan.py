"""Tests for bin/titan, the Titan app provisioner.

Every provider is faked: nothing here touches Render, Resend, GitHub or a
database. Run with:

    uv run --with pytest --with 'psycopg[binary]' pytest tests
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_PATH = Path(__file__).resolve().parents[1] / "bin" / "titan"
_loader = importlib.machinery.SourceFileLoader("titan", str(_PATH))
_spec = importlib.util.spec_from_loader("titan", _loader)
assert _spec is not None
titan = importlib.util.module_from_spec(_spec)
sys.modules["titan"] = titan
_loader.exec_module(titan)
# The autouse fixture fakes this; its own test needs the real one.
BLUEPRINT_DECLARES = titan.blueprint_declares

ADMIN_URL = "postgresql://shared_db_user:pw@dpg-abc123-a.frankfurt-postgres.render.com/shared_db"


@pytest.fixture
def settings() -> Any:
    """Settings with fake credentials and the real defaults."""
    return titan.Settings(render_api_key="rnd", resend_api_key="re_full", db_admin_url=ADMIN_URL)


@pytest.fixture
def app(settings: Any) -> Any:
    """The worked example: Tally."""
    return titan.App.from_slug("tally", settings)


class FakeRender:
    """Render in memory: services by name, env vars, custom domains, deploys."""

    def __init__(self, services: bool = True) -> None:
        """Start with the Blueprint's two services, or none."""
        self.services: dict[str, dict[str, Any]] = {}
        if services:
            self.services["tally"] = {
                "id": "srv-web",
                "name": "tally",
                "serviceDetails": {"url": "https://tally-s2nb.onrender.com"},
            }
            self.services["tally-purge"] = {"id": "crn-cron", "name": "tally-purge"}
        self.envs: dict[str, dict[str, str]] = {
            "srv-web": {"DJANGO_SECRET_KEY": "generated"},
            "crn-cron": {},
        }
        self.domains: dict[str, list[dict[str, Any]]] = {"srv-web": []}
        self.writes: list[tuple[str, str, str]] = []
        self.deploys: list[str] = []
        self.verify_flips = True

    def service(self, name: str, repo: str, kind: str) -> dict[str, Any] | None:
        """The service with this name, or None; checks the caller asks for the right one."""
        assert repo == "https://github.com/hugorodgerbrown/tally"
        assert kind == ("cron_job" if name.endswith("-purge") else "web_service")
        return self.services.get(name)

    def env(self, service_id: str) -> dict[str, str]:
        """A copy of the service's env vars."""
        return dict(self.envs[service_id])

    def set_env(self, service_id: str, key: str, value: str) -> None:
        """Store one env var and record the write."""
        self.envs[service_id][key] = value
        self.writes.append((service_id, key, value))

    def custom_domains(self, service_id: str) -> list[dict[str, Any]]:
        """The service's custom domains."""
        return list(self.domains[service_id])

    def add_custom_domain(self, service_id: str, name: str) -> None:
        """Attach an unverified domain."""
        self.domains[service_id].append({"name": name, "verificationStatus": "unverified"})

    def verify_custom_domain(self, service_id: str, name: str) -> None:
        """Mark the domain verified, unless DNS is "broken"."""
        if self.verify_flips:
            for domain in self.domains[service_id]:
                if domain["name"] == name:
                    domain["verificationStatus"] = "verified"

    def deploy(self, service_id: str) -> str:
        """Record a deploy."""
        self.deploys.append(service_id)
        return "dep-1"

    def deploy_status(self, service_id: str, deploy_id: str) -> str:
        """Every deploy goes live."""
        return "live"


class FakeResend:
    """Resend in memory: one verified domain; records the keys it makes."""

    def __init__(self) -> None:
        """No keys yet."""
        self.keys: list[tuple[str, str]] = []

    def domain_id(self, name: str) -> str:
        """The one verified domain."""
        assert name == "mail.ultraniche.ai"
        return "dom-1"

    def create_sending_key(self, name: str, domain_id: str) -> str:
        """Record the key and return a fake token."""
        self.keys.append((name, domain_id))
        return "re_app_key"


class FakeDb:
    """shared-db in memory."""

    def __init__(
        self, roles: set[str] | None = None, databases: set[str] | None = None, allowed: bool = True
    ) -> None:
        """Start with the given roles and databases."""
        self.roles = roles or set()
        self.databases = databases or set()
        self.allowed = allowed
        self.ensured: list[tuple[str, str | None]] = []

    def can_provision(self) -> bool:
        """Whether the admin may create roles."""
        return self.allowed

    def role_exists(self, name: str) -> bool:
        """Whether the role exists."""
        return name in self.roles

    def database_exists(self, name: str) -> bool:
        """Whether the database exists."""
        return name in self.databases

    def ensure(self, name: str, password: str | None) -> None:
        """Record the call and create both."""
        self.ensured.append((name, password))
        self.roles.add(name)
        self.databases.add(name)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Health checks and GitHub lookups are recorded, never made."""
    checked: list[str] = []
    monkeypatch.setattr(titan, "check_health", lambda url, **_: checked.append(url))
    monkeypatch.setattr(titan, "github_repo_exists", lambda repo: True)
    monkeypatch.setattr(titan, "blueprint_declares", lambda repo, name: False)
    monkeypatch.setattr(titan.time, "sleep", lambda _: None)
    return checked


def run(plan: Any, commit: bool) -> list[str]:
    """Execute a plan and return what it printed."""
    lines: list[str] = []
    titan.execute(plan, commit, out=lines.append)
    return lines


# ---------------------------------------------------------------- names


def test_names_derive_from_the_slug(app: Any) -> None:
    """Names derive from the slug."""
    assert app.name == "Tally"
    assert app.domain == "tally.ultraniche.ai"
    assert app.from_email == "Tally <tally@mail.ultraniche.ai>"
    assert app.repo == "hugorodgerbrown/tally"
    assert (app.web_service, app.cron_service) == ("tally", "tally-purge")


def test_hyphens_become_underscores_in_postgres(settings: Any) -> None:
    """Hyphens become underscores in postgres."""
    app = titan.App.from_slug("resort-planner", settings)
    assert app.db_name == "resort_planner"
    assert app.name == "Resort Planner"
    assert app.from_email == "Resort Planner <resort-planner@mail.ultraniche.ai>"


def test_display_name_with_a_comma_is_quoted(settings: Any) -> None:
    """Display name with a comma is quoted."""
    app = titan.App.from_slug("notes", settings, name="Hugo, Notes")
    assert app.from_email == '"Hugo, Notes" <notes@mail.ultraniche.ai>'


@pytest.mark.parametrize("slug", ["Tally", "1app", "my_app", "", "app.x"])
def test_bad_slugs_are_refused(settings: Any, slug: str) -> None:
    """Bad slugs are refused."""
    with pytest.raises(titan.TitanError):
        titan.App.from_slug(slug, settings)


def test_database_url_uses_the_internal_host_and_quotes_the_password(app: Any) -> None:
    """Database url uses the internal host and quotes the password."""
    assert app.database_url("a/b+c") == "postgresql://tally:a%2Fb%2Bc@dpg-abc123-a:5432/tally"


def test_internal_host_can_be_overridden(settings: Any) -> None:
    """Internal host can be overridden."""
    app = titan.App.from_slug(
        "tally", titan.Settings(**{**settings.__dict__, "db_internal_host": "db.internal"})
    )
    assert app.database_url("pw").startswith("postgresql://tally:pw@db.internal:5432/")


def test_blueprint_link_points_at_the_repo(app: Any) -> None:
    """Blueprint link points at the repo."""
    assert (
        app.blueprint_link()
        == "https://render.com/deploy?repo=https://github.com/hugorodgerbrown/tally"
    )


# ---------------------------------------------------------------- settings


def test_settings_come_from_the_file_and_the_environment_wins(tmp_path: Path) -> None:
    """Settings come from the file and the environment wins."""
    path = tmp_path / "env"
    path.write_text(
        "# titan\nRENDER_API_KEY=from-file\nRESEND_API_KEY='re_x'\nTITAN_DB_ADMIN_URL=postgresql://h/db\n"
    )
    loaded = titan.Settings.load(
        {"RENDER_API_KEY": "from-env", "TITAN_DOMAIN": "example.com"}, path
    )
    assert loaded.render_api_key == "from-env"
    assert loaded.resend_api_key == "re_x"
    assert loaded.domain == "example.com"
    assert loaded.mail_domain == "mail.ultraniche.ai"


def test_missing_settings_are_named(tmp_path: Path) -> None:
    """Missing settings are named."""
    with pytest.raises(titan.TitanError, match="RESEND_API_KEY, TITAN_DB_ADMIN_URL"):
        titan.Settings.load({"RENDER_API_KEY": "x"}, tmp_path / "absent")


# ---------------------------------------------------------------- new


def test_new_stops_at_the_blueprint_when_services_do_not_exist(
    app: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """New stops at the blueprint when services do not exist."""
    monkeypatch.setattr(titan, "github_repo_exists", lambda repo: False)
    plan = titan.plan_new(app, FakeRender(services=False), FakeResend(), FakeDb(), tmp_path, 60)
    out = "\n".join(run(plan, commit=False))
    assert "would: Generate tally from the template and push to hugorodgerbrown/tally" in out
    assert "render.com/deploy?repo=https://github.com/hugorodgerbrown/tally" in out
    assert "run `bin/titan new tally --commit` again" in out


def test_new_dry_run_changes_nothing(app: Any, tmp_path: Path, no_network: list[str]) -> None:
    """New dry run changes nothing."""
    render, resend, db = FakeRender(), FakeResend(), FakeDb()
    out = run(titan.plan_new(app, render, resend, db, tmp_path, 60), commit=False)
    assert (render.writes, resend.keys, db.ensured, no_network) == ([], [], [], [])
    assert any("would: Create role and database tally on shared-db" in line for line in out)
    assert out[-1] == "At go-live: `bin/titan golive tally` prints the CNAME to add in Squarespace."


def test_new_provisions_everything(app: Any, tmp_path: Path, no_network: list[str]) -> None:
    """New provisions everything."""
    render, resend, db = FakeRender(), FakeResend(), FakeDb()
    run(titan.plan_new(app, render, resend, db, tmp_path, 60), commit=True)

    ((name, password),) = db.ensured
    assert name == "tally"
    assert password
    assert resend.keys == [("tally", "dom-1")]
    web, cron = render.envs["srv-web"], render.envs["crn-cron"]
    assert web["DATABASE_URL"] == f"postgresql://tally:{password}@dpg-abc123-a:5432/tally"
    assert web["EMAIL_HOST_PASSWORD"] == "re_app_key"
    assert web["EMAIL_HOST"] == "smtp.resend.com"
    assert web["EMAIL_HOST_USER"] == "resend"
    assert web["DEFAULT_FROM_EMAIL"] == "Tally <tally@mail.ultraniche.ai>"
    assert cron == {"DATABASE_URL": web["DATABASE_URL"], "DJANGO_SECRET_KEY": "generated"}
    assert "EMAIL_HOST_PASSWORD" not in cron
    assert render.domains["srv-web"] == [
        {"name": "tally.ultraniche.ai", "verificationStatus": "unverified"}
    ]
    assert render.deploys == ["srv-web", "crn-cron"]  # env vars apply on the next deploy
    assert no_network == ["https://tally-s2nb.onrender.com"]
    assert "SITE_URL" not in web  # set at go-live, so the app works on onrender.com until then


def test_new_provisions_an_app_with_no_cron_job(
    app: Any, tmp_path: Path, no_network: list[str]
) -> None:
    """An app with no scheduled jobs leaves out <app>-purge: only the web service is set up."""
    render, db = FakeRender(), FakeDb()
    del render.services["tally-purge"]
    out = run(titan.plan_new(app, render, FakeResend(), db, tmp_path, 60), commit=True)

    assert any("Render services (tally; no tally-purge job)" in line for line in out)
    assert render.envs["srv-web"]["DATABASE_URL"]
    assert render.envs["crn-cron"] == {}
    assert all(service == "srv-web" for service, _, _ in render.writes)
    assert render.deploys == ["srv-web"]
    assert no_network == ["https://tally-s2nb.onrender.com"]


def test_new_stops_when_render_yaml_declares_a_missing_cron_job(
    app: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cron job render.yaml declares but Render lacks means an incomplete Blueprint."""
    monkeypatch.setattr(titan, "blueprint_declares", lambda repo, name: True)
    render = FakeRender()
    del render.services["tally-purge"]
    out = run(titan.plan_new(app, render, FakeResend(), FakeDb(), tmp_path, 60), commit=False)
    assert "run `bin/titan new tally --commit` again" in "\n".join(out)
    assert render.writes == []


def test_blueprint_declares_reads_render_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    """The service name must appear as a name: line; an unreadable file counts as declared."""
    yaml = "services:\n  - type: web\n    name: tally\n  - type: cron\n    name: tally-purge\n"
    result = subprocess.CompletedProcess([], 0, stdout=yaml)
    monkeypatch.setattr(titan.subprocess, "run", lambda *a, **k: result)
    assert BLUEPRINT_DECLARES("o/tally", "tally-purge")
    result.stdout = "services:\n  - type: web\n    name: tally\n"
    assert not BLUEPRINT_DECLARES("o/tally", "tally-purge")
    result.returncode = 1
    assert BLUEPRINT_DECLARES("o/tally", "tally-purge")


def test_new_is_idempotent(app: Any, tmp_path: Path) -> None:
    """New is idempotent."""
    render, resend, db = FakeRender(), FakeResend(), FakeDb()
    run(titan.plan_new(app, render, resend, db, tmp_path, 60), commit=True)
    writes, keys, ensured = len(render.writes), len(resend.keys), len(db.ensured)

    out = run(titan.plan_new(app, render, resend, db, tmp_path, 60), commit=True)
    assert (len(render.writes), len(resend.keys), len(db.ensured)) == (writes, keys, ensured)
    assert render.deploys == ["srv-web", "crn-cron"]  # no second deploys
    assert (
        sum("✓" in line for line in out) == len(out) - 3
    )  # all but deploy/health and the go-live note


def test_new_keeps_the_password_when_only_the_database_is_missing(app: Any, tmp_path: Path) -> None:
    """New keeps the password when only the database is missing."""
    render = FakeRender()
    render.envs["srv-web"]["DATABASE_URL"] = "postgresql://tally:old@dpg-abc123-a:5432/tally"
    db = FakeDb(roles={"tally"})
    run(titan.plan_new(app, render, FakeResend(), db, tmp_path, 60), commit=True)
    assert db.ensured == [("tally", None)]
    assert render.envs["srv-web"]["DATABASE_URL"].endswith(":old@dpg-abc123-a:5432/tally")


def test_new_rekeys_a_role_render_has_no_url_for(app: Any, tmp_path: Path) -> None:
    """New rekeys a role render has no url for."""
    db = FakeDb(roles={"tally"}, databases={"tally"})
    out = run(titan.plan_new(app, FakeRender(), FakeResend(), db, tmp_path, 60), commit=True)
    assert any("Re-key role and database tally" in line for line in out)
    assert db.ensured[0][1]


def test_new_refuses_when_the_admin_cannot_create_roles(app: Any, tmp_path: Path) -> None:
    """New refuses when the admin cannot create roles."""
    with pytest.raises(titan.TitanError, match="CREATEROLE"):
        titan.plan_new(app, FakeRender(), FakeResend(), FakeDb(allowed=False), tmp_path, 60)


def test_a_failed_deploy_is_an_error(app: Any, tmp_path: Path) -> None:
    """A failed deploy is an error."""
    render = FakeRender()
    render.deploy_status = lambda service_id, deploy_id: "build_failed"  # type: ignore[method-assign]
    with pytest.raises(titan.TitanError, match="ended build_failed"):
        run(titan.plan_new(app, render, FakeResend(), FakeDb(), tmp_path, 60), commit=True)


# ---------------------------------------------------------------- golive


def test_golive_dry_run_prints_the_cname(app: Any) -> None:
    """Golive dry run prints the cname."""
    render = FakeRender()
    out = run(titan.plan_golive(app, render, 60, 60), commit=False)
    assert "CNAME  tally  →  tally-s2nb.onrender.com" in out[0]
    assert render.writes == []


def test_golive_verifies_switches_and_checks(app: Any, no_network: list[str]) -> None:
    """Golive verifies switches and checks."""
    render = FakeRender()
    render.add_custom_domain("srv-web", "tally.ultraniche.ai")
    run(titan.plan_golive(app, render, 60, 60), commit=True)
    assert render.envs["srv-web"]["SITE_URL"] == "https://tally.ultraniche.ai"
    assert render.envs["srv-web"]["DJANGO_ALLOWED_HOSTS"] == "tally.ultraniche.ai"
    assert render.deploys == ["srv-web"]
    assert no_network == ["https://tally.ultraniche.ai"]


def test_golive_gives_up_when_dns_never_arrives(app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Golive gives up when dns never arrives."""
    render = FakeRender()
    render.verify_flips = False
    render.add_custom_domain("srv-web", "tally.ultraniche.ai")
    clock = iter(range(0, 10_000, 100))
    monkeypatch.setattr(titan.time, "monotonic", lambda: next(clock))
    with pytest.raises(titan.TitanError, match=r"has not verified tally\.ultraniche\.ai"):
        run(titan.plan_golive(app, render, 60, 60), commit=True)
    assert "SITE_URL" not in render.envs["srv-web"]


def test_golive_needs_the_service(app: Any) -> None:
    """Golive needs the service."""
    with pytest.raises(titan.TitanError, match="run `bin/titan new tally` first"):
        titan.plan_golive(app, FakeRender(services=False), 60, 60)


# ---------------------------------------------------------------- API clients


TALLY = {"type": "web_service", "repo": "https://github.com/hugorodgerbrown/tally"}


def test_render_unwraps_lists_and_pages_env_vars() -> None:
    """Render unwraps lists and pages env vars."""
    calls: list[str] = []

    def call(method: str, url: str, token: str, body: Any = None) -> Any:
        """Answer like the Render API."""
        calls.append(f"{method} {url}")
        if "/services?" in url:
            return [
                {"cursor": "c", "service": {"id": "srv-x", "name": "tally-purge", **TALLY}},
                {"cursor": "d", "service": {"id": "srv-y", "name": "tally", **TALLY}},
            ]
        if "cursor=c99" in url:
            return [{"cursor": "z", "envVar": {"key": "LAST", "value": "1"}}]
        return [{"cursor": f"c{i}", "envVar": {"key": f"K{i}", "value": "v"}} for i in range(100)]

    render = titan.Render("tok", call)
    found = render.service("tally", "https://github.com/hugorodgerbrown/tally", "web_service")
    assert found == {"id": "srv-y", "name": "tally", **TALLY}
    env = render.env("srv-y")
    assert len(env) == 101
    assert env["LAST"] == "1"


def test_render_sends_env_values_as_json() -> None:
    """Render sends env values as json."""
    sent: list[tuple[str, str, Any]] = []
    titan.Render("tok", lambda m, u, t, b=None: sent.append((m, u, b))).set_env(
        "srv-1", "SITE_URL", "https://x"
    )
    assert sent == [
        (
            "PUT",
            "https://api.render.com/v1/services/srv-1/env-vars/SITE_URL",
            {"value": "https://x"},
        )
    ]


def test_resend_makes_a_sending_only_key_for_one_domain() -> None:
    """Resend makes a sending only key for one domain."""
    sent: list[Any] = []

    def call(method: str, url: str, token: str, body: Any = None) -> Any:
        """Answer like the Render API."""
        if method == "GET":
            return {"data": [{"id": "dom-1", "name": "mail.ultraniche.ai", "status": "verified"}]}
        sent.append(body)
        return {"id": "key-1", "token": "re_new"}

    resend = titan.Resend("re_full", call)
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
    """Resend refuses a missing or unverified domain."""
    resend = titan.Resend("re_full", lambda *a, **k: {"data": domains})
    with pytest.raises(titan.TitanError, match=message):
        resend.domain_id("mail.ultraniche.ai")


def test_main_reports_errors_and_exits_non_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Main reports errors and exits non zero."""
    monkeypatch.setattr(titan, "CONFIG_FILE", Path("/nonexistent"))
    for key in ("RENDER_API_KEY", "RESEND_API_KEY", "TITAN_DB_ADMIN_URL"):
        monkeypatch.delenv(key, raising=False)
    assert titan.main(["new", "tally"]) == 1
    assert "Set RENDER_API_KEY" in capsys.readouterr().err


def test_render_refuses_a_same_named_service_from_another_repo() -> None:
    """A service called tally that Tally's repo did not make is never touched."""
    rows = [
        {
            "service": {
                "id": "srv-x",
                "name": "tally",
                "type": "web_service",
                "repo": "https://github.com/someone/else",
            }
        }
    ]
    render = titan.Render("tok", lambda *a, **k: rows)
    with pytest.raises(titan.TitanError, match="refusing to change it"):
        render.service("tally", "https://github.com/hugorodgerbrown/tally", "web_service")


def test_render_refuses_matches_in_two_workspaces() -> None:
    """Two matching services means the key sees two workspaces: stop, don't guess."""
    service = {
        "name": "tally",
        "type": "web_service",
        "repo": "https://github.com/hugorodgerbrown/tally.git",
    }
    rows = [
        {"service": {**service, "id": "a", "ownerId": "tea-1"}},
        {"service": {**service, "id": "b", "ownerId": "tea-2"}},
    ]
    render = titan.Render("tok", lambda *a, **k: rows)
    with pytest.raises(titan.TitanError, match="workspaces tea-1, tea-2"):
        render.service("tally", "https://github.com/hugorodgerbrown/tally", "web_service")


def test_render_matches_on_repo_and_type() -> None:
    """The web service and the cron job share a repo; the type tells them apart."""
    repo = "https://github.com/HugoRodgerBrown/tally/"
    rows = [
        {"service": {"id": "w", "name": "tally", "type": "web_service", "repo": repo}},
        {"service": {"id": "c", "name": "tally", "type": "cron_job", "repo": repo}},
    ]
    render = titan.Render("tok", lambda *a, **k: rows)
    found = render.service("tally", "https://github.com/hugorodgerbrown/tally", "cron_job")
    assert found is not None
    assert found["id"] == "c"


def test_generate_repo_resolves_a_relative_dir(
    app: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--dir . works: gh gets the same absolute path it runs in."""
    calls: list[tuple[tuple[str, ...], Path | None]] = []
    monkeypatch.setattr(titan, "run_cmd", lambda *args, cwd=None: calls.append((args, cwd)))
    monkeypatch.chdir(tmp_path)
    titan.generate_repo(app, Path("."))
    gh_args, gh_cwd = calls[-1]
    source = gh_args[gh_args.index("--source") + 1]
    assert Path(source).is_absolute()
    assert Path(source) == gh_cwd == tmp_path / "tally"
