# titan

Starts a new Titan app, and later takes it live: the GitHub repo, then the
Render services, a role and database on shared-db, a sending-only Resend
key, the env groups and the custom domain.

## Install

```sh
uv tool install "git+https://github.com/hugorodgerbrown/django-titan-template#subdirectory=titan"
uv tool upgrade titan      # later, for fixes
```

It also needs `gh` (signed in), `uvx`, and the 1Password CLI `op` if the
keys live in 1Password.

## Use

```sh
titan new tally       # generate the repo and push it to GitHub; nothing on Render
                      # ...work on it, push to main...
titan deploy tally    # set it up on Render and deploy it
titan golive tally    # after the CNAME: verify, set SITE_URL and FIVEBAR_DOMAIN, deploy, check
titan status tally    # what exists and what is missing; changes nothing
titan                 # asks which of these, then asks about the app
```

`golive` also turns on the app's visitor counts: it adds the app's
domain as a site on fivebar and sets `FIVEBAR_DOMAIN` to it. Adding the
site needs `FIVEBAR_API_KEY` (below); without it, golive lists adding
the site at [fiveb.ar/sites](https://fiveb.ar/sites) as a step to do by
hand. Until the site is on fivebar, nothing is counted.

Every command reads the accounts first, shows the whole plan, and asks
before changing anything. `--commit` applies without asking and `--plan`
only shows the plan. Each step does only what is missing, so a failed or
interrupted run is fixed by running it again, and a run on a finished app
says "Nothing to do."

`new` runs copier into `<dir>/<slug>` (the current directory unless you
pass `--dir`), commits the result and pushes it to a private GitHub repo.
`--name` and `--description` answer copier's questions; the rest take the
template's defaults. It never touches Render, shared-db or Resend.

`deploy` needs the repo on GitHub, because Render builds `main` from
there, never from your laptop. It makes everything up front, including
both env groups, so the Blueprint's first deploy has all its settings.
It then opens the Blueprint link in your browser and waits while you click
Deploy Blueprint. It's the one step Render offers no API for. Then it
links the groups (if the Blueprint didn't), adds the domain, deploys
anything that changed, and checks `/healthz`.

## Keys

Three account-wide keys (and an optional fourth, `FIVEBAR_API_KEY`), looked for in this order:

1. **1Password:** an item named `Titan` (set `TITAN_OP_ITEM` to change it,
   and `TITAN_OP_VAULT` to pick a vault) with one field per key, labelled
   exactly as below. titan reads it with one `op item get`, so 1Password
   asks to unlock once.
2. `~/.config/titan/env`: `KEY=value` lines.
3. A hidden prompt.

They are never read from the environment. A shell inside an app's
checkout often exports that app's own keys, and titan must not pick
those up.

| Field | What |
| --- | --- |
| `RENDER_API_KEY` | Render API key (Account settings, API keys) |
| `RESEND_API_KEY` | a **full-access** Resend key: it creates each app's sending-only key |
| `TITAN_DB_ADMIN_URL` | shared-db's External Database URL. shared-db only accepts its allowlisted IP addresses |
| `FIVEBAR_API_KEY` | optional, and never asked for: a fivebar API token (Settings, API tokens) allowed to add sites. Without it, golive's fivebar step is by hand |

Optional settings can go in the environment or in the file:
- `TITAN_DOMAIN` (default `ultraniche.ai`)
- `TITAN_MAIL_DOMAIN` (default `mail.ultraniche.ai`)
- `TITAN_GITHUB_OWNER` (default `hugorodgerbrown`)
- `TITAN_RENDER_WORKSPACE`, an id or name, for when the key sees several
- `TITAN_DB_INTERNAL_HOST`

## Env groups

Every app's services link two Render env groups. titan makes both, and
render.yaml references them (`fromGroup`) without declaring them, so a
Blueprint sync never overwrites them.

| Group | Holds |
| --- | --- |
| `titan` (shared) | `DJANGO_DEBUG=0`, `PYTHON_VERSION`, `DJANGO_ALLOWED_HOSTS=.ultraniche.ai`, `DJANGO_CSRF_TRUSTED_ORIGINS=https://*.ultraniche.ai`, and the SMTP relay (`EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_USE_TLS`) |
| `<slug>` (per app) | `DATABASE_URL`, `DJANGO_SECRET_KEY`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`, and `SITE_URL` and `FIVEBAR_DOMAIN` from go-live |

titan adds keys missing from `titan` but never overwrites one you changed
in the dashboard. It lists the changed ones in the plan. A key belongs to
one group only. To override a shared value for one app, set it on the
service itself, because a service's own env vars win over its groups'.

## Develop

```sh
cd titan
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy
```
