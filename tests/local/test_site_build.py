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


def test_a_demo_only_site_can_reach_nothing_but_its_own_files(tmp_path):
    # The public demo on GitHub Pages: no outside calls, no token box, setup points at the README.
    from stackvitals.site import README_SETUP, main
    assert main(["build", "--out", str(tmp_path / "pub"), "--demo-only"]) == 0
    pub = tmp_path / "pub"
    for page in pub.glob("*.html"):
        policy = re.search(r'Content-Security-Policy" content="([^"]*)', page.read_text(encoding="utf-8")).group(1)
        connect = re.search(r"connect-src ([^;]*)", policy)
        assert connect is None or connect.group(1) in ("'self'", "'none'"), page.name
        assert "https://" not in policy, page.name
    landing = (pub / "index.html").read_text(encoding="utf-8")
    assert "app.html#/setup" not in landing and landing.count(README_SETUP) == 4
    assert README_SETUP in (pub / "setup.html").read_text(encoding="utf-8")
    assert "app.html?demo=1" in landing
    # The ordinary build keeps the app able to read a user's own repo.
    main(["build", "--out", str(tmp_path / "full")])
    assert "https://api.github.com" in (tmp_path / "full" / "app.html").read_text(encoding="utf-8")


def test_every_file_the_landing_pages_name_is_in_the_built_site(tmp_path):
    # The landing once named a font the app had stopped shipping; Pages answered 404.
    from stackvitals.site import main
    main(["build", "--out", str(tmp_path / "s"), "--demo-only"])
    site = tmp_path / "s"
    css = (site / "site" / "site.css").read_text(encoding="utf-8")
    for ref in re.findall(r'url\("?([^")]+)"?\)', css):
        assert (site / "site" / ref).resolve().exists(), ref
    for page in ("index.html", "setup.html", "integrations.html"):
        for ref in re.findall(r'(?:href|src)="([^"#?:]+)(?=[?#"])', (site / page).read_text(encoding="utf-8")):
            assert (site / ref).exists(), f"{page}: {ref}"
