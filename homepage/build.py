"""Build the ultraniche.ai homepage from apps.json into dist/.

The page is static: src/index.html is a string.Template, filled with the
Titan tiles and the earlier apps. apps.json's "opened" count is the one
setting a launch changes: apps 1..opened are open, the next one shows its
brand only, and the rest show nothing but their number. Nothing about an
app is written into the page before its state allows it.

Run with no arguments; exits non-zero if apps.json is invalid.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import sys
from dataclasses import dataclass
from html import escape
from pathlib import Path
from string import Template

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
DIST = ROOT / "dist"
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
LOCK = (
    '<svg class="lock" width="18" height="18" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round" aria-hidden="true"><rect x="5" y="11" width="14" '
    'height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>'
)


class ConfigError(ValueError):
    """apps.json does not describe a page that can be built."""


@dataclass(frozen=True)
class Tile:
    """One Titan app as the page shows it.

    Attributes:
        number: Its place in the run, from 1.
        state: "open", "next" or "sealed".
        app: Its entry in apps.json.
    """

    number: int
    state: str
    app: dict

    @property
    def num(self) -> str:
        """Return the number as two digits."""
        return f"{self.number:02d}"


def load(path: Path) -> dict:
    """Read and check apps.json.

    Args:
        path: The file to read.

    Returns:
        The parsed config.

    Raises:
        ConfigError: The config is inconsistent.
    """
    config = json.loads(path.read_text(encoding="utf-8"))
    titan = config.get("titan")
    if not isinstance(titan, list) or not titan:
        raise ConfigError("titan must be a non-empty list")
    opened = config.get("opened")
    if not isinstance(opened, int) or isinstance(opened, bool) or not 0 <= opened <= len(titan):
        raise ConfigError(f"opened must be a whole number from 0 to {len(titan)}")
    for index, app in enumerate(titan, start=1):
        for key in ("name", "colour"):
            if not app.get(key):
                raise ConfigError(f"titan app {index} needs a {key}")
        if not HEX.match(app["colour"]):
            raise ConfigError(f"titan app {index}: colour must be #RRGGBB")
        if index <= opened:
            for key in ("tagline", "url"):
                if not app.get(key):
                    raise ConfigError(f"{app['name']} is open, so it needs a {key}")
    for app in config.get("earlier", []):
        for key in ("name", "colour", "tagline", "url"):
            if not app.get(key):
                raise ConfigError(f"earlier app needs a {key}: {app!r}")
        if not HEX.match(app["colour"]):
            raise ConfigError(f"{app['name']}: colour must be #RRGGBB")
    return config


def tiles(config: dict) -> list[Tile]:
    """Give each Titan app its state from the opened count.

    Args:
        config: The checked config.

    Returns:
        One tile per app, in order.
    """
    opened = config["opened"]
    result = []
    for number, app in enumerate(config["titan"], start=1):
        if number <= opened:
            state = "open"
        elif number == opened + 1:
            state = "next"
        else:
            state = "sealed"
        result.append(Tile(number=number, state=state, app=app))
    return result


def icon(app: dict, size: str) -> str:
    """Return an app's placeholder icon: its initial on its colour.

    Args:
        app: The app's entry.
        size: The CSS size class, "md" or "lg".

    Returns:
        The icon's HTML.
    """
    return (
        f'<span class="icon icon--{size}" style="background:{app["colour"]}" '
        f'aria-hidden="true">{escape(app["name"][0])}</span>'
    )


def render_tile(tile: Tile) -> str:
    """Return one tile's HTML. A sealed tile carries only its number.

    Args:
        tile: The tile to draw.

    Returns:
        The tile's HTML.
    """
    app = tile.app
    name = escape(app["name"])
    if tile.state == "sealed":
        return (
            f'<li class="tile tile--sealed" aria-label="Titan {tile.num}, still under wraps">'
            f'{LOCK}<span class="tile__bignum">{tile.num}</span></li>'
        )
    if tile.state == "next":
        return (
            f'<li class="tile tile--next" aria-label="Titan {tile.num}: {name}, coming next">'
            f'<span class="tile__row"><span class="tile__num">{tile.num}</span>'
            f'<span class="pill">Next</span></span>'
            f'<span class="tile__brand">{icon(app, "lg")}'
            f'<span class="tile__name">{name}</span></span>'
            f'<span class="tile__foot">Coming next</span></li>'
        )
    story = (
        f'<a class="btn btn--quiet" href="{escape(app["story"])}">Read the story</a>'
        if app.get("story")
        else ""
    )
    return (
        f'<li class="tile tile--open">'
        f'<span class="tile__row">{icon(app, "md")}<span class="tile__num">{tile.num}</span></span>'
        f'<span class="tile__text"><h3>{name}</h3><p>{escape(app["tagline"])}</p></span>'
        f'<span class="tile__links"><a class="btn" style="background:{app["colour"]}" '
        f'href="{escape(app["url"])}">Open {name}</a>{story}</span></li>'
    )


def render_earlier(app: dict) -> str:
    """Return an earlier app's card.

    Args:
        app: The app's entry.

    Returns:
        The card's HTML.
    """
    host = escape(app["url"].split("://", 1)[-1].rstrip("/"))
    return (
        f'<li><a class="card card--app" href="{escape(app["url"])}">{icon(app, "md")}'
        f'<span class="card__text"><span class="card__name">{escape(app["name"])}</span>'
        f'<span class="card__tag">{escape(app["tagline"])}</span>'
        f'<span class="card__host" style="color:{app["colour"]}">{host}</span></span></a></li>'
    )


def render(config: dict, template: str) -> str:
    """Fill the page template.

    Args:
        config: The checked config.
        template: src/index.html's text.

    Returns:
        The finished page.
    """
    all_tiles = tiles(config)
    total = len(all_tiles)
    opened = config["opened"]
    open_tiles = [t for t in all_tiles if t.state == "open"]
    next_tiles = [t for t in all_tiles if t.state == "next"]
    sealed = [t for t in all_tiles if t.state == "sealed"]
    # On a phone: the next app, then the newest open ones, then a strip.
    first = next_tiles + open_tiles[::-1]
    strip = "".join(
        f'<li class="chip" aria-label="Titan {t.num}, still under wraps">{t.num}</li>'
        for t in sealed
    )
    segments = "".join(f'<span class="seg seg--{t.state}"></span>' for t in all_tiles)
    if next_tiles:
        next_line = f"Coming next: {escape(next_tiles[0].app['name'])}"
    else:
        next_line = f"All {total} are open."
    return Template(template).substitute(
        open_line=f"{opened} of {total} open" if opened else "None open yet",
        next_line=next_line,
        total=total,
        segments=segments,
        grid="".join(render_tile(t) for t in all_tiles),
        first="".join(render_tile(t) for t in first),
        strip=(
            '<div class="strip"><h3 class="strip__title">Still under wraps</h3>'
            f'<ol class="strip__chips">{strip}</ol></div>'
            if sealed
            else ""
        ),
        earlier="".join(render_earlier(app) for app in config.get("earlier", [])),
    )


def build(config_path: Path = ROOT / "apps.json", out: Path = DIST) -> Path:
    """Build the site into ``out``, replacing what was there.

    Args:
        config_path: apps.json.
        out: The folder to write.

    Returns:
        The page written.
    """
    config = load(config_path)
    page = render(config, (SRC / "index.html").read_text(encoding="utf-8"))
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(SRC, out, ignore=shutil.ignore_patterns("index.html"))
    index = out / "index.html"
    index.write_text(page, encoding="utf-8")
    logger.info("Built %s with %s of %s open", index, config["opened"], len(config["titan"]))
    return index


def main() -> int:
    """Build the site; return the exit status."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        build()
    except (ConfigError, json.JSONDecodeError) as error:
        logger.error("apps.json: %s", error)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
