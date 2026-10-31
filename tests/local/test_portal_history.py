import json
from datetime import datetime, timezone

from test_portal_m1 import NOW, fake


def write_history(folder, days):
    folder.mkdir(parents=True, exist_ok=True)
    for day, rows in days.items():
        (folder / f"{day}.json").write_text(json.dumps({"repos": rows}), encoding="utf-8")


def test_since_when_comes_from_the_unbroken_run_of_daily_history(tmp_path):
    from stackvitals.portal.history import since
    write_history(tmp_path, {"2026-10-16": [{"name": "acme/api", "owners": "valid", "level": "silver"}],
                             "2026-10-17": [{"name": "acme/api", "owners": "weak", "level": "bronze"}],
                             "2026-10-18": [{"name": "acme/api", "owners": "weak", "level": "bronze"}]})
    current = [{"name": "acme/api", "owners": {"status": "weak"}, "score": {"level": "bronze"}},
               {"name": "acme/new", "owners": {"status": "none"}, "score": {"level": None}}]
    got = since(tmp_path, current, "2026-10-19")
    assert got["acme/api"] == {"owners": "2026-10-17", "level": "2026-10-17"}
    assert got["acme/new"] == {"owners": "2026-10-19", "level": "2026-10-19"}  # first seen today


def test_the_page_says_since_when_a_repo_has_been_weak():
    from stackvitals.portal.pages import render_catalog
    c = {"org": "acme", "built_at": "2026-10-19T12:00:00Z", "complete": True,
         "repos": [{"name": "acme/api", "owners": {"status": "weak", "reasons": ["team acme/core has no members"]},
                    "since": {"owners": "2026-10-17", "level": "2026-10-17"}, "score": {"level": "bronze", "results": []}}]}
    page = render_catalog(c, destination_private=True)
    assert "weak since 2026-10-17" in page and "bronze since 2026-10-17" in page


def catalog_routes():
    catalog = {"org": "acme", "built_at": "2026-10-19T12:00:00Z", "complete": True, "repos": [
        {"name": "acme/api", "owners": {"status": "weak", "reasons": ["bob is named as an owner but is not a member of acme"]},
         "score": {"level": None, "results": [{"id": "codeowners", "level": "bronze", "result": "pass", "evidence": "CODEOWNERS at CODEOWNERS"},
                                              {"id": "reviews-required", "level": "bronze", "result": "fail",
                                               "evidence": "no pull_request rule on the default branch"}]}},
        {"name": "acme/web", "owners": {"status": "valid", "reasons": []},
         "score": {"level": "bronze", "results": [{"id": "codeowners", "level": "bronze", "result": "pass", "evidence": "x"}]}}]}
    return {"/repos/acme/portal/contents/portal/catalog.json": (200, json.dumps(catalog))}


def test_agents_read_the_orgs_published_catalog_for_levels_scorecards_and_owners(tmp_path):
    from test_ci_mcp import NoRel, mcp_call

    from mergescout.mcp_server import App
    from stackvitals.mcp_server import build_server
    app = App(root=tmp_path / "h", releases=NoRel(), live=None, log=lambda *a: None)
    server = build_server(app, ci_api=fake(catalog_routes()), ci_home=tmp_path / "sv", ci_token="tok")
    org = mcp_call(server, "org_catalog", {"org": "acme"})
    assert org["source"] == "acme/portal stackvitals-data branch" and org["levels"] == {"gold": 0, "silver": 0, "bronze": 1, "below bronze": 1}
    assert org["most_failed_rules"] == [{"rule": "reviews-required", "repos": 1}]
    card = mcp_call(server, "repo_scorecard", {"repo": "acme/api"})
    assert card["level"] is None and card["failing"] == [{"rule": "reviews-required", "evidence": "no pull_request rule on the default branch"}]
    owners = mcp_call(server, "owners_health", {"org": "acme"})
    assert owners["counts"] == {"valid": 1, "weak": 1, "none": 0} and owners["weak"][0]["repo"] == "acme/api"
