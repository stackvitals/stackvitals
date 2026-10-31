"""Cross-module findings: each one a plain sentence with its number, n, links to the evidence and what to do, ranked by
the hours of waiting or outage at stake; public pages never name a reviewer."""
from datetime import datetime, timezone

from stackvitals.core import findings

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
REPO = "o/r"


def red_ci():
    return {"prs": 40, "red_prs": 6, "red_hours_total": 50.0, "rerun_hours_total": 30.0,
            "measures": {"insight.red_ci_share": {"low": 0.07, "high": 0.29}},
            "rerun_jobs": [{"workflow": "CI", "job": "tests (3.12)", "hours": 21.5, "prs": 4,
                            "runs": [[101, 1], [102, 2]]},
                           {"workflow": "CI", "job": "lint", "hours": 0.4, "prs": 1, "runs": [[103, 1]]}],
            "rerun_tests": [{"test": "tests/test_net.py::test_fetch", "hours": 18.0, "prs": 3}],
            "top": [{"pr": 7, "hours": 20.0, "waits": []}]}


def delivery():
    return {"stuck": {"hanging_review": [{"pr": 11, "since": "2026-10-10T00:00:00Z", "hours": 252.0},
                                         {"pr": 12, "since": "2026-10-15T00:00:00Z", "hours": 132.0}],
                      "long_lived": [], "high_interaction": [], "red_and_idle": []},
            "incidents": [{"source": "revert", "number": 30, "created": "2026-10-01T10:00:00Z", "resolved": "2026-10-01T16:00:00Z",
                           "deployment": "release:v2.0", "deployment_finished": "2026-10-01T08:00:00Z", "hours_to_restore": 8.0}]}


def flow():
    return {"groups": {"insider": {"pickup": {"median_s": 2 * 3600, "p90_s": 9 * 3600, "n": 30}},
                       "outsider": {"pickup": {"median_s": 30 * 3600, "p90_s": 80 * 3600, "n": 12}}},
            "load": [{"reviewer": "bob", "open_requests": 4}]}


BUMPS = [{"pr": 50, "title": "Bump requests from 2.31.0 to 2.32.0", "package": "requests", "to": "2.32.0", "hours": 40.0,
          "state": "open"},
         {"pr": 51, "title": "Bump idna from 3.6 to 3.7", "package": "idna", "to": "3.7", "hours": 2.0, "state": "merged"}]


def test_findings_rank_by_hours_and_carry_n_evidence_and_an_action():
    out = findings.build(REPO, red_ci=red_ci(), delivery=delivery(), flow=flow(), bumps=BUMPS, now=NOW)
    kinds = [f["kind"] for f in out]
    assert kinds[0] == "review_wait"  # 384 hours of asked-for reviews not started outrank the rest
    assert {"red_ci", "fix_job", "fix_test", "incident", "outsider_wait", "bump_red"} <= set(kinds)
    for f in out:
        assert f["title"] and f["n"] is not None and f["evidence"] and f["hours"] >= 0
    fix = next(f for f in out if f["kind"] == "fix_job")
    assert "CI / tests (3.12)" in fix["title"] and "21.5 h" in fix["title"] and fix["n"] == 4
    assert fix["evidence"][0]["url"] == "https://github.com/o/r/actions/runs/101/attempts/1"
    assert "quarantine" in fix["action"].lower()
    assert not any(f["kind"] == "fix_job" and "lint" in f["title"] for f in out)  # under an hour and one PR: noise


def test_public_findings_never_name_a_reviewer_and_escape_nothing_unsafe():
    out = findings.build(REPO, red_ci=red_ci(), delivery=delivery(), flow=flow(), bumps=BUMPS, now=NOW)
    text = " ".join(f["title"] + " " + (f["action"] or "") for f in out)
    assert "bob" not in text and "@" not in text


def test_small_groups_and_missing_modules_give_no_finding():
    tiny = {"groups": {"insider": {"pickup": {"median_s": 3600, "n": 3}}, "outsider": {"pickup": {"median_s": 99 * 3600, "n": 2}}}}
    out = findings.build(REPO, red_ci=None, delivery=None, flow=tiny, bumps=[], now=NOW)
    assert out == []


def test_the_page_lists_findings_with_links_and_the_summary_leads_with_the_top_three():
    out = findings.build(REPO, red_ci=red_ci(), delivery=delivery(), flow=flow(), bumps=BUMPS, now=NOW)
    page = findings.render_html(out, REPO, NOW)
    assert "https://github.com/o/r/pull/11" in page and "n=" in page
    md = findings.render_markdown(out, REPO)
    assert md.count("\n1. ") + md.count("\n2. ") + md.count("\n3. ") == 3 and "\n4. " not in md


def test_review_requests_split_into_waiting_now_and_stale_with_hours_capped_at_the_window():
    d = {"window_days": 90, "incidents": [],
         "stuck": {"hanging_review": [{"pr": 1, "since": "2026-10-15T12:00:00Z", "hours": 120.0},
                                      {"pr": 2, "since": "2025-01-01T00:00:00Z", "hours": 15000.0},
                                      {"pr": 3, "since": "2026-08-01T00:00:00Z", "hours": 1932.0}]}}
    out = {f["kind"]: f for f in findings.build(REPO, red_ci=None, delivery=d, flow=None, bumps=[], now=NOW)}
    assert out["review_wait"]["n"] == 1 and out["review_wait"]["hours"] == 120.0
    stale = out["stale_review"]
    assert stale["n"] == 2 and stale["hours"] == 90 * 24 + 1932.0  # one request older than the window counts 90 days
    assert "since 2025-01-01" in stale["title"] and "close" in stale["action"].lower()
    assert "days in all" not in stale["title"]


def test_a_failing_dependency_update_is_compared_with_the_same_update_across_the_crawl():
    bumps = [{"pr": 50, "package": "requests", "to": "2.32.0", "ecosystem": "pip", "bump": "minor", "hours": 40.0, "state": "open"},
             {"pr": 51, "package": "idna", "to": "3.7", "ecosystem": "pip", "bump": "minor", "hours": 6.0, "state": "merged"}]
    ledger = {"pip:requests": [{"bump": "minor", "prs": 140, "repos": 120, "ci_known": 130, "ci_failed": 53, "expected_failed": 12.0}],
              "pip:idna": [{"bump": "minor", "prs": 90, "repos": 70, "ci_known": 80, "ci_failed": 8, "expected_failed": 7.5}]}
    out = {f["kind"]: f for f in findings.build(REPO, red_ci=None, delivery=None, flow=None, bumps=bumps, now=NOW, ledger=ledger)}
    text = out["bump_red"]["title"] + " " + out["bump_red"]["action"]
    assert "across 120 crawled repos, requests 2.32.0 failed CI in 41% of 130 checked pull requests (their other updates fail 9%)" in text
    assert "likely the update itself" in text and "idna" in text
    plain = findings.build(REPO, red_ci=None, delivery=None, flow=None, bumps=bumps, now=NOW)
    assert "crawled" not in plain[0]["title"]


def test_an_update_that_fails_no_more_than_usual_points_back_at_the_repos_own_checks():
    bumps = [{"pr": 50, "package": "actions/stale", "to": "11.0.0", "ecosystem": "actions", "bump": "major", "hours": 40.0,
              "state": "merged"}]
    ledger = {"actions:actions/stale": [{"bump": "major", "prs": 199, "repos": 184, "ci_known": 182, "ci_failed": 44,
                                         "expected_failed": 44.53}]}
    f = findings.build(REPO, red_ci=None, delivery=None, flow=None, bumps=bumps, now=NOW, ledger=ledger)[0]
    assert "no more often than other updates" in f["action"] and "24%" in f["title"]
