"""The project site (landing page, the app at app.html, forwards from the earlier setup and integrations pages, an
optional real-data demo) is built from the package, and its files never reach a user's Pages."""
import json
import re

from stackvitals.core import webapp


def test_the_app_copied_to_a_repo_never_carries_the_site():
    assert not [n for n in webapp.files() if n.startswith("site/") or n in ("setup.html", "integrations.html")]
    assert {"index.html", "setup.html", "integrations.html", "site/site.css"} == set(webapp.site_files())


def test_every_page_of_the_site_links_versioned_files():
    out = webapp.stamped({"index.html": b'<link rel="stylesheet" href="site/site.css">', "site/site.css": b"body{}",
                          "app.html": b'<script type="module" src="app/main.js"></script>', "app/main.js": b'import"./x.js";'})
    versions = {v for body in out.values() for v in re.findall(rb"\?v=([0-9a-f]+)", body)}
    assert len(versions) == 1 and b"site/site.css?v=" in out["index.html"] and b'import"./x.js?v=' in out["app/main.js"]


def test_a_built_site_has_the_landing_the_app_and_the_demos(tmp_path):
    from stackvitals.site import build, main
    demo = tmp_path / "demo-docs"
    demo.mkdir()
    (demo / "app.json").write_text(json.dumps({"repo": "o/r", "modules": {}}), encoding="utf-8")
    build(tmp_path / "dist", demo=demo)
    dist = tmp_path / "dist"
    assert (dist / "app.html").exists() and (dist / "app" / "main.js").exists() and (dist / "app" / "demo" / "mobile" / "app.json").exists()
    assert (dist / "demo" / "index.html").exists() and (dist / "demo" / "app.json").exists()
    assert 'src="app/main.js?v=' in (dist / "app.html").read_text(encoding="utf-8")
    # Without a real-data demo, the landing links only the app's own demo.
    assert main(["build", "--out", str(tmp_path / "plain")]) == 0
    landing = (tmp_path / "plain" / "index.html").read_text(encoding="utf-8")
    assert "app.html?demo=1" in landing and 'href="demo/"' not in landing and "<!--REAL-DEMO-->" not in landing
