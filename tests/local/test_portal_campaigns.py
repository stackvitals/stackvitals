import json
from datetime import datetime, timezone

NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)
TOML = """
[[rule]]
id = "codeowners"
check = "owners_present"
level = "bronze"

[[campaign]]
id = "owners-everywhere"
title = "Every active Go repo has a CODEOWNERS file"
rules = ["codeowners"]
repos = "acme/*"
language = "Go"
until = "2026-12-31"
"""


def scored(name, fails, language="Go"):
    return {"name": name, "language": language, "checked": "x",
            "score": {"level": None if fails else "bronze",
                      "results": [{"id": "codeowners", "level": "bronze", "result": "fail" if fails else "pass", "evidence": "e"}]}}


def test_campaigns_load_with_their_filters_and_target_date():
    from stackvitals.portal.campaigns import load_campaigns
    c = load_campaigns(TOML)
    assert c == [{"id": "owners-everywhere", "title": "Every active Go repo has a CODEOWNERS file", "rules": ["codeowners"],
                  "repos": "acme/*", "language": "Go", "until": "2026-12-31"}]


def test_progress_counts_target_repos_and_lists_who_still_fails(tmp_path):
    from stackvitals.portal.campaigns import load_campaigns, progress
    repos = [scored("acme/api", fails=False), scored("acme/web", fails=True), scored("acme/cli", fails=True),
             scored("acme/site", fails=True, language="JavaScript"), scored("other/x", fails=True)]
    p = progress(load_campaigns(TOML)[0], repos, tmp_path, NOW)
    assert (p["targets"], p["passing"]) == (3, 1) and p["failing"] == ["acme/cli", "acme/web"] and p["days_left"] == 73


def test_the_burn_down_comes_from_the_daily_history(tmp_path):
    from stackvitals.portal.campaigns import load_campaigns, progress
    for day, failing in (("2026-10-01", ["acme/api", "acme/web", "acme/cli"]), ("2026-10-10", ["acme/web", "acme/cli"])):
        rows = [{"name": n, "failed": ["codeowners"] if n in failing else [], "language": "Go"} for n in ("acme/api", "acme/web", "acme/cli")]
        (tmp_path / f"{day}.json").write_text(json.dumps({"repos": rows}), encoding="utf-8")
    repos = [scored("acme/api", False), scored("acme/web", True), scored("acme/cli", False)]
    p = progress(load_campaigns(TOML)[0], repos, tmp_path, NOW)
    assert p["burn_down"] == [["2026-10-01", 3], ["2026-10-10", 2], ["2026-10-19", 1]]


def test_the_tracking_issue_is_one_issue_in_the_portal_repo_edited_in_place():
    from test_portal_m1 import fake

    from stackvitals.portal.campaigns import MARKER, update_tracking_issue
    posted = []
    routes = {"/repos/acme/portal/issues": (200, [{"number": 7, "body": f"{MARKER} owners-everywhere -->\nold",
                                                  "pull_request": None}])}

    def capture(token, repo, **kw):
        api = fake(routes)(token, repo, **kw)
        real = api.send
        api.send = lambda method, path, body=None: (posted.append((method, path, body)), {"number": 7})[1]
        return api
    p = {"id": "owners-everywhere", "title": "T", "rules": ["codeowners"], "targets": 3, "passing": 1, "failing": ["acme/web"],
         "until": "2026-12-31",
         "days_left": 73, "burn_down": [["2026-10-19", 2]]}
    update_tracking_issue(capture("t", "acme/portal"), "acme/portal", p)
    assert posted[0][0] == "PATCH" and posted[0][1] == "/repos/acme/portal/issues/7" and "acme/web" in posted[0][2]["body"]
    posted.clear()
    routes["/repos/acme/portal/issues"] = (200, [])
    update_tracking_issue(capture("t", "acme/portal"), "acme/portal", p)
    assert posted[0][0] == "POST" and posted[0][2]["title"].startswith("Campaign: T")
