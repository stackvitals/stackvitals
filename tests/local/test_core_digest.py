"""The weekly digest: what changed since last week in each module that ran, what to fix first, and decisions whose
review date is near, as one short message. Nobody is pinged, item names can't break the Markdown, and a module that
didn't run is simply left out."""
from datetime import datetime, timezone

from stackvitals.core.digest import compose, due

NOW = datetime(2026, 10, 26, 7, tzinfo=timezone.utc)

DOCS = {
    "data": {"pushes": {"first_try_share": 0.80, "pushes": 40},
             "changes": [{"metric": "ci.first_try_green", "label": "pushes green on the first try", "now": 0.6, "base": 0.9,
                          "n_now": 20, "n_base": 80, "p": 0.001, "direction": "down", "unit": "share"},
                         {"metric": "ci.push_wait", "label": "push to all checks done", "now": 9.0, "base": 8.0,
                          "n_now": 20, "n_base": 80, "p": 0.4, "direction": "up", "unit": "min"},
                         {"metric": "ci.flake_share", "label": "job runs that flaked", "now": 0.02, "base": 0.01,
                          "n_now": 200, "n_base": 800, "p": 0.9, "direction": "up", "unit": "share"}],
             "tests": [{"id": "t::a", "state": "flaky"}, {"id": "t::`b`", "state": "flaky"}, {"id": "t::c", "state": "ok"}],
             "jobs": [{"workflow": ".github/workflows/ci.yml", "job": "lint", "state": "flaky"}]},
    "delivery": {"phases": {"pickup": {"p75_h": 6.0, "n": 30}, "review": {"p75_h": 10.0, "n": 30},
                            "cycle_to_merge": {"p75_h": 40.0, "n": 30}},
                 "dora": {"deployments": 4, "change_failure_rate": 0.25},
                 "changes": [{"metric": "delivery.pickup", "label": "pickup", "now": 30.0, "base": 3.0, "n_now": 6,
                              "n_base": 20, "p": 0.02, "direction": "up", "unit": "h"},
                             *({"metric": f"delivery.{m}", "label": m, "now": 1, "base": 1, "n_now": 9, "n_base": 30,
                                "p": p, "direction": "up", "unit": "h"} for m, p in (("review", 0.5), ("cycle_to_merge", 0.7),
                                                                                     ("deployments", 0.3), ("change_failure", 0.8)))]},
    "flow": {"open": 12, "stale": 2},
    "insights": {"findings": [{"kind": "fix_job", "key": "fix_job:ci.yml/lint", "hours": 30.5, "n": 9,
                               "title": "ci.yml / lint failed and then passed on the same code"}]},
    "community": {"waiting_total": 3},
}
LAST = {"week": "2026-W43", "numbers": {"first_try": 0.86, "pickup_p75_h": 4.5, "review_p75_h": 10.0, "cycle_p75_h": 50.0,
                                        "flaky": ["test t::a", "job ci.yml / lint", "test t::gone"]}}


def test_week_over_week_changes_new_and_recovered_flakes_and_the_top_fix():
    text, numbers = compose("o/r", NOW, DOCS, LAST, [], "https://o.github.io/r/")
    # Only changes that survive false-alarm control over all 8 checked numbers are claimed (Phase 13 M1).
    assert "pushes green on the first try fell to 60% from 90% (n 20 and 80)" in text
    assert "pickup rose to 30.0 h from 3.0 h (medians, n 6 and 20)" in text
    assert "8 numbers checked against the four weeks before; the other 6 held steady within noise" in text
    assert "first-try green 80%" in text and "points from" not in text and "push to all checks" not in text
    assert "pickup P75 6.0 h" in text and "(up 1.5 h)" not in text and "cycle to merge P75 40.0 h;" in text
    assert "newly flaky: `t::'b'`" in text and "1 recovered" in text
    assert "ci.yml / lint failed and then passed" in text and "30.5 h at stake" in text
    assert "3 newcomers waiting" in text and "https://o.github.io/r/" in text
    # Next week compares with the real names; only the message shows them made safe.
    assert numbers["first_try"] == 0.80 and numbers["flaky"] == ["job ci.yml / lint", "test t::`b`", "test t::a"]


def test_a_first_digest_has_no_comparison_and_missing_modules_are_left_out():
    one = compose("o/r", NOW, {"delivery": {"phases": {}, "dora": {"deployments": 1}, "deploy_source": "releases",
                                            "window_days": 90}}, None, [], None)[0]
    assert "; 1 deployment in 90 days." in one
    text, _numbers = compose("o/r", NOW, {"flow": {"open": 1, "stale": 0}}, None, [], None)
    assert "CI" not in text and "Delivery" not in text and "1 open pull request" in text and "from" not in text


def test_decisions_near_their_review_date_are_listed_without_pinging_anyone():
    state = {"test:t::a": {"verb": "quarantine", "kind": "test", "id": "t::a", "until": "2026-10-30", "by": "alice",
                           "reason": "ping @bob at www.example.com"},
             "finding:red_ci": {"verb": "snooze", "kind": "finding", "id": "red_ci", "until": "2026-12-30", "by": "carol",
                                "reason": ""}}
    soon = due(state, NOW.date(), days=7)
    assert [d["id"] for d in soon] == ["t::a"]
    text, _ = compose("o/r", NOW, DOCS, None, soon, None)
    assert "quarantine of `t::a` ends 2026-10-30" in text and "@bob" not in text and "www.example.com" not in text
    assert "alice" in text and "@alice" not in text.replace("`@alice`", "")


def test_working_agreement_exceptions_reach_the_digest():
    delivery = {"phases": {}, "dora": {"deployments": 2},
                "agreements": {"window_days": 14, "labels": {"max_pr_lines": "PRs under 400 lines"},
                               "counts": {"max_pr_lines": 3}, "exceptions": [{"pr": 9}, {"pr": 8}, {"pr": 7}]}}
    text, _ = compose("o/r", NOW, {"delivery": delivery}, None, [], None)
    assert "**Working agreements:** 3 exceptions in the last 14 days (PRs under 400 lines: 3)." in text


def test_dependency_updates_needing_attention_reach_the_digest():
    deps = {"open": [{"pr": 12, "age_hours": 300.0}, {"pr": 10, "age_hours": 100.0}], "security_overdue": [{"pr": 10}],
            "quiet_days": 0, "bots": ["dependabot"]}
    text, _ = compose("o/r", NOW, {"deps": deps}, None, [], None)
    assert "**Dependencies:** 2 update pull requests open (the oldest 12 days); 1 security update waiting over 48 h." in text
    quiet, _ = compose("o/r", NOW, {"deps": {"open": [], "security_overdue": [], "quiet_days": 40, "bots": ["dependabot"]}}, None, [], None)
    assert "no update pull request from dependabot for 40 days" in quiet


def test_an_agent_comparison_with_no_measurable_difference_reads_as_a_sentence():
    # Review finding: "merged by someone else no measurable difference (...) than people's PRs".
    from stackvitals.core.digest import _ai_line
    same = {"verdict": "no measurable difference", "gap": 0.01, "low": -0.02, "high": 0.04, "detectable": 0.06}
    line = _ai_line({"agent": {"merged_by_others": same}}, {})
    assert "than people's" not in line and "merged by someone else: no measurable difference (it could detect 6 points" in line
    more = {"verdict": "higher", "gap": 0.08, "low": 0.02, "high": 0.14, "detectable": 0.06}
    assert "merged by someone else more often (+8 points" in _ai_line({"agent": {"merged_by_others": more}}, {})
