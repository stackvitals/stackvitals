"""Every app URL carries one version made from the files' contents, so a browser that cached the last release never
mixes old and new modules (Pages caches for 10 minutes), while a quiet run still writes nothing."""
import re

from stackvitals.core import webapp


def versions(text):
    return set(re.findall(r"\?v=([0-9a-f]+)", text))


def test_every_module_url_carries_the_same_version(tmp_path):
    webapp.write_webapp(tmp_path)
    page = (tmp_path / "index.html").read_text(encoding="utf-8")
    main = (tmp_path / "app" / "main.js").read_text(encoding="utf-8")
    ci = (tmp_path / "app" / "pages" / "ci.js").read_text(encoding="utf-8")
    assert re.search(r'src="app/main\.js\?v=[0-9a-f]{10}"', page) and re.search(r'href="app/main\.css\?v=', page)
    assert re.search(r'src="app/boot\.js\?v=', page) and re.search(r'rel="modulepreload" href="app/chunks/[^"]+\?v=', page)
    assert re.search(r'from"\./chunks/[^"]+\.js\?v=', main) and re.search(r'import\("\./pages/ci\.js\?v=', main)
    assert re.search(r'import"\.\./chunks/[^"]+\.js\?v=', ci)  # side-effect imports too
    assert len(versions(page) | versions(main) | versions(ci)) == 1
    assert webapp.write_webapp(tmp_path) == []  # a quiet run writes nothing


def test_a_changed_file_changes_the_version_everywhere(tmp_path, monkeypatch):
    webapp.write_webapp(tmp_path)
    before = versions((tmp_path / "index.html").read_text(encoding="utf-8"))
    real = webapp.files
    monkeypatch.setattr(webapp, "files", lambda: {**real(), "app/pages/ci.js": real()["app/pages/ci.js"] + b"\n// changed\n"})
    changed = webapp.write_webapp(tmp_path)
    assert "index.html" in changed and "app/main.js" in changed
    assert versions((tmp_path / "index.html").read_text(encoding="utf-8")) != before


def test_binary_files_are_written_byte_for_byte_and_fonts_keep_their_plain_url():
    font = b"wOF2\x00\r\n\x01\x02\r\n"
    out = webapp.stamped({"app/fonts/x.woff2": font, "app/a.js": b'import x from "./b.js";\r\n',
                          "index.html": b'<link rel="preload" href="app/fonts/x.woff2"><script src="app/a.js"></script>'})
    assert out["app/fonts/x.woff2"] == font and b"\r\n" not in out["app/a.js"]
    assert b'href="app/fonts/x.woff2"' in out["index.html"] and b'src="app/a.js?v=' in out["index.html"]
