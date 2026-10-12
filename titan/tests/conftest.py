"""Fakes for every account titan talks to: nothing in the tests leaves the process."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from titan.app import App
from titan.credentials import Settings
from titan.plans import Context
from titan.steps import Plan, Step

ADMIN_URL = "postgresql://shared_db_user:pw@dpg-abc123-a.frankfurt-postgres.render.com/shared_db"
REPO = "https://github.com/hugorodgerbrown/tally"


class FakeRender:
    """Render in memory: services, their env vars, env groups, domains and deploys."""

    def __init__(self, services: bool = True, cron: bool = True) -> None:
        """Start with the Blueprint's services (or none, until `deploy_blueprint`)."""
        self.services: dict[str, dict[str, Any]] = {}
        self.envs: dict[str, dict[str, str]] = {"srv-web": {}, "crn-cron": {}}
        self.groups: dict[str, dict[str, Any]] = {}
        self.domains: dict[str, list[dict[str, Any]]] = {"srv-web": []}
        self.deploys: list[str] = []
        self.statuses: dict[str, list[str]] = {}
        self.latest: dict[str, dict[str, Any]] = {}
        self.writes: list[tuple[str, str, str]] = []
        self.verify_flips = True
        self.cron = cron
        # Services appear after this many lookups (the person deploying the Blueprint).
        self.blueprint_after: int | None = None
        self.lookups = 0
        if services:
            self.deploy_blueprint()

    def deploy_blueprint(self) -> None:
        """What Render does with render.yaml: make the services and link the groups."""
        self.services["tally"] = {
            "id": "srv-web",
            "name": "tally",
            "type": "web_service",
            "repo": REPO,
            "serviceDetails": {"url": "https://tally-s2nb.onrender.com"},
        }
        if self.cron:
            self.services["tally-purge"] = {
                "id": "crn-cron",
                "name": "tally-purge",
                "type": "cron_job",
                "repo": REPO,
            }
        for group in self.groups.values():
            for service in self.services.values():
                group["serviceLinks"].append({"id": service["id"], "name": service["name"]})
        for service in self.services.values():
            self.latest[service["id"]] = {"id": "dep-blueprint", "status": "live"}

    # The client's interface ------------------------------------------------

    def workspaces(self) -> list[dict[str, Any]]:
        """One workspace."""
        return [{"id": "tea-1", "name": "Ultraniche"}]

    def service(self, name: str, repo: str, kind: str, owner_id: str = "") -> dict[str, Any] | None:
        """The service, once the Blueprint is deployed; always asked within the workspace."""
        assert repo == REPO
        assert owner_id == "tea-1"
        assert kind == ("cron_job" if name.endswith("-purge") else "web_service")
        self.lookups += 1
        if self.blueprint_after is not None and self.lookups > self.blueprint_after:
            self.blueprint_after = None
            self.deploy_blueprint()
        return self.services.get(name)

    def web_services(self, owner_id: str) -> list[dict[str, Any]]:
        """The web services."""
        return [s for s in self.services.values() if s["type"] == "web_service"]

    def env(self, service_id: str) -> dict[str, str]:
        """A copy of the service's own env vars."""
        return dict(self.envs[service_id])

    def set_env(self, service_id: str, key: str, value: str) -> None:
        """Store one service env var."""
        self.envs[service_id][key] = value
        self.writes.append((service_id, key, value))

    def env_group(self, name: str, owner_id: str) -> dict[str, Any] | None:
        """A deep-enough copy of the group."""
        assert owner_id == "tea-1"
        group = self.groups.get(name)
        if group is None:
            return None
        return {
            **group,
            "envVars": [dict(r) for r in group["envVars"]],
            "serviceLinks": list(group["serviceLinks"]),
        }

    def create_env_group(self, name: str, owner_id: str, env: dict[str, str]) -> dict[str, Any]:
        """Make a group."""
        assert name not in self.groups
        self.groups[name] = {
            "id": f"evg-{name}",
            "name": name,
            "envVars": [{"key": k, "value": v} for k, v in env.items()],
            "serviceLinks": [],
        }
        for key, value in env.items():
            self.writes.append((f"evg-{name}", key, value))
        return self.env_group(name, owner_id) or {}

    def group_values(self, name: str) -> dict[str, str]:
        """A group's values, for assertions."""
        return {r["key"]: r["value"] for r in self.groups[name]["envVars"]}

    def set_group_env(self, group_id: str, key: str, value: str) -> None:
        """Add or update a group key."""
        group = next(g for g in self.groups.values() if g["id"] == group_id)
        group["envVars"] = [r for r in group["envVars"] if r["key"] != key]
        group["envVars"].append({"key": key, "value": value})
        self.writes.append((group_id, key, value))

    def link_group(self, group_id: str, service_id: str) -> None:
        """Link a group to a service."""
        group = next(g for g in self.groups.values() if g["id"] == group_id)
        group["serviceLinks"].append({"id": service_id})
        self.writes.append((group_id, "link", service_id))

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
        return f"dep-{len(self.deploys)}"

    def deploy_status(self, service_id: str, deploy_id: str) -> str:
        """Each deploy goes through the queued statuses (default: straight to live)."""
        queue = self.statuses.get(service_id) or ["live"]
        return queue.pop(0) if len(queue) > 1 else queue[0]

    def latest_deploy(self, service_id: str) -> dict[str, Any] | None:
        """The Blueprint's deploy, if any."""
        return self.latest.get(service_id)


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


class FakeGitHub:
    """The repo exists unless told otherwise; render.yaml declares the cron job."""

    def __init__(self, exists: bool = True, declares_cron: bool = True) -> None:
        """Record generations."""
        self.exists = exists
        self.declares_cron = declares_cron
        self.generated: list[dict[str, str]] = []

    def repo_exists(self, repo: str) -> bool:
        """Whether the repo exists."""
        return self.exists

    def blueprint_declares(self, repo: str, name: str) -> bool:
        """Whether render.yaml declares the service."""
        return self.declares_cron

    def generate(self, answers: dict[str, str], repo: str, workdir: Path) -> Path:
        """Record the answers; the repo now exists."""
        self.generated.append(answers)
        self.exists = True
        return workdir / answers["project_slug"]


class RecordingView:
    """A View that keeps every redraw."""

    def __init__(self) -> None:
        """Nothing drawn yet."""
        self.frames: list[list[tuple[str, str, str]]] = []
        self.opened: list[str] = []

    def show(self, plan: Plan, commit: bool) -> None:
        """Keep (state, title, note) per step."""
        self.frames.append([(s.state.value, s.title, s.note) for s in plan.steps])

    def started(self, step: Step) -> None:
        """Record links that would open."""
        if step.link:
            self.opened.append(step.link)

    @property
    def last(self) -> list[tuple[str, str, str]]:
        """The final checklist."""
        return self.frames[-1]

    def titles(self, state: str) -> list[str]:
        """Titles of the final checklist's steps in one state."""
        return [title for s, title, _ in self.last if s == state]


@pytest.fixture
def settings() -> Settings:
    """Settings with fake credentials and the real defaults."""
    return Settings(render_api_key="rnd", resend_api_key="re_full", db_admin_url=ADMIN_URL)


@pytest.fixture
def app(settings: Settings) -> App:
    """The worked example: Tally."""
    return App.from_slug("tally", settings)


@pytest.fixture
def checked(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Health checks are recorded and answer 200; nothing is fetched."""
    urls: list[str] = []

    def fake_health(url: str) -> str:
        urls.append(url)
        return "200"

    monkeypatch.setattr("titan.plans.health", fake_health)
    return urls


@pytest.fixture
def make_ctx(app: App, tmp_path: Path, checked: list[str]) -> Any:
    """Build a Context over fakes; no sleeping, and a clock that moves 10s per read."""

    def build(
        render: FakeRender | None = None,
        db: FakeDb | None = None,
        github: FakeGitHub | None = None,
        resend: FakeResend | None = None,
    ) -> Context:
        ticks = iter(range(0, 1_000_000, 10))
        return Context(
            app=app,
            render=render or FakeRender(),  # type: ignore[arg-type]
            resend=resend or FakeResend(),  # type: ignore[arg-type]
            db=db or FakeDb(),  # type: ignore[arg-type]
            github=github or FakeGitHub(),  # type: ignore[arg-type]
            owner_id="tea-1",
            workdir=tmp_path,
            sleep=lambda _: None,
            clock=lambda: float(next(ticks)),
        )

    return build
