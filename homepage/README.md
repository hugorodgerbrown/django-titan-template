# ultraniche.ai homepage

The UltraNiche homepage: one static page showing Project Titan's ten apps,
revealed one at a time, and the earlier apps. Hosted on Render as a free
static site.

## Launch the next app

Everything the page shows comes from `apps.json`. To launch an app:

1. Fill in its `tagline` and `url` (and `story`, once the post exists).
2. Raise `opened` by one.

That opens it, and the app after it shows its icon and name as "Coming next".
Nothing about an app reaches the page before its state allows it: a sealed
app shows only its number, and the next app shows no tagline or link. The
build refuses an `opened` count that would open an app with no tagline or
link.

Colours are each app's brand colour; the icons are its initial on that
colour until it has a real icon.

## Work on it

```bash
cd homepage
uv sync
uv run pytest
uv run ruff format . && uv run ruff check .
python3 build.py          # writes dist/; open dist/index.html
```

The build uses only the Python standard library. Render's static site
`ultraniche-home` (https://ultraniche-home.onrender.com) runs
`cd homepage && python3 build.py` and publishes `homepage/dist`, with
nothing to install. It deploys every push to `main`.

It lives in this repository because Project Zero holds everything the
Titan apps share, and the launch tile (RAS-39) is part of it.
