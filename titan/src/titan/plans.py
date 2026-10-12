"""What `new` and `golive` still have to do for an app, read from the accounts.

`new`, in order: the GitHub repo; the shared ``titan`` env group; the
app's role and database on shared-db; its sending-only Resend key; the
rest of its own ``<slug>`` group. All of that exists before the Blueprint
is deployed, so the Blueprint's first deploy has every setting it needs.
Then it waits for the Blueprint, links the groups if Render did not, adds
the custom domain, deploys whatever changed and checks /healthz.

`golive` waits for Render to verify the domain (after the CNAME is added
by hand), sets SITE_URL, deploys and checks /healthz on the real address.

Every step is safe to re-run: each one reads what exists and only does
what is missing.
"""

from __future__ import annotations

import secrets
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from titan import TitanError
from titan.app import APP_KEYS, COMMON_GROUP, App, common_env
from titan.providers import DEPLOY_DONE, GitHub, Render, Resend, SharedDb, health
from titan.steps import Plan, Progress


@dataclass
class Context:
    """The app, its accounts, and what this run has learnt or changed."""

    app: App
    render: Render
    resend: Resend
    db: SharedDb
    github: GitHub
    owner_id: str
    workdir: Path = field(default_factory=Path.cwd)
    answers: dict[str, str] = field(default_factory=dict)
    deploy_timeout: float = 900
    blueprint_timeout: float = 1800
    verify_timeout: float = 600
    health_timeout: float = 120
    poll: float = 10
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    # Read once per plan, kept current by the steps that write them.
    web: dict[str, Any] | None = None
    cron: dict[str, Any] | None = None
    web_env: dict[str, str] = field(default_factory=dict)
    cron_env: dict[str, str] = field(default_factory=dict)
    group: dict[str, Any] | None = None
    # Something a running service reads changed: deploy it.
    dirty: bool = False

    def read_services(self) -> None:
        """Find the app's services and their own env vars (None before the Blueprint)."""
        app = self.app
        self.web = self.render.service(app.web_service, app.repo_url, "web_service", self.owner_id)
        self.cron = self.render.service(app.cron_service, app.repo_url, "cron_job", self.owner_id)
        self.web_env = self.render.env(self.web["id"]) if self.web else {}
        self.cron_env = self.render.env(self.cron["id"]) if self.cron else {}

    @property
    def services(self) -> list[dict[str, Any]]:
        """The services that exist."""
        return [s for s in (self.web, self.cron) if s]

    @property
    def group_env(self) -> dict[str, str]:
        """The app group's values."""
        rows = (self.group or {}).get("envVars", [])
        return {r["key"]: r.get("value") or "" for r in rows}

    def value(self, key: str) -> str:
        """What the web service sees for one of the app's keys.

        A service's own env var wins over its groups' (apps made before the
        groups keep theirs there), so it is read first.
        """
        return self.web_env.get(key) or self.group_env.get(key, "")

    def set_value(self, key: str, value: str) -> None:
        """Write one of the app's keys to its group, and wherever a service shadows it."""
        self.write_group(key, value)
        for service, env in ((self.web, self.web_env), (self.cron, self.cron_env)):
            if service and key in env and env[key] != value:
                self.render.set_env(service["id"], key, value)
                env[key] = value
        if self.services:
            self.dirty = True

    def write_group(self, key: str, value: str) -> None:
        """Write one of the app's keys to its group only, creating the group if need be."""
        if key not in APP_KEYS:
            raise TitanError(f"{key} is not one of the app group's keys.")
        if self.group is None:
            self.group = self.render.create_env_group(self.app.group, self.owner_id, {key: value})
            self.group.setdefault("envVars", [{"key": key, "value": value}])
        else:
            self.render.set_group_env(self.group["id"], key, value)
            rows = [r for r in self.group.get("envVars", []) if r["key"] != key]
            self.group["envVars"] = [*rows, {"key": key, "value": value}]

    def wait(self, timeout: float, what: str, check: Callable[[float], bool]) -> None:
        """Call check(elapsed) every poll seconds until it is true; TitanError on timeout."""
        start = self.clock()
        while not check(self.clock() - start):
            if self.clock() - start > timeout:
                raise TitanError(f"Gave up waiting for {what} after {int(timeout)}s.")
            self.sleep(self.poll)


def elapsed(seconds: float) -> str:
    """1m12s."""
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}m{secs:02d}s" if minutes else f"{secs}s"


def service_url(service: dict[str, Any] | None) -> str:
    """The service's onrender.com address."""
    return str((service or {}).get("serviceDetails", {}).get("url", ""))


# ---------------------------------------------------------------- new


def plan_new(ctx: Context) -> Plan:
    """Read every account and work out what `new` still has to do."""
    app, render = ctx.app, ctx.render
    plan = Plan()

    if ctx.github.repo_exists(app.repo):
        plan.add(f"GitHub repo {app.repo}")
    else:
        answers = {"project_name": app.name, "project_slug": app.slug, **ctx.answers}
        plan.add(
            f"Generate {app.slug} from the template and push to {app.repo}",
            f"into {ctx.workdir / app.slug}",
            run=lambda _: ctx.github.generate(answers, app.repo, ctx.workdir),
        )

    ctx.read_services()
    ctx.group = render.env_group(app.group, ctx.owner_id)
    _common_group(ctx, plan)
    _adopt_service_values(ctx, plan)
    _database(ctx, plan)
    _mail_key(ctx, plan)
    _app_values(ctx, plan)

    cron_missing = ctx.cron is None and ctx.github.blueprint_declares(app.repo, app.cron_service)
    if ctx.web is None or cron_missing:

        def wait_for_blueprint(progress: Progress) -> None:
            def check(seconds: float) -> bool:
                progress(f"waiting for you to deploy it · {elapsed(seconds)}")
                ctx.read_services()
                return ctx.web is not None and (ctx.cron is not None or not cron_missing)

            ctx.wait(ctx.blueprint_timeout, "the Blueprint's services", check)

        plan.add(
            "Deploy the Blueprint in Render",
            "one click: open the link, pick the workspace, Deploy Blueprint",
            run=wait_for_blueprint,
            link=app.blueprint_link(),
        )
        plan.then = lambda: _after_blueprint(ctx)
        plan.later = "Then: link the env groups, add the domain, deploy and check /healthz"
    else:
        plan.steps += _after_blueprint(ctx).steps
    plan.finish = f"At go-live: `titan golive {app.slug}` gives the CNAME to add in Squarespace."
    return plan


def _common_group(ctx: Context, plan: Plan) -> None:
    """The shared group: create it, or add the keys it lacks. Changed values stay."""
    wanted = common_env(ctx.app.settings)
    group = ctx.render.env_group(COMMON_GROUP, ctx.owner_id)
    if group is None:
        plan.add(
            f"Create the shared env group {COMMON_GROUP!r}",
            ", ".join(wanted),
            run=lambda _: ctx.render.create_env_group(COMMON_GROUP, ctx.owner_id, wanted),
        )
        return
    have = {r["key"]: r.get("value") or "" for r in group.get("envVars", [])}
    missing = {k: v for k, v in wanted.items() if k not in have}
    changed = sorted(k for k, v in wanted.items() if k in have and have[k] != v)
    note = f"kept as changed in Render: {', '.join(changed)}" if changed else ""
    if not missing:
        plan.add(f"Shared env group {COMMON_GROUP!r}", note)
        return

    def add_missing(_: Progress) -> None:
        for key, value in missing.items():
            ctx.render.set_group_env(group["id"], key, value)
        if ctx.services:
            ctx.dirty = True

    plan.add(
        f"Add {', '.join(missing)} to the shared env group {COMMON_GROUP!r}",
        note,
        run=add_missing,
    )


def _adopt_service_values(ctx: Context, plan: Plan) -> None:
    """Copy an older app's values from its web service into its group.

    Apps made before the groups keep DATABASE_URL and the rest on the
    service. The service's copy stays (it wins, so nothing changes for the
    running app) but the group becomes complete, so the service's own
    copies can later be deleted without losing anything.
    """
    adopt = {
        k: ctx.web_env[k]
        for k in APP_KEYS
        if ctx.web_env.get(k) and ctx.group_env.get(k) != ctx.web_env[k]
    }
    if not adopt:
        return

    def copy(_: Progress) -> None:
        for key, value in adopt.items():
            ctx.write_group(key, value)

    plan.add(
        f"Copy {', '.join(adopt)} from the {ctx.app.web_service} service into the "
        f"app's env group {ctx.app.group!r}",
        "the service keeps its own copy, which wins until you delete it",
        run=copy,
    )


def _database(ctx: Context, plan: Plan) -> None:
    """The app's role and database, and DATABASE_URL in its group."""
    app, db = ctx.app, ctx.db
    if not db.can_provision():
        raise TitanError(
            "shared-db's admin user cannot create roles and databases"
            " (needs CREATEROLE and CREATEDB)."
        )
    role_exists = db.role_exists(app.db_name)
    has_url = bool(ctx.value("DATABASE_URL"))
    # The URL on Render holds the only copy of the password: keep it while the
    # role it belongs to exists, otherwise make (or re-key to) a new one.
    keep_password = has_url and role_exists
    if keep_password and db.database_exists(app.db_name):
        plan.add(f"Role and database {app.db_name} on shared-db")
        return
    verb = "Re-key" if role_exists and not has_url else "Create"

    def make_db(_: Progress) -> None:
        password = None if keep_password else secrets.token_urlsafe(32)
        db.ensure(app.db_name, password)
        if password:
            ctx.set_value("DATABASE_URL", app.database_url(password))

    plan.add(
        f"{verb} role and database {app.db_name} on shared-db",
        "others cannot connect; its URL goes in the app's env group",
        run=make_db,
    )


def _mail_key(ctx: Context, plan: Plan) -> None:
    """A sending-only Resend key for the shared mail domain."""
    app = ctx.app
    if ctx.value("EMAIL_HOST_PASSWORD"):
        plan.add(f"Resend key for {app.slug}")
        return

    def make_key(_: Progress) -> None:
        key = ctx.resend.create_sending_key(
            app.slug, ctx.resend.domain_id(app.settings.mail_domain)
        )
        ctx.set_value("EMAIL_HOST_PASSWORD", key)

    plan.add(
        f"Create a sending-only Resend key {app.slug!r}",
        f"for {app.settings.mail_domain}",
        run=make_key,
    )


def _app_values(ctx: Context, plan: Plan) -> None:
    """The secret key and sender, unless the app already has them."""
    wanted: dict[str, Callable[[], str]] = {}
    if not ctx.value("DJANGO_SECRET_KEY"):
        wanted["DJANGO_SECRET_KEY"] = lambda: secrets.token_urlsafe(50)
    if not ctx.value("DEFAULT_FROM_EMAIL"):
        wanted["DEFAULT_FROM_EMAIL"] = lambda: ctx.app.from_email
    title = f"App env group {ctx.app.group!r}"
    # Keys that belong in the shared group (or on the service) make it
    # ambiguous which value wins; say so rather than delete anything.
    strays = sorted(set(ctx.group_env) - set(APP_KEYS))
    note = f"also holds {', '.join(strays)}: move or delete them in Render" if strays else ""
    if not wanted:
        plan.add(title, note or f"from {ctx.value('DEFAULT_FROM_EMAIL')}")
        return

    def write(_: Progress) -> None:
        for key, make in wanted.items():
            ctx.set_value(key, make())

    plan.add(f"{title}: set {', '.join(wanted)}", note, run=write)


def _after_blueprint(ctx: Context) -> Plan:
    """Once the services exist: link the groups, add the domain, deploy, check."""
    app, render = ctx.app, ctx.render
    plan = Plan()
    if ctx.web is None:
        ctx.read_services()
    if ctx.web is None:
        raise TitanError(f"No Render service {app.web_service!r} yet; deploy the Blueprint.")

    plan.add(
        "Render services",
        f"{app.web_service}, {app.cron_service}"
        if ctx.cron
        else f"{app.web_service}; no {app.cron_service} job",
    )

    groups = [render.env_group(name, ctx.owner_id) for name in (COMMON_GROUP, app.group)]
    unlinked = [
        (group, service)
        for group in groups
        if group
        for service in ctx.services
        if service["id"] not in {link.get("id") for link in group.get("serviceLinks", [])}
    ]
    if unlinked:

        def link(_: Progress) -> None:
            for group, service in unlinked:
                render.link_group(group["id"], service["id"])
            ctx.dirty = True

        names = sorted({f"{g['name']} → {s['name']}" for g, s in unlinked})
        plan.add("Link the env groups", ", ".join(names), run=link)
    else:
        plan.add("Env groups linked", f"{COMMON_GROUP}, {app.group}")

    domains = {d.get("name") for d in render.custom_domains(ctx.web["id"])}
    if app.domain in domains:
        plan.add(f"Custom domain {app.domain}", "verified at go-live")
    else:
        web_id = ctx.web["id"]
        plan.add(
            f"Add custom domain {app.domain}",
            "verified at go-live",
            run=lambda _: render.add_custom_domain(web_id, app.domain),
        )

    url = service_url(ctx.web)
    plan.add("Deploy what changed, then check /healthz", url, run=lambda p: _deploy(ctx, url, p))
    return plan


def _deploy(ctx: Context, url: str, progress: Progress) -> None:
    """Let any deploy in flight finish; deploy again if it failed or settings changed."""
    for service in ctx.services:
        latest = ctx.render.latest_deploy(service["id"])
        if latest and latest.get("status") not in DEPLOY_DONE:
            status = _wait_for_deploy(ctx, service, str(latest["id"]), progress)
        else:
            status = str((latest or {}).get("status", ""))
        if ctx.dirty or status != "live":
            deploy_id = ctx.render.deploy(service["id"])
            status = _wait_for_deploy(ctx, service, deploy_id, progress)
            if status != "live":
                raise TitanError(
                    f"{service['name']}'s deploy {deploy_id} ended {status}; "
                    "see its Events and Logs in Render."
                )
    ctx.dirty = False
    check_health(ctx, url, progress)


def _wait_for_deploy(
    ctx: Context, service: dict[str, Any], deploy_id: str, progress: Progress
) -> str:
    """Block until the deploy ends; returns its final status."""
    status = "created"

    def check(seconds: float) -> bool:
        nonlocal status
        status = ctx.render.deploy_status(service["id"], deploy_id)
        progress(f"{service['name']}: {status.replace('_', ' ')} · {elapsed(seconds)}")
        return status in DEPLOY_DONE

    ctx.wait(ctx.deploy_timeout, f"{service['name']}'s deploy", check)
    return status


def check_health(ctx: Context, url: str, progress: Progress) -> None:
    """GET <url>/healthz until it answers 200 (it also reads the database)."""
    last = ""

    def check(seconds: float) -> bool:
        nonlocal last
        last = health(url)
        progress(f"{url}/healthz: {last} · {elapsed(seconds)}")
        return last == "200"

    try:
        ctx.wait(ctx.health_timeout, f"{url}/healthz", check)
    except TitanError:
        raise TitanError(f"{url}/healthz did not answer 200 (last: {last}).") from None


# ---------------------------------------------------------------- golive


def plan_golive(ctx: Context) -> Plan:
    """Work out what `golive` still has to do."""
    app, render = ctx.app, ctx.render
    ctx.read_services()
    ctx.group = render.env_group(app.group, ctx.owner_id)
    web = ctx.web
    if web is None:
        raise TitanError(
            f"No Render service {app.web_service!r}; run `titan new {app.slug}` first."
        )
    target = urllib.parse.urlsplit(service_url(web)).hostname or f"{app.slug}.onrender.com"
    label = app.domain.removesuffix("." + app.settings.domain)
    plan = Plan()
    plan.add(
        f"In Squarespace (DNS for {app.settings.domain}): CNAME  {label}  →  {target}", "by hand"
    )

    domain = next(
        (d for d in render.custom_domains(web["id"]) if d.get("name") == app.domain), None
    )
    if domain is None:
        plan.add(
            f"Add custom domain {app.domain}",
            run=lambda _: render.add_custom_domain(web["id"], app.domain),
        )
    if domain is not None and domain.get("verificationStatus") == "verified":
        plan.add(f"{app.domain} verified by Render")
    else:

        def verify(progress: Progress) -> None:
            def check(seconds: float) -> bool:
                progress(f"waiting for DNS to reach Render · {elapsed(seconds)}")
                render.verify_custom_domain(web["id"], app.domain)
                current = next(
                    (d for d in render.custom_domains(web["id"]) if d.get("name") == app.domain),
                    {},
                )
                return current.get("verificationStatus") == "verified"

            try:
                ctx.wait(ctx.verify_timeout, f"{app.domain}", check)
            except TitanError:
                raise TitanError(
                    f"Render has not verified {app.domain} yet. Check the CNAME, then re-run; "
                    "DNS can take a few minutes to reach Render."
                ) from None

        plan.add(
            f"Wait for Render to verify {app.domain}",
            f"up to {int(ctx.verify_timeout)}s",
            run=verify,
        )

    site_url = f"https://{app.domain}"
    pending: dict[str, str] = {}
    if ctx.value("SITE_URL") != site_url:
        pending["SITE_URL"] = site_url
    # An app made before the shared group may pin its hosts on the service.
    own_hosts = ctx.web_env.get("DJANGO_ALLOWED_HOSTS")
    extra_hosts = own_hosts is not None and app.domain not in own_hosts.split(",")

    def switch(progress: Progress) -> None:
        for key, value in pending.items():
            ctx.set_value(key, value)
        if extra_hosts:
            render.set_env(web["id"], "DJANGO_ALLOWED_HOSTS", f"{own_hosts},{app.domain}")
            ctx.dirty = True
        ctx.dirty = ctx.dirty or bool(pending)
        _deploy(ctx, site_url, progress)

    changes = [*pending, *(["DJANGO_ALLOWED_HOSTS"] if extra_hosts else [])]
    title = f"Set {', '.join(changes)}, deploy, " if changes else ""
    plan.add(f"{title}check {site_url}/healthz", run=switch)
    plan.finish = f"{app.name} is live at {site_url}."
    return plan
