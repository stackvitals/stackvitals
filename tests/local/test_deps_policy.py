from stackvitals.core.config import parse


def test_policy_settings_take_a_score_and_a_severity_and_refuse_the_rest():
    cfg, notes = parse('[deps.policy]\nmin_scorecard = 5\nmax_severity = "high"\n')
    assert cfg["deps"]["policy"] == {"min_scorecard": 5.0, "max_severity": "high"} and not notes
    cfg, notes = parse('[deps.policy]\nmin_scorecard = 11\nmax_severity = "severe"\ncolour = 1\n')
    assert cfg["deps"]["policy"] == {"min_scorecard": None, "max_severity": None} and len(notes) == 3
    assert parse("")[0]["deps"]["policy"] == {"min_scorecard": None, "max_severity": None}


def test_the_osv_summary_keeps_the_worst_open_advisory():
    from datetime import datetime, timezone

    from mergescout.signals.osv import _summary
    now = datetime(2026, 10, 18, tzinfo=timezone.utc)
    fact = lambda i, sev, fixed: {"id": i, "aliases": [], "published": "2026-01-01", "withdrawn": False,  # noqa: E731
                                  "severity": sev, "pkgs": {"pypi:x": fixed}, "bounds": {}}
    out = _summary("pypi:x", [fact("A", "CRITICAL", True), fact("B", "MODERATE", False), fact("C", "HIGH", False)], now)
    assert out["open_severity"] == "HIGH"
    assert _summary("pypi:x", [fact("A", "CRITICAL", True)], now)["open_severity"] is None


def test_a_changed_package_with_an_open_advisory_above_the_policy_is_flagged():
    from stackvitals.deps.action import apply_policy
    d = {"verdict": "use", "reasons": ["fine"], "osv": {"open_severity": "CRITICAL"}}
    got = apply_policy(d, {"min_scorecard": None, "max_severity": "high"}, "lodash")
    assert got["verdict"] == "investigate" and "max_severity" in got["reasons"][0] and "/stackvitals accept package:lodash" in got["reasons"][0]
    assert apply_policy(d, {"min_scorecard": None, "max_severity": "critical"}, "lodash") == d
    assert apply_policy(d, {"min_scorecard": None, "max_severity": None}, "lodash") == d


def test_projects_under_the_minimum_scorecard_are_listed_unless_accepted():
    from stackvitals.deps.supply import below_policy
    cards = {"scores": {"github.com/a/a": [["2026-10-01", 3.1]], "github.com/b/b": [["2026-10-01", 7.0]]},
             "names": {"github.com/a/a": ["a-lib"], "github.com/b/b": ["b-lib"]}}
    got = below_policy(cards["scores"], cards["names"], 5.0, accepted=set())
    assert got == [{"project": "github.com/a/a", "score": 3.1, "packages": ["a-lib"]}]
    assert below_policy(cards["scores"], cards["names"], 5.0, accepted={"a-lib"}) == []
    assert below_policy(cards["scores"], cards["names"], None, accepted=set()) == []
