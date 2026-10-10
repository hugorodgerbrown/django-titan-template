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
| Docs | `CLAUDE.md`, testing, PWA, security, performance, decision records; Claude Code skills for the Linear docs (research, user testing script, blog post), short by default |

Read the generated `docs/pwa.md` for how the offline pieces fit together.

## Working on the template

Template files live in `template/`; files ending `.jinja` are rendered
with the answers, everything else is copied as is. CI (`template-ci.yml`)
generates a project with and without MCP and runs its full check suite,
browser journeys included. Locally:

```bash
copier copy --trust --defaults --vcs-ref HEAD . /tmp/app && (cd /tmp/app && uv run tox)
```
