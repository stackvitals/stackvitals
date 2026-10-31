"""Test monitors with Trunk's documented shape, every threshold tunable in .github/stackvitals.toml: pass-on-retry with a
quiet heal, failure rate and broken with separate switch-on and switch-off thresholds, slow and timeout-inflation labels,
mutes, quarantine overrides and status records that say since when."""
from datetime import datetime, timedelta, timezone

from stackvitals.ci.monitors import DEFAULTS, evaluate, transitions
from stackvitals.core.config import parse

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)


def days(d):
    return NOW - timedelta(days=d)


def ev(d):
    return (days(d), "retry", [], {"run": int(d * 10), "att": 1, "kind": "retry"})


def test_pass_on_retry_switches_on_at_two_flakes_and_heals_after_quiet_days():
    cfg = DEFAULTS
    on = evaluate([ev(3), ev(1)], [ev(3), ev(1)], [], 2, NOW, cfg)
    assert on["state"] == "flaky" and on["monitors"] == ["pass_on_retry"] and on["since"] == days(3).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert evaluate([ev(40)], [ev(40)][:0], [], 30, NOW, cfg)["state"] == "ok"
    assert evaluate([ev(2)], [ev(2)], [], 1, NOW, cfg)["state"] == "suspect"
    healed = evaluate([ev(45), ev(40)], [], [], 12, NOW, cfg)
    assert healed["state"] == "fixed" and healed["monitors"] == []
    quick = parse("[ci.monitors.pass_on_retry]\nquiet_days = 7\n")[0]
    assert evaluate([ev(10), ev(9)], [], [], 3, NOW, quick)["state"] != "flaky"
    assert evaluate([ev(10), ev(9)], [], [], 3, NOW, cfg)["state"] == "flaky"


def test_failure_rate_switches_on_above_one_threshold_and_off_below_another():
    pattern = "".join("F" if i % 6 == 0 else "." for i in range(36)) + "...."  # 6 of 40 = 15%, no streak
    hist = [(days(40 - i), c == "F") for i, c in enumerate(pattern)]
    out = evaluate([], [], hist, 0, NOW, DEFAULTS)
    assert out["state"] == "flaky" and out["monitors"] == ["failure_rate"] and out["failure_rate"] == 0.15
    lower = [(days(40 - i), c == "F") for i, c in enumerate("".join("F" if i % 10 == 0 else "." for i in range(40)))]  # 10%
    assert evaluate([], [], lower, 0, NOW, DEFAULTS)["state"] == "ok"
    kept = evaluate([], [], lower, 0, NOW, DEFAULTS, previous={"state": "flaky", "since": "2026-10-01T00:00:00Z",
                                                               "monitors": ["failure_rate"]})
    assert kept["state"] == "flaky" and kept["since"] == "2026-10-01T00:00:00Z"
    few = [(days(10 - i), c == "F") for i, c in enumerate("....FF....")]  # 20% but only 10 runs
    assert evaluate([], [], few, 0, NOW, DEFAULTS)["state"] == "ok"


def test_broken_by_a_streak_or_by_rate_and_it_stays_broken_until_the_rate_falls_below_half():
    streak = [(days(5 - i), c == "F") for i, c in enumerate("..FFF")]
    b = evaluate([], [], streak, 0, NOW, DEFAULTS)
    assert b["state"] == "broken" and b["since"] == days(3).strftime("%Y-%m-%dT%H:%M:%SZ")
    mostly = [(days(5 - i), c == "F") for i, c in enumerate("FFF.F")]
    assert evaluate([], [], mostly, 0, NOW, DEFAULTS)["state"] == "broken"
    recovering = [(days(5 - i), c == "F") for i, c in enumerate("FFFF.")]  # 80% over 5, last passed
    assert evaluate([], [], recovering, 0, NOW, DEFAULTS, previous={"state": "broken", "since": "x", "monitors": ["broken"]})["state"] == "broken"
    better = [(days(5 - i), c == "F") for i, c in enumerate("FF...")]  # 40%: below half
    assert evaluate([], [], better, 0, NOW, DEFAULTS, previous={"state": "broken", "since": "x", "monitors": ["broken"]})["state"] != "broken"


def test_labels_mutes_and_bad_config():
    out = evaluate([], [], [], 0, NOW, DEFAULTS, pass_ms=[6000, 6500, 7000], fail_ms=[30000, 30010, 29990])
    assert out["labels"] == ["slow", "timeout_inflation"]
    cfg, notes = parse('[ci.mute]\n"tests/test_net.py::*" = "2026-11-01"\n"old::t" = "2026-10-01"\n')
    assert notes == []
    assert evaluate([ev(3), ev(1)], [ev(3), ev(1)], [], 2, NOW, cfg, test_id="tests/test_net.py::test_x")["muted_until"] == "2026-11-01"
    assert "muted_until" not in evaluate([ev(3), ev(1)], [ev(3), ev(1)], [], 2, NOW, cfg, test_id="old::t")
    cfg, notes = parse("[ci.monitors.broken]\nactivate = 'lots'\n[ci.monitors.nonsense]\nx = 1\n")
    assert cfg["ci"]["monitors"]["broken"]["activate"] == 0.8 and len(notes) == 2
    cfg, notes = parse("this is = not toml [")
    assert cfg == parse("")[0] and "stackvitals.toml" in notes[0]


def test_status_records_keep_since_and_log_each_change():
    previous = {"a": {"state": "flaky", "since": "2026-10-01T00:00:00Z", "monitors": ["pass_on_retry"]},
                "b": {"state": "broken", "since": "2026-10-10T00:00:00Z", "monitors": ["broken"]}}
    tests = [{"id": "a", "state": "flaky", "monitors": ["pass_on_retry"], "since": "2026-10-05T00:00:00Z"},
             {"id": "b", "state": "fixed", "monitors": [], "since": None},
             {"id": "c", "state": "flaky", "monitors": ["failure_rate"], "since": "2026-10-19T00:00:00Z"}]
    status, changes = transitions(previous, tests, NOW)
    assert status["a"]["since"] == "2026-10-01T00:00:00Z"  # unchanged state keeps its original since
    assert status["c"] == {"state": "flaky", "since": "2026-10-19T00:00:00Z", "monitors": ["failure_rate"]}
    assert "b" not in status  # healthy again: no record
    assert [(c["id"], c["from"], c["to"]) for c in changes] == [("b", "broken", "fixed"), ("c", "ok", "flaky")]
    assert all(c["at"] == "2026-10-20T12:00:00Z" for c in changes)
