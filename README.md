# django-titan-template

The Titan project template: a Django + plain-JavaScript PWA that installs,
launches with a loading screen, works offline, and queues writes on the
device until it can send them. People sign up and sign in with an emailed
link or code, and add passkeys; there are no passwords. Testing, linting, type checking, security
scanning, performance budgets and CI come configured, lifted from Tally and
Snowdesk rather than invented.

## Start a project

```bash
uv tool install copier
copier copy --trust gh:hugorodgerbrown/django-titan-template my-project
cd my-project && uv run tox
```

`--trust` lets the template run its post-generation tasks: draw placeholder
icons, write `uv.lock` and `package-lock.json`, and `git init`.

Questions: the product name, slug, description, author, brand colour,
whether to serve an MCP endpoint through
[mcp-auth](https://github.com/hugorodgerbrown/mcp-auth) (and which release,
and who may connect), and the Render region.

## Provision and deploy a new app

`bin/titan` sets up everything around a new app: the GitHub repo, the
Render services, a role and database on shared-db, a sending-only Resend
key, the env vars and the custom domain. Each app is `<slug>.ultraniche.ai`
and sends from `<slug>@mail.ultraniche.ai`.

```bash
bin/titan new resort-planner             # plan: reads every account, changes nothing
bin/titan new resort-planner --commit    # generate, push, then stops for the Blueprint
#   → deploy the Blueprint from the printed link (leave prompted values blank)
bin/titan new resort-planner --commit    # database, Resend key, env vars, domain, deploy
bin/titan golive resort-planner --commit # prints the CNAME, waits for DNS, sets SITE_URL
```

An app with no scheduled jobs can leave the `<slug>-purge` cron job out of
its `render.yaml`; `titan` then provisions the web service alone.

Two steps stay manual because neither provider has an API for them:
creating the Blueprint in Render (one click) and adding the CNAME in
Squarespace at go-live (one record). Every run is safe to repeat; it does
only what is still missing. Until go-live the app runs on its onrender.com
address, so it can be tried before the domain points at it.

It needs `uv`, `gh` (signed in) and these three keys. `titan` asks for each
one (the input is hidden) unless `~/.config/titan/env` holds it, and never
reads them from the environment, so an app's own keys exported in your
shell can't be picked up by mistake. All three are account-wide, not per
app:

| Setting | What |
|---|---|
| `RENDER_API_KEY` | Render API key |
| `RESEND_API_KEY` | A **full-access** Resend key; it creates each app's sending-only key |
| `TITAN_DB_ADMIN_URL` | shared-db's External Database URL. shared-db only accepts its allowlisted IP addresses, so run `titan` from one of them |

`TITAN_DOMAIN`, `TITAN_MAIL_DOMAIN` and `TITAN_GITHUB_OWNER` (environment or
the config file) override the defaults. Secrets go from each provider straight into Render and are never
printed. Tests: `uv run --with pytest --with 'psycopg[binary]' pytest tests`.

## Keep a project up to date

```bash
cd my-project
copier update --trust
```

Copier replays your answers against the newer template and shows the
difference as a normal merge: review it like any PR.

## What a project gets

| Area | What |
| --- | --- |
| Backend | Django 6.1, one env-driven settings module, Postgres via `DATABASE_URL`, WhiteNoise, gunicorn |
| PWA | Scoped to `/app/`: manifest, icons, `/app/sw.js` (precached shell, network-first pages with a 4 s fallback, offline page), launch screen |
| Accounts | Sign-up and sign-in by emailed link or code (single use, hashed, rate-limited), passkeys added from the account page, email sent from a task |
| Public pages | Placeholder homepage, terms and privacy notice, outside the app's scope |
| Offline writes | IndexedDB outbox with backoff, Background Sync where available, per-user rows; `IdempotencyMiddleware` so a retried write is applied once |
| Example | A notes app that proves an offline write end to end |
| MCP (optional) | `/mcp` JSON-RPC endpoint with notes tools, plus the privacy notice, terms and help as Markdown, and an MCP App (`list_notes` drawn as a card in Claude), authenticated by mcp-auth, passing its contract suite |
| Tests | pytest + FactoryBoy (90% floor), Vitest + fake-indexeddb, three capped Playwright journeys (offline write, offline fallback, passkey) |
| Lint and types | ruff (format, lint, bandit, docstrings), mypy + django-stubs, pre-commit |
| Security | Strict CSP (no inline anything), `check --deploy`, semgrep, pip-audit, npm audit, gitleaks, Dependabot |
| Performance | Precache byte budget, query-count assertions, Lighthouse CI budgets |
| CI and deploy | One GitHub Actions job per tox env; Render Blueprint with a daily clean-up job |
| Docs | `CLAUDE.md`, testing, PWA, security, performance, decision records; Claude Code skills for the Linear docs (research, user testing script, blog post), short by default; they need the [Linear MCP server](https://linear.app/docs/mcp) |

Read the generated `docs/pwa.md` for how the offline pieces fit together.

## Working on the template

Template files live in `template/`; files ending `.jinja` are rendered
with the answers, everything else is copied as is. CI (`template-ci.yml`)
generates a project with and without MCP and runs its full check suite,
browser journeys included. Locally:

```bash
copier copy --trust --defaults --vcs-ref HEAD . /tmp/app && (cd /tmp/app && uv run tox)
```
