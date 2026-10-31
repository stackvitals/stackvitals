"""Fixes from the Phase 12 review of the delivery and community numbers: each test is one verified finding."""
from datetime import datetime, timezone

from stackvitals.core import ai_outcomes, delivery

NOW = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
DEPS = [{"id": 1, "finished": "2026-07-29T10:00:00Z", "sha": "aaa"}, {"id": 2, "finished": "2026-08-15T10:00:00Z", "sha": "bbb"}]


def pr(n, merged, title="Change", mc=None):
    return {"n": n, "mg": merged, "cr": merged, "ti": title, "mc": mc, "lb": []}


def test_a_pr_merged_before_the_oldest_known_deployment_is_not_credited_to_it():
    # Review finding (pip): the oldest stored deployment absorbed 246 PRs back to 2024 (lead time 2,696 h instead of 28 h).
    assert delivery.deployment_of(pr(1, "2025-01-01T00:00:00Z"), DEPS) is None
    assert delivery.deployment_of(pr(2, "2026-08-01T00:00:00Z"), DEPS)["id"] == 2
    assert delivery.deployment_of(pr(3, "2025-01-01T00:00:00Z", mc="aaa"), DEPS)["id"] == 1  # its merge commit shipped


def test_what_a_revert_reverted_is_found_by_number_suffix_then_latest_title():
    # Review finding: exact titles missed 5 of 9 real reverts ('Revert "T (#N)"', 'Revert #N') and marked re-lands.
    prs = [pr(10, "2026-08-01T00:00:00Z", "Add cache"), pr(11, "2026-08-03T00:00:00Z", "Add cache"),
           pr(12, "2026-08-05T00:00:00Z", "Speed up (#12)")]
    by_n = {p["n"]: p for p in prs}
    assert ai_outcomes.revert_target(pr(20, "2026-08-06T00:00:00Z", 'Revert "Speed up (#12)"'), by_n) == 12
    assert ai_outcomes.revert_target(pr(21, "2026-08-06T00:00:00Z", "Revert #10"), by_n) == 10
    assert ai_outcomes.revert_target(pr(22, "2026-08-04T00:00:00Z", 'Revert "Add cache"'), by_n) == 11  # the latest before
    assert ai_outcomes.revert_target(pr(23, "2026-08-02T00:00:00Z", 'Revert "Add cache"'), by_n) == 10
    assert ai_outcomes.revert_target(pr(24, "2026-08-06T00:00:00Z", 'Revert "Something else"'), by_n) is None


def test_a_revert_shipped_in_the_same_release_as_its_original_is_not_rework():
    # Review finding (xdsl #5194): the bad change never reached users.
    original, revert = pr(30, "2026-08-10T00:00:00Z", "Risky"), pr(31, "2026-08-11T00:00:00Z", 'Revert "Risky"')
    same = [(original, {}, DEPS[1]), (revert, {}, DEPS[1])]
    incidents = [{"source": "revert", "number": 31}]
    assert ai_outcomes.rework_rate(DEPS, same, incidents, datetime(2026, 7, 1, tzinfo=timezone.utc), NOW)["rework_deployments"] == 0
    later = [(original, {}, DEPS[0]), (revert, {}, DEPS[1])]
    assert ai_outcomes.rework_rate(DEPS, later, incidents, datetime(2026, 7, 1, tzinfo=timezone.utc), NOW)["rework_deployments"] == 1


def test_a_connected_pager_never_hides_githubs_reverts_from_the_rework_rate(monkeypatch):
    # Review finding: with PagerDuty or incident.io, rework saw only pager incidents and said 0 of N.
    import sys
    sys.path.insert(0, "tests/local")
    from test_core_delivery import NOW as DNOW
    from test_core_delivery_surfaces import sample

    from stackvitals.core.config import parse
    flow, repo = sample()
    merged = [p for p in flow["closed"] if p.get("mg")]
    first = min(merged, key=lambda p: p["mg"])
    flow["closed"].append({**first, "n": 9999, "ti": f'Revert "{first.get("ti")}"', "mg": max(p["mg"] for p in merged),
                           "cr": max(p["mg"] for p in merged), "mc": None})
    plain = delivery.build(flow, repo, {"runs": [], "jobs": []}, [], DNOW, 365, parse("")[0])
    pager = [{"source": "pagerduty", "number": "P1", "created": first["mg"], "resolved": first["mg"]}]
    monkeypatch.setattr(delivery, "incidents_for", lambda *a, **k: (delivery.find_incidents([], [], a[2], a[3], extra=pager), "PagerDuty"))
    with_pager = delivery.build(flow, repo, {"runs": [], "jobs": []}, [], DNOW, 365, parse("")[0])
    assert with_pager["dora"]["rework_deployments"] == plain["dora"]["rework_deployments"]


def test_the_crawl_keeps_a_persons_ai_assisted_pr_as_theirs_like_the_app():
    # Review finding: the crawl classed any AI-tagged PR as "ai", so its bus factor and agent baseline left out people's
    # AI-assisted PRs (pytest: bus factor 6 became 5) while the app counted them.
    import duckdb

    from mergescout.signals.identity import build_pr_class
    con = duckdb.connect()
    con.execute("CREATE TABLE prs (repo_id BIGINT, number INT, author_login VARCHAR, author_type VARCHAR, ai_tag VARCHAR)")
    con.execute("CREATE TABLE people (repo_id BIGINT, login VARCHAR, kind VARCHAR)")
    con.executemany("INSERT INTO prs VALUES (?,?,?,?,?)", [(1, 1, "amy", "User", "claude"), (1, 2, "Copilot", "Bot", "copilot"),
                                                          (1, 3, "bob", "User", None), (1, 4, "renovate[bot]", "Bot", "bot")])
    con.execute("INSERT INTO people VALUES (1, 'amy', 'insider'), (1, 'bob', 'outsider'), (1, 'renovate[bot]', 'bot')")
    build_pr_class(con)
    got = dict(con.execute("SELECT author_login, author_role FROM pr_class").fetchall())
    assert got == {"amy": "insider", "Copilot": "agent", "bob": "outsider", "renovate[bot]": "bot"}


def test_backports_to_release_branches_are_not_counted_again():
    # Review finding (aiohttp): 169 of 417 counted PRs were backports to 3.13, 3.14 and 3.15.
    from stackvitals.core.investment import mix
    prs = [{"n": 1, "ti": "Fix crash", "lb": [], "paths": [], "mg": "2026-10-02T00:00:00Z", "au": "amy", "at": "User", "base": "master"},
           {"n": 2, "ti": "[3.14] Fix crash", "lb": [], "paths": [], "mg": "2026-10-03T00:00:00Z", "au": "amy", "at": "User",
            "base": "3.14"}]
    assert mix(prs, NOW, base="master")["n"] == 1 and mix(prs, NOW)["n"] == 2


def test_release_notes_prs_are_maintenance_and_a_title_prefix_beats_fragments():
    # Review finding: pytest "Cherry pick 9.1.0 release notes" (50 fragments of 5 kinds) and pip "doc: Reword news
    # entries" became fixes.
    from stackvitals.core.investment import classify
    many = [f"changelog/{i}.{k}.rst" for i, k in enumerate(["bugfix", "feature", "doc", "removal", "improvement"] * 10)]
    assert classify({"ti": "Cherry pick 9.1.0 release notes", "lb": [], "paths": many}) == \
        ("maintenance", "changelog fragments of several kinds")
    assert classify({"ti": "doc: Reword news entries", "lb": [], "paths": ["news/1.bugfix.rst", "news/2.feature.rst"]})[0] == "docs"
    assert classify({"ti": "Fix broken pipe", "lb": [], "paths": ["src/x.py", "news/11608.bugfix.rst"]})[0] == "fix"


def test_the_ai_window_is_six_calendar_months_with_one_start_and_small_sides_say_not_enough():
    # Review finding: going back 31x5 days from the 1st landed in April (seven buckets), stats started Apr 21, the merge
    # rate Apr 1; and n=2 still showed "Review P75 591 h".
    def row(n, merged, ai=False):
        p = {"n": n, "mg": merged, "cr": merged, "ti": "x", "ai": ["claude"] if ai else [], "lb": [], "add": 1, "del": 0}
        return (p, {"pickup": 1.0, "review": 2.0}, None)
    rows = [row(i, f"2026-{m:02d}-21T00:00:00Z") for i, m in enumerate([4, 5, 6, 7, 8, 9, 10] * 3)]
    rows += [row(100 + i, "2026-10-02T00:00:00Z", ai=True) for i in range(2)]
    decided = [r[0] for r in rows] + [{"n": 999, "st": "CLOSED", "cl": "2026-04-25T00:00:00Z", "ai": [], "lb": []}]
    out = ai_outcomes.outcomes(rows, {"runs": []}, [], NOW, decided=decided)
    assert [m["month"] for m in out["monthly"]] == ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
    assert out["window"]["others"]["n"] == 18 and out["window"]["others"]["merge_rate_n"] == 18  # April left out
    assert out["window"]["assisted"]["n"] == 2 and out["window"]["assisted"]["review_p75_h"] is None
    assert out["window"]["assisted"]["merge_rate"] is None and out["window"]["others"]["review_p75_h"] == 2.0


def test_queue_removals_need_every_failed_job_flaky_and_reruns_are_one_run():
    # Review finding: a real lint failure next to a flaky CI job was called "taken out by a flaky job", and a re-run
    # counted as a second run.
    from stackvitals.core.merge_queue import health
    pr_ = {"n": 2, "mg": None, "base": "main", "mq": [["add", "2026-10-11T10:00:00Z"], ["rm", "2026-10-11T10:40:00Z", "failed_checks"]]}
    runs = [{"id": 50, "att": 1, "ev": "merge_group", "br": "gh-readonly-queue/main/pr-2-abc", "c": "failure", "cr": "2026-10-11T10:05:00Z", "path": "ci.yml"},
            {"id": 50, "att": 2, "ev": "merge_group", "br": "gh-readonly-queue/main/pr-2-abc", "c": "failure", "cr": "2026-10-11T10:05:00Z", "path": "ci.yml"},
            {"id": 51, "att": 1, "ev": "merge_group", "br": "gh-readonly-queue/main/pr-2-abc", "c": "failure", "cr": "2026-10-11T10:05:30Z", "path": "lint.yml"}]
    jobs = [{"run": 50, "att": 2, "n": "e2e", "c": "failure"}, {"run": 51, "att": 1, "n": "lint", "c": "failure"}]
    states = {("ci.yml", "e2e"): "flaky", ("lint.yml", "lint"): "ok"}
    out = health([pr_], {"runs": runs, "jobs": jobs}, states, NOW, 30)
    assert (out["runs"], out["failed_runs"]) == (2, 2) and out["removed_by_flakes"] == []
    only_flaky = health([pr_], {"runs": runs[:2], "jobs": jobs[:1]}, states, NOW, 30)
    assert [x["jobs"] for x in only_flaky["removed_by_flakes"]] == [["e2e"]]


def test_queue_and_tracker_times_need_ten_items():
    from stackvitals.connectors.tracker import _stats
    from stackvitals.core.merge_queue import health
    prs = [{"n": i, "mg": "2026-10-12T12:00:00Z", "mq": [["add", "2026-10-12T10:00:00Z"]]} for i in range(3)]
    out = health(prs, {"runs": [], "jobs": []}, {}, NOW, 30)
    assert out["merged"] == 3 and out["p50_h"] is None and out["p90_h"] is None
    assert _stats([1.0, 2.0, 3.0], "lead") == {"lead_n": 3, "lead_p50_h": None, "lead_p75_h": None}


def test_a_pager_alone_shows_no_issues_and_sprints_section():
    # Review finding: with only PagerDuty connected, an "Issues and sprints" tab said "Issues read 1 from pagerduty".
    out = delivery._tracker({"sources": ["pagerduty"], "issues": [{"key": "P1", "incident": True, "created": "2026-10-01T00:00:00Z"}],
                             "changes": [], "sprints": []}, [], NOW, 90)
    assert out is None
