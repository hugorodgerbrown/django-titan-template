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
icons and a share card, write `uv.lock` and `package-lock.json`, and `git init`.

Questions: the product name, slug, description, author, copyright holder
(for the site footer), brand colour,
whether to serve an MCP endpoint through
[mcp-auth](https://github.com/hugorodgerbrown/mcp-auth) (and which release,
and who may connect), and the Render region.

## Provision and deploy a new app

Starting a new app? Work through [NEW_PROJECT_CHECKLIST.md](NEW_PROJECT_CHECKLIST.md):
every phase from the Linear issue to the app directories, and the snags
the first three apps hit.

[titan](titan/) sets up everything around a new app and takes it live:
the GitHub repo, a role and database on shared-db, a sending-only Resend
key, the shared and per-app env groups, the Render services and the
custom domain. Each app is `<slug>.ultraniche.ai` and sends from
`<slug>@mail.ultraniche.ai`.

```bash
uv tool install "git+https://github.com/hugorodgerbrown/django-titan-template#subdirectory=titan"
titan new tally      # generate the repo and push it to GitHub; nothing on Render
# ...work on it...
titan deploy tally   # set it up on Render and deploy it
titan golive tally   # after the CNAME: the custom domain
```

Plain `titan` asks what to do. Every command shows the plan and asks before
changing anything.

It reads its keys from a 1Password item named `Titan`. Install,
keys, env groups and every command are in [titan/README.md](titan/README.md).

## Keep a project up to date

```bash
cd my-project
copier update --trust
```

Copier replays your answers against the newer template and shows the
difference as a normal merge: review it like any PR.

## The register of Titan apps

[apps.json](apps.json) lists every app made from this template, so
anything that has to reach all of them, such as the routine that runs
`copier update` in each and opens a PR, reads one file:

```json
{"slug": "tally", "name": "Tally", "repo": "hugorodgerbrown/tally",
 "domain": "tally.ultraniche.ai", "stage": "live", "updates": true}
```

titan keeps it: `titan new` adds the app at stage `new` (and adds an app
made before the register when run on its existing repo), and `titan golive`
moves it to `live`. Each is a commit to `main` here. `updates` starts
`true` and titan never changes it; set it to `false` in a PR to stop
update PRs for one app, for example during a rewrite. Only apps made with
copier belong in it: an app with no `.copier-answers.yml` has nothing for
`copier update` to replay.

## The ultraniche.ai homepage

The page at ultraniche.ai that reveals the Titan apps one at a time lives in
[ultraniche-homepage](https://github.com/hugorodgerbrown/ultraniche-homepage).
A launch is one edit to its `apps.json`.

## What a project gets

| Area | What |
| --- | --- |
| Backend | Django 6.1, one env-driven settings module, Postgres via `DATABASE_URL`, WhiteNoise, gunicorn |
| PWA | Scoped to `/app/`: manifest, icons, `/app/sw.js` (precached shell, network-first pages with a 4 s fallback, offline page), launch screen |
| Accounts | Sign-up and sign-in by emailed link or code (single use, hashed, rate-limited), passkeys added from the account page, email sent from a task |
| Public pages | Placeholder homepage, terms and privacy notice, outside the app's scope |
| Error pages | 400, 403, 404, 500 and CSRF failure as one card on the site's frame, with 400 and 500 drawn without the request or database; JSON for MCP and API clients, plain text for htmx; staff preview at `/app/design/errors/<kind>/` |
| Offline writes | IndexedDB outbox with backoff, Background Sync where available, per-user rows; `IdempotencyMiddleware` so a retried write is applied once |
| Example | A notes app that proves an offline write end to end |
| MCP (optional) | `/mcp` JSON-RPC endpoint with notes tools, plus the privacy notice, terms and help as Markdown, and an MCP App (`list_notes` drawn as a card in Claude), authenticated by mcp-auth, passing its contract suite |
| Tests | pytest + FactoryBoy (90% floor), Vitest + fake-indexeddb, three capped Playwright journeys (offline write, offline fallback, passkey) |
| Lint and types | ruff (format, lint, bandit, docstrings), mypy + django-stubs, pre-commit |
| Design system | [DESIGN.md](template/DESIGN.md): the rules every app's design system follows (tokens only, limits on colours, type, spacing, corners and shadows, no dead CSS), enforced by `tests/test_design.py`; and a staff-only design page at `/app/design/` showing every token and component state from the real CSS |
| Onboarding | The rule that every app ships a first-run tour on private demo data, measured in fivebar (a decision record), and a blank script, `docs/onboarding-tour.md`, to fill in before building it. The tour itself is built per app; no tour engine is included yet |
| Analytics | [fivebar](https://fiveb.ar) visitor counts, no cookies: its tag on every page once `FIVEBAR_DOMAIN` is set (titan sets it at go-live), with private paths counted by their route |
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
