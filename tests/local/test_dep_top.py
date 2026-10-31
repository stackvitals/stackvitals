import json
from datetime import datetime, timezone

import duckdb

from mergescout.signals.top_packages import fetch_top

NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)


def pages(lists):
    def get_json(url):
        from urllib.parse import parse_qs, urlparse
        registry = url.split("/registries/")[1].split("/")[0]
        page = int(parse_qs(urlparse(url).query)["page"][0])
        rows = lists.get(registry, [])
        if rows == "boom":
            raise OSError("reset")
        return [{"name": n} for n in rows[(page - 1) * 100: page * 100]]
    return get_json


def test_the_top_lists_come_page_by_page_with_registry_names_normalised():
    npm = [f"pkg-{i}" for i in range(250)] + ["https://not/a/name"]
    got = fetch_top(300, pages({"npmjs.org": npm, "pypi.org": ["Requests", "typing_extensions"]}))
    assert got[:2] == [("npm", "pkg-0"), ("npm", "pkg-1")] and len([g for g in got if g[0] == "npm"]) == 250
    assert ("pypi", "requests") in got and ("pypi", "typing-extensions") in got


def test_a_failed_registry_list_does_not_stop_the_other():
    got = fetch_top(200, pages({"npmjs.org": "boom", "pypi.org": ["six"]}))
    assert got == [("pypi", "six")]


def test_the_daily_map_adds_the_top_packages_and_keeps_yesterdays_list_when_the_download_fails(tmp_path, monkeypatch):
    import mergescout.signals.deps_map as dm
    import mergescout.signals.top_packages as tp
    from mergescout.snapshot.__main__ import write_package_map
    con = duckdb.connect()
    con.execute("CREATE TABLE bump_ledger (ecosystem VARCHAR, package VARCHAR, prs INT)")
    con.execute("INSERT INTO bump_ledger VALUES ('pypi', 'django', 500)")
    asked = []

    def refresh(packages, previous, now, **kw):
        asked.append(list(packages))
        return {f"{e}:{n}": {**previous.get(f"{e}:{n}", {}), "ecosystem": e, "package": n, "repo": None, "link": None}
                for e, n in packages}
    monkeypatch.setattr(dm, "refresh_map", refresh)
    monkeypatch.setattr(tp, "fetch_top", lambda *a, **k: [("npm", "lodash"), ("pypi", "django")])
    write_package_map(con, tmp_path, NOW, log=lambda s: None)
    mapped = json.loads((tmp_path / "deps-map.json").read_text(encoding="utf-8"))["packages"]
    assert asked[0] == [("pypi", "django"), ("npm", "lodash")]  # the ledger's packages first, then the top list
    assert mapped["npm:lodash"]["top"] is True and mapped["pypi:django"]["top"] is True
    monkeypatch.setattr(tp, "fetch_top", lambda *a, **k: [])
    write_package_map(con, tmp_path, NOW, log=lambda s: None)
    assert ("npm", "lodash") in asked[1]
