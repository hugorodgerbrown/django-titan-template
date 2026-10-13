"""Tests for titan.plans: what `new`, `deploy` and `golive` do, over fake accounts."""

from __future__ import annotations

from typing import Any

import pytest
from conftest import FakeDb, FakeFivebar, FakeGitHub, FakeRender, RecordingView

from titan import TitanError
from titan.plans import plan_deploy, plan_golive, plan_new
from titan.steps import Plan, execute

SHARED = {
    "DJANGO_DEBUG": "0",
    "PYTHON_VERSION": "3.14",
    "DJANGO_ALLOWED_HOSTS": ".ultraniche.ai",
    "DJANGO_CSRF_TRUSTED_ORIGINS": "https://*.ultraniche.ai",
    "EMAIL_HOST": "smtp.resend.com",
    "EMAIL_PORT": "587",
    "EMAIL_HOST_USER": "resend",
    "EMAIL_USE_TLS": "True",
}


def run(plan: Plan, commit: bool = True) -> RecordingView:
    """Execute a plan against a recording view."""
    view = RecordingView()
    execute(plan, view, commit)
    return view


TALLY_NEW = (
    '{"apps": [{"slug": "tally", "name": "Tally", "repo": "hugorodgerbrown/tally",'
    ' "domain": "tally.ultraniche.ai", "stage": "new", "updates": true}]}'
)


# ---------------------------------------------------------------- new: the repo only


def test_new_generates_and_pushes_without_touching_render(make_ctx: Any, tmp_path: Any) -> None:
    """A new app is a repo on GitHub; Render, shared-db and Resend are never asked."""
    render, db, github = FakeRender(services=False), FakeDb(), FakeGitHub(exists=False)
    plan = plan_new(make_ctx(render=render, db=db, github=github))
    view = run(plan)
    assert github.generated == [{"project_name": "Tally", "project_slug": "tally"}]
    assert github.published == [("hugorodgerbrown/tally", tmp_path / "tally")]
    assert (render.lookups, render.writes, db.ensured) == (0, [], [])
    assert view.titles("todo") == []
    assert "titan deploy tally" in plan.finish


def test_new_on_an_existing_repo_does_nothing(make_ctx: Any) -> None:
    """The repo is there and registered: nothing to generate, and the next step is deploy."""
    github = FakeGitHub(register=TALLY_NEW)
    plan = plan_new(make_ctx(github=github))
    assert plan.changes == 0
    assert github.generated == []
    assert "titan deploy tally" in plan.finish


def test_new_records_the_app_in_the_register(make_ctx: Any) -> None:
    """A new app is added to the register at stage new, with copier updates on."""
    github = FakeGitHub(exists=False)
    run(plan_new(make_ctx(github=github)))
    assert github.register() == [
        {
            "slug": "tally",
            "name": "Tally",
            "repo": "hugorodgerbrown/tally",
            "domain": "tally.ultraniche.ai",
            "stage": "new",
            "updates": True,
        }
    ]
    assert github.commits == ["Add tally in the register of Titan apps (new)"]


def test_new_on_an_existing_repo_registers_an_app_made_before_the_register(
    make_ctx: Any,
) -> None:
    """An older app's repo is left alone; it only gains its register entry."""
    github = FakeGitHub()
    plan = plan_new(make_ctx(github=github))
    assert plan.changes == 1
    run(plan)
    assert github.generated == []
    assert [e["slug"] for e in github.register()] == ["tally"]


def test_deploy_needs_the_repo_on_github(make_ctx: Any) -> None:
    """Render builds from GitHub, so deploy refuses an app that is not there yet."""
    with pytest.raises(TitanError, match="titan new tally"):
        plan_deploy(make_ctx(github=FakeGitHub(exists=False)))


# ---------------------------------------------------------------- deploy: a fresh app


def test_deploy_fills_both_groups_before_the_blueprint(make_ctx: Any, checked: list[str]) -> None:
    """Everything the first deploy needs exists before the services do."""
    render = FakeRender(services=False)
    render.blueprint_after = 2  # the person clicks Deploy Blueprint while titan waits
    db = FakeDb()
    ctx = make_ctx(render=render, db=db)
    view = run(plan_deploy(ctx))

    assert render.group_values("titan") == SHARED
    ((name, password),) = db.ensured
    assert name == "tally"
    app_group = render.group_values("tally")
    assert app_group == {
        "DATABASE_URL": f"postgresql://tally:{password}@dpg-abc123-a:5432/tally",
        "EMAIL_HOST_PASSWORD": "re_app_key",
        "DJANGO_SECRET_KEY": app_group["DJANGO_SECRET_KEY"],
        "DEFAULT_FROM_EMAIL": "Tally <tally@mail.ultraniche.ai>",
    }
    assert len(app_group["DJANGO_SECRET_KEY"]) > 50
    # The Blueprint linked the groups and its first deploy went live: no redeploy.
    assert render.deploys == []
    assert view.opened == [ctx.app.blueprint_link()]
    assert checked == ["https://tally-s2nb.onrender.com"]
    assert render.domains["srv-web"] == [
        {"name": "tally.ultraniche.ai", "verificationStatus": "unverified"}
    ]
    assert view.titles("failed") == []
    assert view.titles("todo") == []
    assert "Env groups linked" in view.titles("done")
    assert render.envs == {"srv-web": {}, "crn-cron": {}}  # nothing on the services themselves


def test_deploy_shows_the_wait_while_the_blueprint_is_deployed(make_ctx: Any) -> None:
    """The waiting step redraws with how long it has waited."""
    render = FakeRender(services=False)
    render.blueprint_after = 4
    view = run(plan_deploy(make_ctx(render=render)))
    notes = [
        note
        for frame in view.frames
        for state, title, note in frame
        if title == "Deploy the Blueprint in Render" and state == "running" and note
    ]
    assert notes[0].startswith("waiting for you to deploy it")
    assert len(notes) >= 2


def test_deploy_dry_run_changes_nothing(make_ctx: Any, checked: list[str]) -> None:
    """A plan run reads but writes nothing, and says what comes after the Blueprint."""
    render = FakeRender(services=False)
    db = FakeDb()
    github = FakeGitHub()
    plan = plan_deploy(make_ctx(render=render, db=db, github=github))
    run(plan, commit=False)
    assert (render.writes, db.ensured, github.generated, checked) == ([], [], [], [])
    assert plan.then is not None
    assert "link the env groups" in plan.later
    assert [s.title for s in plan.steps if s.run] == [
        "Create the shared env group 'titan'",
        "Create role and database tally on shared-db",
        "Create a sending-only Resend key 'tally'",
        "App env group 'tally': set DJANGO_SECRET_KEY, DEFAULT_FROM_EMAIL",
        "Deploy the Blueprint in Render",
    ]


def test_deploy_links_groups_the_blueprint_did_not(make_ctx: Any) -> None:
    """A render.yaml without fromGroup still ends linked, then redeployed."""
    render = FakeRender(services=False)
    ctx = make_ctx(render=render)
    plan = plan_deploy(ctx)
    # The person deploys a Blueprint that references no groups.
    original = render.deploy_blueprint

    def blueprint_without_groups() -> None:
        groups, render.groups = render.groups, {}
        original()
        render.groups = groups

    render.deploy_blueprint = blueprint_without_groups  # type: ignore[method-assign]
    render.blueprint_after = 1
    run(plan)
    assert {link["id"] for link in render.groups["titan"]["serviceLinks"]} == {
        "srv-web",
        "crn-cron",
    }
    assert {link["id"] for link in render.groups["tally"]["serviceLinks"]} == {
        "srv-web",
        "crn-cron",
    }
    assert render.deploys == ["srv-web", "crn-cron"]


def test_deploy_redeploys_when_the_blueprint_deploy_failed(make_ctx: Any) -> None:
    """A failed first deploy (an app from the old render.yaml) is deployed again."""
    render = FakeRender(services=False)
    render.blueprint_after = 2  # after planning's two lookups
    original = render.deploy_blueprint

    def failing_blueprint() -> None:
        original()
        render.latest["srv-web"] = {"id": "dep-bp", "status": "build_failed"}

    render.deploy_blueprint = failing_blueprint  # type: ignore[method-assign]
    run(plan_deploy(make_ctx(render=render)))
    assert render.deploys == ["srv-web"]


def test_deploy_waits_for_a_deploy_in_flight(make_ctx: Any) -> None:
    """A deploy still building is waited for, not started again."""
    render, db = FakeRender(services=False), FakeDb()
    render.blueprint_after = 2
    run(plan_deploy(make_ctx(render=render, db=db)))
    render.latest["srv-web"] = {"id": "dep-push", "status": "build_in_progress"}
    render.statuses["srv-web"] = ["build_in_progress", "update_in_progress", "live"]
    view = run(plan_deploy(make_ctx(render=render, db=db)))
    assert render.deploys == []
    notes = [note for frame in view.frames for _, _, note in frame if note.startswith("tally:")]
    assert notes[0].startswith("tally: build in progress")


# ---------------------------------------------------------------- new: re-runs


def test_deploy_is_idempotent(make_ctx: Any) -> None:
    """A second run finds everything done and changes nothing but the health check."""
    render, db = FakeRender(services=False), FakeDb()
    render.blueprint_after = 2
    run(plan_deploy(make_ctx(render=render, db=db)))
    writes, ensured = list(render.writes), list(db.ensured)

    plan = plan_deploy(make_ctx(render=render, db=db))
    assert plan.changes == 0
    assert plan.steps[-1].title == "Latest deploy is live"
    run(plan)
    assert (render.writes, db.ensured, render.deploys) == (writes, ensured, [])


def test_deploy_keeps_the_password_when_only_the_database_is_missing(make_ctx: Any) -> None:
    """The URL holds the only copy of the password: keep it while its role exists."""
    render = FakeRender()
    render.envs["srv-web"]["DATABASE_URL"] = "postgresql://tally:old@dpg-abc123-a:5432/tally"
    db = FakeDb(roles={"tally"})
    run(plan_deploy(make_ctx(render=render, db=db)))
    assert db.ensured == [("tally", None)]
    assert render.envs["srv-web"]["DATABASE_URL"].endswith(":old@dpg-abc123-a:5432/tally")


def test_deploy_rekeys_a_role_render_has_no_url_for(make_ctx: Any) -> None:
    """A role with no URL anywhere gets a new password."""
    db = FakeDb(roles={"tally"}, databases={"tally"})
    view = run(plan_deploy(make_ctx(db=db)))
    assert "Re-key role and database tally on shared-db" in view.titles("done")
    assert db.ensured[0][1]


def test_a_value_on_the_service_is_updated_with_the_group(make_ctx: Any) -> None:
    """An older app keeps DATABASE_URL on the service, which wins: both are rewritten."""
    render = FakeRender()
    render.envs["srv-web"]["DATABASE_URL"] = "postgresql://tally:lost@dpg-abc123-a:5432/tally"
    db = FakeDb(roles=set())  # the role is gone, so the password is new
    run(plan_deploy(make_ctx(render=render, db=db)))
    new_url = render.group_values("tally")["DATABASE_URL"]
    assert ":lost@" not in new_url
    assert render.envs["srv-web"]["DATABASE_URL"] == new_url
    assert render.deploys == ["srv-web", "crn-cron"]


def test_the_shared_group_keeps_values_changed_in_render(make_ctx: Any) -> None:
    """Missing shared keys are added; one changed in the dashboard is left and reported."""
    render = FakeRender()
    render.create_env_group("titan", "tea-1", {**SHARED, "EMAIL_PORT": "2587"})
    render.set_group_env("evg-titan", "EMAIL_USE_TLS", "True")
    render.groups["titan"]["envVars"] = [
        r for r in render.groups["titan"]["envVars"] if r["key"] != "PYTHON_VERSION"
    ]
    plan = plan_deploy(make_ctx(render=render))
    step = next(s for s in plan.steps if "shared env group" in s.title)
    assert step.title == "Add PYTHON_VERSION to the shared env group 'titan'"
    assert step.detail == "kept as changed in Render: EMAIL_PORT"
    run(plan)
    assert render.group_values("titan")["EMAIL_PORT"] == "2587"
    assert render.group_values("titan")["PYTHON_VERSION"] == "3.14"


def test_deploy_provisions_an_app_with_no_cron_job(make_ctx: Any) -> None:
    """An app whose render.yaml has no <app>-purge job sets up the web service only."""
    render = FakeRender(services=False, cron=False)
    render.blueprint_after = 1
    view = run(plan_deploy(make_ctx(render=render, github=FakeGitHub(declares_cron=False))))
    assert "Render services" in view.titles("done")
    assert all(link["id"] == "srv-web" for link in render.groups["tally"]["serviceLinks"])


def test_deploy_waits_for_a_declared_cron_job(make_ctx: Any) -> None:
    """A cron job render.yaml declares but Render lacks means the Blueprint isn't done."""
    render = FakeRender(cron=False)
    plan = plan_deploy(make_ctx(render=render, github=FakeGitHub(declares_cron=True)))
    assert any(s.title == "Deploy the Blueprint in Render" for s in plan.steps)


def test_deploy_gives_up_waiting_for_the_blueprint(make_ctx: Any) -> None:
    """Nobody deploys the Blueprint: the step fails and says so."""
    ctx = make_ctx(render=FakeRender(services=False))
    ctx.blueprint_timeout = 30
    with pytest.raises(TitanError, match="the Blueprint's services"):
        run(plan_deploy(ctx))


def test_deploy_refuses_when_the_admin_cannot_create_roles(make_ctx: Any) -> None:
    """An admin without CREATEROLE stops the plan."""
    with pytest.raises(TitanError, match="CREATEROLE"):
        plan_deploy(make_ctx(db=FakeDb(allowed=False)))


def test_a_failed_deploy_is_an_error(make_ctx: Any) -> None:
    """A redeploy that fails stops the run, naming the service."""
    render = FakeRender()
    render.latest["srv-web"] = {"id": "dep-0", "status": "build_failed"}
    render.statuses["srv-web"] = ["build_failed"]
    view = RecordingView()
    with pytest.raises(TitanError, match="tally's deploy dep-1 ended build_failed"):
        execute(plan_deploy(make_ctx(render=render)), view, commit=True)
    assert view.titles("failed") == ["Deploy what changed, then check /healthz"]


def test_an_unhealthy_app_is_an_error(make_ctx: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """/healthz never answering 200 fails the run with the last answer."""
    monkeypatch.setattr("titan.plans.health", lambda url: "503")
    with pytest.raises(TitanError, match=r"did not answer 200 \(last: 503\)"):
        run(plan_deploy(make_ctx()))


# ---------------------------------------------------------------- golive


def test_golive_dry_run_gives_the_cname(make_ctx: Any) -> None:
    """The first line is the DNS record to add by hand."""
    render = FakeRender()
    plan = plan_golive(make_ctx(render=render))
    run(plan, commit=False)
    assert "CNAME  tally  →  tally-s2nb.onrender.com" in plan.steps[0].title
    assert plan.steps[1].title == "In fivebar: add the site tally.ultraniche.ai"
    assert plan.steps[1].detail == (
        "by hand, at https://fiveb.ar/sites (or give titan a FIVEBAR_API_KEY)"
    )
    assert render.writes == []


def test_golive_verifies_sets_site_url_and_checks(make_ctx: Any, checked: list[str]) -> None:
    """SITE_URL and FIVEBAR_DOMAIN go in the app's group; the shared one covers the hosts."""
    render = FakeRender()
    render.create_env_group("tally", "tea-1", {"DJANGO_SECRET_KEY": "k"})
    render.add_custom_domain("srv-web", "tally.ultraniche.ai")
    plan = plan_golive(make_ctx(render=render))
    assert plan.steps[-2].title.startswith("Set SITE_URL, FIVEBAR_DOMAIN, deploy")
    run(plan)
    group = render.group_values("tally")
    assert group["SITE_URL"] == "https://tally.ultraniche.ai"
    assert group["FIVEBAR_DOMAIN"] == "tally.ultraniche.ai"
    assert render.envs["srv-web"] == {}
    assert render.deploys == ["srv-web", "crn-cron"]
    assert checked == ["https://tally.ultraniche.ai"]


def test_golive_on_a_live_app_only_turns_on_the_counts(make_ctx: Any) -> None:
    """An app that went live before fivebar gets FIVEBAR_DOMAIN alone, and a deploy."""
    render = FakeRender()
    render.create_env_group("tally", "tea-1", {"SITE_URL": "https://tally.ultraniche.ai"})
    render.add_custom_domain("srv-web", "tally.ultraniche.ai")
    render.verify_custom_domain("srv-web", "tally.ultraniche.ai")
    plan = plan_golive(make_ctx(render=render))
    assert plan.steps[-2].title.startswith("Set FIVEBAR_DOMAIN, deploy")
    run(plan)
    assert render.group_values("tally")["FIVEBAR_DOMAIN"] == "tally.ultraniche.ai"
    assert render.deploys == ["srv-web", "crn-cron"]


def test_golive_marks_the_app_live_and_keeps_hand_edits(make_ctx: Any) -> None:
    """Stage moves to live; the name and a paused `updates` set by hand stay."""
    render = FakeRender()
    render.add_custom_domain("srv-web", "tally.ultraniche.ai")
    render.verify_custom_domain("srv-web", "tally.ultraniche.ai")
    edited = TALLY_NEW.replace('"Tally"', '"Tally Workouts"').replace("true", "false")
    other = '{"slug": "atlas", "name": "Atlas", "repo": "o/atlas", "domain": "d",'
    other += ' "stage": "new", "updates": true}'
    github = FakeGitHub(register=edited.replace("[{", "[" + other + ", {"))
    run(plan_golive(make_ctx(render=render, github=github)))
    atlas, tally = github.register()
    assert atlas["slug"] == "atlas"
    assert (tally["stage"], tally["name"], tally["updates"]) == ("live", "Tally Workouts", False)
    assert github.commits == ["Update tally in the register of Titan apps (live)"]


def test_golive_on_a_registered_live_app_leaves_the_register(make_ctx: Any) -> None:
    """Already live in the register: the step is shown done and nothing is committed."""
    github = FakeGitHub(register=TALLY_NEW.replace('"new"', '"live"'))
    plan = plan_golive(make_ctx(github=github))
    assert plan.steps[-1].title == "In the register of Titan apps as live"
    assert plan.steps[-1].run is None


def test_golive_adds_the_fivebar_site_with_a_token(make_ctx: Any) -> None:
    """With a token, golive adds the site itself, before the deploy that turns counting on."""
    render = FakeRender()
    render.add_custom_domain("srv-web", "tally.ultraniche.ai")
    fivebar = FakeFivebar()
    plan = plan_golive(make_ctx(render=render, fivebar=fivebar))
    assert plan.steps[1].title == "Add the site tally.ultraniche.ai to fivebar"
    run(plan)
    assert fivebar.added == ["tally.ultraniche.ai"]


def test_golive_leaves_an_existing_fivebar_site_alone(make_ctx: Any) -> None:
    """A site already on the account is a done step."""
    render = FakeRender()
    render.add_custom_domain("srv-web", "tally.ultraniche.ai")
    fivebar = FakeFivebar({"tally.ultraniche.ai"})
    plan = plan_golive(make_ctx(render=render, fivebar=fivebar))
    assert plan.steps[1].title == "fivebar site tally.ultraniche.ai"
    assert plan.steps[1].run is None
    run(plan)
    assert fivebar.added == []


def test_golive_adds_the_domain_to_hosts_pinned_on_the_service(make_ctx: Any) -> None:
    """An older app with DJANGO_ALLOWED_HOSTS on the service gets the domain added to it."""
    render = FakeRender()
    render.envs["srv-web"]["DJANGO_ALLOWED_HOSTS"] = "tally-s2nb.onrender.com"
    render.add_custom_domain("srv-web", "tally.ultraniche.ai")
    run(plan_golive(make_ctx(render=render)))
    assert render.envs["srv-web"]["DJANGO_ALLOWED_HOSTS"] == (
        "tally-s2nb.onrender.com,tally.ultraniche.ai"
    )


def test_golive_gives_up_when_dns_never_arrives(make_ctx: Any) -> None:
    """No verification within the timeout: stop before touching SITE_URL."""
    render = FakeRender()
    render.verify_flips = False
    render.add_custom_domain("srv-web", "tally.ultraniche.ai")
    ctx = make_ctx(render=render)
    ctx.verify_timeout = 60
    with pytest.raises(TitanError, match=r"has not verified tally\.ultraniche\.ai"):
        run(plan_golive(ctx))
    assert "tally" not in render.groups


def test_golive_needs_the_service(make_ctx: Any) -> None:
    """Go-live before the Blueprint points back at `deploy`."""
    with pytest.raises(TitanError, match="run `titan deploy tally` first"):
        plan_golive(make_ctx(render=FakeRender(services=False)))


def test_an_older_apps_service_values_are_copied_into_its_group(make_ctx: Any) -> None:
    """Values that live only on the service are copied to the group, without a redeploy."""
    render = FakeRender()
    url = "postgresql://tally:pw@dpg-abc123-a:5432/tally"
    render.envs["srv-web"].update(
        {"DATABASE_URL": url, "EMAIL_HOST_PASSWORD": "re_old", "DJANGO_SECRET_KEY": "sk"}
    )
    render.create_env_group("titan", "tea-1", SHARED)
    for service in ("srv-web", "crn-cron"):
        render.link_group("evg-titan", service)
    db = FakeDb(roles={"tally"}, databases={"tally"})
    plan = plan_deploy(make_ctx(render=render, db=db))
    step = next(s for s in plan.steps if s.title.startswith("Copy"))
    assert step.title == (
        "Copy DATABASE_URL, DJANGO_SECRET_KEY, EMAIL_HOST_PASSWORD from the tally service "
        "into the app's env group 'tally'"
    )
    run(plan)
    group = render.group_values("tally")
    assert (group["DATABASE_URL"], group["EMAIL_HOST_PASSWORD"]) == (url, "re_old")
    assert render.envs["srv-web"]["DATABASE_URL"] == url
    # Writing DEFAULT_FROM_EMAIL and linking the new group are real changes: one deploy.
    assert render.deploys == ["srv-web", "crn-cron"]


def test_keys_that_belong_elsewhere_in_the_app_group_are_reported(make_ctx: Any) -> None:
    """A shared key left in the app's group is named, and left alone."""
    render = FakeRender()
    render.create_env_group("tally", "tea-1", {"EMAIL_PORT": "587", "SECRET_KEY": "x"})
    plan = plan_deploy(make_ctx(render=render))
    step = next(s for s in plan.steps if s.title.startswith("App env group"))
    assert step.detail == "also holds EMAIL_PORT, SECRET_KEY: move or delete them in Render"
    run(plan)
    assert render.group_values("tally")["EMAIL_PORT"] == "587"
