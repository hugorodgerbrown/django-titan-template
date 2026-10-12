# CLAUDE.md — the ultraniche.ai homepage (homepage/)

The UltraNiche homepage, a static page built by `build.py` from `apps.json`
and `src/`. Read README.md first.

- `apps.json` is the only thing a launch changes. Never put an unlaunched
  app's tagline, link or story into the page.
- `build.py` stays standard library only (Render builds with plain
  `python3`). Dev tools come through `uv` (`[dependency-groups]`).
- Module header docstring, Google-style docstrings, every argument typed;
  British English. `uv run ruff format . && uv run ruff check . && uv run
  pytest` from homepage/ before a PR; the homepage workflow runs the same.
- Visitor counts are fivebar's script tag in `src/index.html`; no cookies.
