"""The web app (web/ sources, built into src/stackvitals/web/app/ and index.html): the build is present, the page runs
only its own scripts, the first screen and fonts stay within budget, and every route has its page module."""
import gzip
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "src" / "stackvitals" / "web"
APP = WEB / "app"
SRC = ROOT / "web"
# 46 KiB since 2026-10-30 (44.8 KB measured): Instrument's styles now ship in main.css; before, sheet.css was a separate request.
FIRST_SCREEN_GZ = 46 * 1024
FONTS = 90 * 1024
# The demo's three made-up repos ship in every install, so they stay small.
# 288 KiB since 2026-10-29 (UI coverage): settings.json and portal.json are now shared by the three repos, and every
# Phase 23/24 field (security, deployments, releases, risk, code quality, knowledge map...) has demo values.
DEMO = 288 * 1024


def _gz(path: Path) -> int:
    return len(gzip.compress(path.read_bytes(), 9))


def test_the_build_output_is_there():
    for rel in ("main.js", "main.css", "boot.js", "LICENSES.md", "fonts/plex-sans-400.woff2", "pages/overview.js", "pages/ci.js"):
        assert (APP / rel).is_file(), rel
    for repo in ("payments-api", "web-app", "mobile"):
        assert (APP / "demo" / repo / "app.json").is_file()
    licences = (APP / "LICENSES.md").read_text(encoding="utf-8")
    assert "Preact" in licences and "uPlot" in licences and "Open Font License" in licences


def test_the_page_runs_only_its_own_scripts():
    page = (WEB / "index.html").read_text(encoding="utf-8")
    assert "script-src 'self'" in page and "object-src 'none'" in page
    scripts = re.findall(r'<script[^>]*src="([^"]+)"', page)
    assert scripts and all(s.startswith("app/") for s in scripts)
    assert "<script>" not in page and "http://" not in page.split("Content-Security-Policy")[0]
    for p in APP.rglob("*.js"):
        text = p.read_text(encoding="utf-8")
        assert "cdn.jsdelivr" not in text and "unpkg.com" not in text and "fonts.googleapis" not in text, p.name
    linked = re.findall(r'(?:href|src)="(app/[^"?]+)"', page)
    assert all((WEB / p).is_file() for p in linked), [p for p in linked if not (WEB / p).is_file()]


def test_the_first_screen_and_fonts_stay_within_budget():
    page = (WEB / "index.html").read_text(encoding="utf-8")
    # What every visitor loads: Instrument is the only design and its styles are in main.css.
    first = ["app/main.js", "app/main.css", "app/boot.js", *re.findall(r'rel="modulepreload" href="([^"]+)"', page)]
    total = sum(_gz(WEB / p) for p in first)
    assert total <= FIRST_SCREEN_GZ, f"first screen is {total} bytes gzipped"
    assert not any("uPlot" in p for p in first)  # the chart library loads lazily
    assert not (APP / "sheet.css").exists() and 'data-design="sheet"' in page
    fonts = {p.name: p.stat().st_size for p in (APP / "fonts").iterdir()}
    assert set(fonts) == set(re.findall(r'url\("?fonts/([^")]+)"?\)', (APP / "main.css").read_text(encoding="utf-8")))
    assert sum(fonts.values()) <= FONTS, fonts


def test_every_route_has_its_page_module():
    routes = (SRC / "src" / "app" / "routes.ts").read_text(encoding="utf-8")
    pages = re.findall(r'import\("\.\./pages/([a-z]+)"\)', routes)
    assert len(pages) >= 17
    for p in pages:
        assert (SRC / "src" / "pages" / f"{p}.tsx").is_file(), p
        assert (APP / "pages" / f"{p}.js").is_file(), p
    css = re.search(r'name="sv-page-css" content="([^"]*)"', (WEB / "index.html").read_text(encoding="utf-8")).group(1).split(",")
    assert all((APP / "pages" / f"{c}.css").is_file() for c in css if c)


def test_the_demo_data_stays_small():
    size = sum(p.stat().st_size for p in (APP / "demo").rglob("*") if p.is_file())
    assert size <= DEMO, f"the demo is {size} bytes"
