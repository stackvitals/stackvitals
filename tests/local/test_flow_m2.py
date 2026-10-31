from datetime import datetime, timedelta, timezone

from stackvitals.flow.knowledge import area, backtest, codeowners_for, delivery, expertise, knowledge_map, suggest_reviewers

NOW = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)


def at(days):
    return (NOW - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def merged(n, au, paths, days, reviewers=(), assoc="MEMBER", title="Change", head="feat", add=10):
    ev = [["review", at(days + 0.5), r, "APPROVED", "MEMBER", "User"] for r in reviewers] + [["merged", at(days), "x"]]
    return {"t": "pr", "n": n, "ti": title, "st": "MERGED", "cr": at(days + 1), "mg": at(days), "cl": at(days), "au": au,
            "at": "User", "as": assoc, "rq": [], "ev": ev, "cm": [], "paths": list(paths), "add": add, "del": 0,
            "head": head}


def test_paths_map_to_areas_two_folders_deep():
    assert area("src/db/pool.py") == "src/db" and area("docs/index.md") == "docs" and area("README.md") == "(root)"


def history():
    out = [merged(k, "dana", ["src/db/pool.py"], 10 + k, reviewers=["erin"]) for k in range(6)]
    out += [merged(20 + k, "frank", ["src/web/app.py"], 20 + k, reviewers=["dana"]) for k in range(3)]
    out += [merged(30, "gina", ["src/db/x.py"], 300)]
    return out


def test_expertise_comes_from_recent_authors_and_reviewers_of_each_area():
    ex = expertise(history(), NOW)
    top = sorted(ex["src/db"].items(), key=lambda kv: -kv[1])
    assert top[0][0] == "dana" and dict(top)["erin"] > dict(top).get("gina", 0)


def test_suggestions_skip_the_author_and_weigh_current_load():
    ex = expertise(history(), NOW)
    pr = {"n": 99, "au": "dana", "paths": ["src/db/new.py"]}
    s = suggest_reviewers(pr, ex, load={}, owners={})
    assert [x["login"] for x in s][0] == "erin" and all(x["login"] != "dana" for x in s)
    busy = suggest_reviewers({"n": 98, "au": "zed", "paths": ["src/db/new.py"]}, ex, load={"dana": 12}, owners={})
    assert busy[0]["login"] == "erin" and "12 open" in busy[1]["why"]
    fast = suggest_reviewers({"n": 97, "au": "zed", "paths": ["src/db/new.py"]}, ex, load={}, owners={},
                             speed={"erin": 3600, "dana": 9 * 86400})
    assert fast[0]["login"] == "erin" and "answers in" in fast[0]["why"]
    assert "answers in" not in suggest_reviewers({"n": 96, "au": "zed", "paths": ["src/db/a.py"]}, ex, {}, {})[0]["why"]


def test_codeowners_are_matched_last_rule_wins_and_boost_a_suggestion():
    text = "* @root-team\n/src/db/ @erin\n*.md @docs-team\n"
    assert codeowners_for("src/db/pool.py", text) == ["erin"] and codeowners_for("README.md", text) == ["docs-team"]
    assert codeowners_for("src/web/a.py", text) == ["root-team"]
    ex = expertise(history(), NOW)
    s = suggest_reviewers({"n": 9, "au": "zed", "paths": ["src/web/a.py"]}, ex, load={}, owners={"src/web/a.py": ["dana"]})
    # Code owners are named and nudged, but history of who actually works there still leads.
    assert s[0]["login"] == "frank" and "code owner" in next(x for x in s if x["login"] == "dana")["why"]


def test_knowledge_map_finds_one_person_areas_quiet_owners_and_hotspots():
    km = knowledge_map(history(), NOW)
    db = next(a for a in km["areas"] if a["area"] == "src/db")
    assert db["owner"] == "dana" and db["single_owner"] and db["prs"] == 7
    old = [merged(40 + k, "hal", ["lib/old/a.py"], 200 + k) for k in range(4)]
    quiet = next(a for a in knowledge_map(history() + old, NOW)["areas"] if a["area"] == "lib/old")
    assert quiet["owner_quiet_days"] >= 200
    assert km["hotspots"][0]["area"] == "src/db"


def test_delivery_counts_releases_lead_time_and_reverts_as_a_labelled_proxy():
    rel = [{"tag": f"v1.{k}", "at": at(60 - 7 * k), "pre": False} for k in range(8)]
    prs = [merged(1, "dana", ["a"], 56), merged(2, "dana", ["a"], 30),
           merged(3, "dana", ["a"], 28.5, title='Revert "Change"', head="revert-2-feat")]
    d = delivery(prs, rel, NOW, window_days=90)
    assert d["source"] == "releases" and d["releases"] == 8 and round(d["per_week"], 2) == round(8 / (90 / 7), 2)
    assert d["lead_time_median_s"] is not None and d["change_fail"]["failed"] == 1 and d["change_fail"]["proxy"]


def test_backtest_asks_if_the_top_three_included_a_real_reviewer():
    prs = history() + [merged(50, "zed", ["src/db/q.py"], 2, reviewers=["erin"]),
                       merged(51, "zed", ["src/web/q.py"], 1, reviewers=["quinn"])]
    out = backtest(prs, NOW, last=2)
    assert out["checked"] == 2 and out["hits"] == 1


def test_build_adds_suggestions_where_nobody_was_asked_plus_knowledge_and_delivery():
    from stackvitals.flow.build import build
    waiting = {"t": "pr", "n": 99, "ti": "New pool", "draft": False, "st": "OPEN", "cr": at(3), "up": at(1), "mg": None,
               "cl": None, "au": "zed", "at": "User", "as": "NONE", "rq": [], "ev": [], "cm": [], "ci": "SUCCESS",
               "lc": at(3), "paths": ["src/db/new.py"]}
    repo = {"releases": [{"tag": "v1", "at": at(5), "pre": False}], "codeowners": None}
    public = build({"open": [waiting], "closed": history()}, repo, NOW, owner="o")
    q = public["queue"][0]
    assert q["suggested"][0]["login"] == "dana" and "answers in" not in q["suggested"][0]["why"]
    assert public["knowledge"]["areas"][0]["area"] == "src/db" and public["delivery"]["releases"] == 1
    private = build({"open": [waiting], "closed": history()}, repo, NOW, owner="o", people_speed=True)
    assert "responders" in private and "responders" not in public


def test_only_people_who_can_review_are_suggested_and_lock_files_are_not_areas():
    # Real findings: poetry suggested outside contributors; uv's "busiest area" was its lock files.
    prs = history() + [merged(60 + k, "visitor", ["src/db/y.py"], 5 + k, assoc="NONE") for k in range(5)]
    ex = expertise(prs, NOW)
    picks = [s["login"] for s in suggest_reviewers({"n": 1, "au": "zed", "paths": ["src/db/z.py"]}, ex, {}, {})]
    assert "visitor" not in picks and picks[0] == "dana"
    locky = [merged(80 + k, "dana", ["Cargo.lock", "uv.lock"], 3 + k, add=50000) for k in range(5)]
    km = knowledge_map(history() + locky, NOW)
    assert all(a["area"] != "(root)" for a in km["areas"]) and km["hotspots"][0]["area"] == "src/db"
