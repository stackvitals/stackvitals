"""The StackVitals app (built from web/ into the package's web/index.html and web/app/): shipped with its bundled libraries
and their licences, no CDN and no bare imports (so it works offline under `stackvitals ui` and on any Pages site), the
committed build is current, every route has its page, old links still land, and a job publishes it at the site's front
door without changing it on a quiet run."""
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from stackvitals.core.webapp import files
from stackvitals.core.workspace import run_job

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "stackvitals" / "web"
SRC = ROOT / "web"
NOW = datetime(2026, 10, 21, 9, tzinfo=timezone.utc)
NODE = shutil.which("node")
# Every relative module specifier in a built file: static, side-effect, re-export and dynamic imports.
SPECS = re.compile(r"""(?:\bfrom|\bimport\s*\(?)\s*["']([\w@./?=-]+)["']""")


def _strips_types() -> bool:
    # Node 22.18+ loads TypeScript files that only use erasable syntax.
    if not NODE:
        return False
    out = subprocess.run([NODE, "--version"], capture_output=True, text=True).stdout.strip().lstrip("v").split(".")
    major, minor = int(out[0]), int(out[1])
    return major >= 24 or (major == 23 and minor >= 6) or (major == 22 and minor >= 18)


needs_ts = pytest.mark.skipif(not _strips_types(), reason="Node 22.18+ isn't installed")
needs_build_tools = pytest.mark.skipif(not NODE or not (SRC / "node_modules" / "esbuild").is_dir(), reason="node or web/node_modules missing")


def _node_ts(script: str, cwd: Path) -> str:
    out = subprocess.run([NODE, "--input-type=module", "-e", script], cwd=cwd, capture_output=True, text=True, timeout=60, encoding="utf-8")
    assert out.returncode == 0, out.stderr[-2000:]
    return out.stdout


def test_the_app_ships_with_its_libraries_licences_and_no_remote_code():
    app = files()
    names = set(app)
    assert {"index.html", "app/main.js", "app/main.css", "app/boot.js", "app/LICENSES.md", "app/fonts/plex-sans-400.woff2"} <= names
    licences = app["app/LICENSES.md"].decode("utf-8")
    assert all(x in licences for x in ("Preact (MIT)", "uPlot (MIT)", "Open Font License", "TweetNaCl"))
    for name, data in app.items():
        if name.endswith((".js", ".mjs")):
            text = data.decode("utf-8")
            for spec in SPECS.findall(text):
                assert spec.startswith(("./", "../")), f"{name} imports {spec}"
            assert "cdn.jsdelivr" not in text and "unpkg.com" not in text and "fonts.googleapis" not in text, name
    page = app["index.html"].decode("utf-8")
    assert "script-src 'self'" in page and "object-src 'none'" in page  # the page runs only its own scripts
    assert "<script>" not in page
    linked = re.findall(r'(?:href|src)="(app/[^"?]+)"', page)
    assert len(linked) >= 5 and all(p in names for p in linked), [p for p in linked if p not in names]
    # The earlier app (Preact + htm views) is gone from the package.
    assert not [n for n in names if n.startswith(("app/views/", "app/vendor/", "next/")) or n == "next.html"]


@needs_build_tools
def test_the_committed_build_is_current(tmp_path):
    out = subprocess.run([NODE, "build.mjs", "--out", str(tmp_path)], cwd=SRC, capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr[-2000:]

    def tree(base: Path) -> dict[str, bytes]:
        got = {p.relative_to(base).as_posix(): p.read_bytes().replace(b"\r\n", b"\n") for p in (base / "app").rglob("*") if p.is_file()}
        got["index.html"] = (base / "index.html").read_bytes().replace(b"\r\n", b"\n")
        return got
    fresh, shipped = tree(tmp_path), tree(WEB)
    stale = sorted(k for k in fresh.keys() | shipped.keys() if fresh.get(k) != shipped.get(k))
    assert stale == [], f"run `npm run build` in web/ and commit the output: {stale[:10]}"


def test_every_route_has_its_page_and_every_app_link_lands():
    from stackvitals import shell
    routes = (SRC / "src" / "app" / "routes.ts").read_text(encoding="utf-8")
    ids = re.findall(r'\{ id: "([a-z]+)"', routes)
    pages = re.findall(r'import\("\.\./pages/([a-z]+)"\)', routes)
    assert len(ids) >= 17 and ids == pages
    assert all((WEB / "app" / "pages" / f"{p}.js").is_file() for p in pages)
    css = re.search(r'name="sv-page-css" content="([^"]*)"', files()["index.html"].decode("utf-8")).group(1).split(",")
    assert all((WEB / "app" / "pages" / f"{c}.css").is_file() for c in css if c)
    # Links the printable pages, chat messages and Portal exports carry, and the earlier app's routes, all have a page.
    router = (SRC / "src" / "app" / "router.ts").read_text(encoding="utf-8")
    old = dict(re.findall(r'(\w+): "(\w+)"', re.search(r"OLD_ROUTES: Record<string, string> = \{([^}]*)\}", router).group(1)))
    assert {"home", "integrations"} <= set(old) and set(old.values()) <= set(ids)
    assert set(shell.APP_ROUTES.values()) | {"ci", "delivery", "portal"} <= set(ids)


def test_a_job_puts_the_app_at_the_front_door_and_a_quiet_job_changes_nothing(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    env = {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": bare.as_uri(), "RUNNER_TEMP": str(tmp_path / "t")}

    def ci(ws):
        (ws.path / "docs").mkdir(exist_ok=True)
        (ws.path / "docs" / "ci.html").write_text("ci page", encoding="utf-8")
    run_job(env, [("CI Health", ci)], NOW)
    shown = subprocess.run(["git", "show", "stackvitals-data:docs/index.html"], cwd=bare, capture_output=True, text=True).stdout
    assert "app/main.js" in shown
    assert run_job(env, [("CI Health", ci)], NOW)["outcome"] == "unchanged"


def test_every_app_url_carries_one_version_so_a_cached_release_never_mixes_with_a_new_one(tmp_path):
    from stackvitals.core.webapp import write_webapp
    (tmp_path / "app" / "views").mkdir(parents=True)
    (tmp_path / "app" / "views" / "home.js").write_text("the earlier app", encoding="utf-8")
    write_webapp(tmp_path)
    assert not (tmp_path / "app" / "views").exists()  # an upgraded site carries only this release
    page = (tmp_path / "index.html").read_text(encoding="utf-8")
    main = (tmp_path / "app" / "main.js").read_text(encoding="utf-8")
    assert 'src="app/main.js?v=' in page and 'href="app/main.css?v=' in page and 'import("./pages/overview.js?v=' in main
    # boot.js preloads the first-screen fonts at the stylesheet's own unversioned URLs, so each downloads once.
    boot = (tmp_path / "app" / "boot.js").read_text(encoding="utf-8")
    assert "plus-jakarta-sans" not in boot and "plex-sans-400" in boot and "fonts/" in boot and "fonts/" not in page
    versions, unversioned = set(), []
    for path in (tmp_path / "app").rglob("*.js"):
        text = path.read_text(encoding="utf-8")
        for spec in SPECS.findall(text):
            url, _, v = spec.partition("?v=")
            versions.add(v)
            if not v or not (path.parent / url).resolve().is_file():
                unversioned.append(f"{path.name}: {spec}")
    assert unversioned == [] and len(versions | set(re.findall(r"\?v=([0-9a-f]+)", page))) == 1
    assert write_webapp(tmp_path) == []


@needs_ts
def test_a_request_the_app_builds_is_what_the_action_reads():
    """The contract between the page and the workflow (web/src/data/write.ts): its issue body parses back exactly."""
    from datetime import date

    from stackvitals.core import decisions as dec
    change = {"verb": "mute", "kind": "job", "id": "ci.yml / lint", "until": "2026-11-20", "reason": 'say "hi" & <b>'}
    settings = {"alerts.pickup_p75_hours": 6, "identity.teams": {"web": ["amy", "bob"]}, "digest.day": None, "community.norms": "Ünï ✓"}
    out = _node_ts("import { request, requestBody } from './write.ts'; "
                   f"console.log(requestBody(request([{json.dumps(change)}], {json.dumps(settings)}), 'note'))", SRC / "src" / "data")
    req = dec.parse_request(out, date(2026, 10, 21))
    assert req.settings == settings and req.changes == [dec.Decision("mute", "job", "ci.yml / lint", "2026-11-20", 'say "hi" & <b>')]


@needs_ts
def test_a_command_the_app_hands_out_names_exactly_the_item():
    """Review guard: unquoted ids with spaces decided a different item (Jest names, fix-first keys)."""
    from datetime import date

    from stackvitals.core import decisions as dec
    ids = ["src/Button.test.js::Button::renders correctly", "fix_job:.github/workflows/ci.yml / test", 'say "hi"',
           "tests\\win.py::it's", "plain::id"]
    out = _node_ts(f"import {{ target }} from './write.ts'; console.log(JSON.stringify({json.dumps(ids)}.map((i) => target('test', i))))",
                   SRC / "src" / "data")
    for ident, word in zip(ids, json.loads(out)):
        assert dec.parse_command(f"/stackvitals mute {word} for 7d because x", date(2026, 10, 21))[0].id == ident


@needs_ts
def test_a_refused_token_is_forgotten_and_an_outage_keeps_it():
    def after(status: int) -> str:
        return _node_ts("import { setToken, token, dispatch } from './write.ts'; "
                        f"globalThis.fetch = async () => ({{ ok: false, status: {status}, json: async () => ({{}}) }}); "
                        "setToken('github_pat_x', false); "
                        "try { await dispatch({ repo: 'o/r', default_branch: 'main', links: { workflow: 'stackvitals.yml' } }, {}); } "
                        "catch (e) { console.log('error: ' + e.message); } console.log('token: ' + token());", SRC / "src" / "data")
    for status in (401, 403, 404):
        assert "token: null" in after(status)
    assert "token: github_pat_x" in after(502)


@needs_ts
def test_the_threshold_preview_replays_alerts_like_the_action():
    import random

    from stackvitals.core.alerts import HEADS_UP, MIN_N, replay
    rng = random.Random(3)
    series = {m: [[f"d{k}", None if rng.random() < 0.1 else round(rng.uniform(0, 30), 2), rng.choice([0, 9, 10, 30])] for k in range(91)]
              for m in ("pickup_p75_hours", "review_p75_hours")}
    limits = {"pickup_p75_hours": 8, "review_p75_hours": 14}
    out = _node_ts(f"import {{ replay }} from './settingsReplay.ts'; console.log(JSON.stringify(replay({json.dumps(series)}, "
                   f"{json.dumps(limits)}, {{ headsUp: {HEADS_UP}, minN: {MIN_N} }})))", SRC / "src" / "features")
    assert json.loads(out) == replay({m: [tuple(p) for p in v] for m, v in series.items()}, limits)


@needs_build_tools
def test_the_packed_portal_file_unpacks_to_the_same_results(tmp_path):
    # Scale (Phase 17): the app's portal.json is packed to a third of its size; the app must read back every result.
    from stackvitals.portal.scorecard import pack
    results = [{"id": "codeowners", "level": "bronze", "result": "pass", "evidence": "CODEOWNERS file at .github/CODEOWNERS"},
               {"id": "ci-first-try", "level": "silver", "result": "not available", "evidence": "no benchmark yet"}]
    catalog = {"org": "o", "repos": [{"name": "o/a", "score": {"level": "bronze", "results": results}}, {"name": "o/b"}]}
    (tmp_path / "p.json").write_text(json.dumps(pack(catalog)), encoding="utf-8")
    out = _node_ts("import { load } from './test/load.mjs'; const fs = await import('node:fs');"
                   "globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };"
                   "globalThis.sessionStorage = globalThis.localStorage;"
                   "const { unpack } = await load('src/data/files.ts');"
                   f"const p = unpack(JSON.parse(fs.readFileSync({json.dumps(str(tmp_path / 'p.json'))}, 'utf8')));"
                   "console.log(JSON.stringify(p.repos.map((r) => r.score?.results || null)));", SRC)
    assert json.loads(out.strip().splitlines()[-1]) == [results, None]


def test_the_project_site_builds_and_never_reaches_a_repos_pages(tmp_path):
    """The landing page and forwards come from the package; a repo's app never carries them."""
    from stackvitals.core.webapp import site_files
    from stackvitals.site import build
    assert not [n for n in files() if n.startswith("site/") or n in ("setup.html", "integrations.html", "app.html")]
    for name, data in site_files().items():
        if name.endswith(".html"):
            assert "<script" not in data.decode("utf-8"), name  # the site pages run no code
    demo = tmp_path / "demo"
    demo.mkdir()
    (demo / "app.json").write_text(json.dumps({"repo": "o/r", "modules": {}}), encoding="utf-8")
    build(tmp_path / "dist", demo=demo)
    dist = tmp_path / "dist"
    assert all((dist / p).exists() for p in ("index.html", "app.html", "setup.html", "app/main.js", "app/demo/web-app/app.json",
                                             "demo/index.html", "demo/app.json"))
    landing = (dist / "index.html").read_text(encoding="utf-8")
    assert 'href="app.html?demo=1"' in landing and 'href="demo/"' in landing and "site/site.css?v=" in landing
    assert "app.html#/setup" in (dist / "setup.html").read_text(encoding="utf-8")


@pytest.mark.skipif(NODE is None, reason="Node isn't installed")
def test_every_app_file_parses_as_a_module(tmp_path):
    # Trial error (2026-10-23): `node --check x.js` passes a broken ES module silently, so each file is checked as .mjs.
    bad = []
    for path in (WEB / "app").rglob("*.js"):
        copy = tmp_path / (path.stem + "_" + str(abs(hash(str(path)))) + ".mjs")
        copy.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        out = subprocess.run([NODE, "--check", str(copy)], capture_output=True, text=True, timeout=30)
        if out.returncode:
            bad.append(f"{path.relative_to(WEB)}: {out.stderr.strip().splitlines()[-1] if out.stderr.strip() else ''}")
    assert bad == []
