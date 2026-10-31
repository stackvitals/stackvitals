"""Phase 13 M1: the uncertainty layer's statistics, checked against textbook values."""
import math
import random

import pytest

from stackvitals.core import stats


def test_the_incomplete_beta_matches_the_binomial_tail_and_its_inverse_round_trips():
    # For whole numbers, I_x(a, b) is the chance of at least a successes in a + b - 1 tries.
    assert stats.betainc(2, 3, 0.5) == pytest.approx(11 / 16, abs=1e-9)
    assert stats.betainc(1, 1, 0.3) == pytest.approx(0.3, abs=1e-9)
    assert stats.betainc(5, 2, 0) == 0 and stats.betainc(5, 2, 1) == 1
    for a, b, q in ((11, 2, 0.025), (0.5, 0.5, 0.9), (300, 40, 0.5)):
        x = stats.beta_ppf(q, a, b)
        assert stats.betainc(a, b, x) == pytest.approx(q, abs=1e-6)


def test_fishers_exact_test_gives_the_textbook_answers():
    assert stats.fisher(3, 4, 1, 4) == pytest.approx(0.4857, abs=1e-4)  # 3 of 4 against 1 of 4
    assert stats.fisher(10, 10, 0, 10) == pytest.approx(2 / math.comb(20, 10), rel=1e-6)
    assert stats.fisher(5, 10, 5, 10) == pytest.approx(1.0)
    assert stats.fisher(0, 0, 3, 10) == 1.0


def test_mann_whitney_finds_a_shift_and_not_a_tie():
    assert stats.mann_whitney([1, 2, 3, 4, 5], [6, 7, 8, 9, 10]) == pytest.approx(0.0122, abs=0.001)
    assert stats.mann_whitney([1, 2, 3], [1, 2, 3]) == pytest.approx(1.0)
    assert stats.mann_whitney([], [1, 2]) == 1.0
    assert stats.mann_whitney([2, 2, 2, 2], [2, 2, 2, 2]) == 1.0  # all tied: nothing to see


def test_a_weeks_count_is_compared_with_the_weeks_before():
    # 10 this week against 4 in the 4 weeks before: far above the expected fifth of 14.
    assert stats.count_change(10, 4, 4) < 0.001
    assert stats.count_change(1, 4, 4) == pytest.approx(1.0)
    assert stats.count_change(0, 0, 4) == 1.0


def test_benjamini_hochberg_keeps_what_survives_the_whole_scan():
    assert stats.bh([0.01, 0.04, 0.03, 0.2], 0.1) == [True, True, True, False]
    assert stats.bh([0.04, 0.05, 0.06, 0.07, 0.08], 0.1) == [True] * 5  # step-up: the largest p clears 5/5 of q
    assert stats.bh([0.03, 0.5, 0.6, 0.7, 0.8], 0.1) == [False] * 5  # one small p among five is not enough
    assert stats.bh([], 0.1) == []


def test_a_beta_binomial_prior_is_recovered_from_many_repos():
    rng = random.Random(7)
    pairs = []
    for _ in range(600):
        p = rng.betavariate(8, 2)
        n = rng.randint(3, 60)
        pairs.append((sum(rng.random() < p for _ in range(n)), n))
    a, b = stats.beta_fit(pairs)
    assert a / (a + b) == pytest.approx(0.8, abs=0.02) and 5 <= a + b <= 20


def test_a_small_sample_is_pulled_toward_its_peers_and_a_big_one_barely_moves():
    small = stats.shrink(3, 3, (8, 2))
    assert small["value"] == pytest.approx(11 / 13, abs=1e-4) and small["low"] < 0.7 < small["high"] <= 1
    big = stats.shrink(300, 600, (8, 2))
    assert big["value"] == pytest.approx(308 / 610, abs=1e-4) and big["high"] - big["low"] < 0.1
    assert stats.shrink(0, 0, (8, 2))["value"] == pytest.approx(0.8)


def test_dora_numbers_carry_ranges_and_say_when_the_tier_is_not_settled():
    from datetime import datetime, timedelta, timezone

    from stackvitals.core.delivery import dora
    end = datetime(2026, 10, 21, tzinfo=timezone.utc)
    start = end - timedelta(days=90)
    stamp = lambda d: (end - timedelta(days=d)).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    deps = [{"id": f"d{i}", "finished": stamp(2 + 4 * i)} for i in range(20)]
    # Lead times from 10 h to 48 h: the median sits near the one-day cut between elite and high.
    deployed = [{"deployment": f"d{i}", "cycle_min": (10 + 2 * i) * 60} for i in range(20)]
    incidents = [{"deployment": f"d{i}", "created": stamp(1 + 4 * i), "resolved": stamp(4 * i)} for i in (1, 5, 9)]
    out = dora(deps, deployed, incidents, start, end)
    low, high = out["lead_time_range_hours"]
    assert low <= out["lead_time_hours"] <= high and high - low > 1
    assert out["lead_time_tier_span"] == ["elite", "high"]
    assert out["cfr_range"][0] < out["change_failure_rate"] < out["cfr_range"][1]
    assert out["recovery_range_hours"] is None  # three restores are too few for a range
    few = dora(deps[:3], deployed[:3], [], start, end)
    assert few["lead_time_range_hours"] is None and few["lead_time_tier_span"] is None


def test_ci_push_numbers_carry_ranges_measured_like_the_benchmark():
    from datetime import datetime, timedelta, timezone

    from stackvitals.ci.bench import push_stats
    now = datetime(2026, 10, 21, tzinfo=timezone.utc)
    runs = []
    for i in range(30):
        start = now - timedelta(days=1 + i / 2)
        runs.append({"id": i, "att": 1, "ev": "push", "sha": f"s{i}", "path": "ci.yml", "br": "main",
                     "c": "success" if i % 5 else "failure", "cr": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "up": (start + timedelta(minutes=5 + i)).strftime("%Y-%m-%dT%H:%M:%SZ")})
    out = push_stats({"runs": runs}, now)
    lo, hi = out["first_try_range"]
    assert lo < out["first_try_share"] < hi and out["pushes"] == 30
    mlo, mhi = out["median_range_s"]
    assert mlo <= out["median_s"] <= mhi and "durations" not in out


def test_a_week_is_compared_with_the_four_before_and_only_real_shifts_survive_the_scan():
    from stackvitals.core import changes
    slow = changes.times("flow.pickup", "pickup", [30, 40, 35, 50, 45, 38], [2, 3, 4, 2, 5, 3, 4, 2, 3, 6], better=-1, unit="h")
    assert slow["direction"] == "up" and slow["p"] < 0.01 and slow["n_now"] == 6 and slow["worse"]
    noise = [changes.share(f"m{i}", "x", 7, 10, 30, 40, better=1) for i in range(7)]
    few = changes.share("ci.first_try", "first try", 1, 3, 30, 40, better=1)
    assert few["p"] == 1.0 and few["note"] == "too few to tell"
    deploys = changes.count("delivery.deployments", "deployments", 2, 9, better=1)
    assert deploys["base"] == 2.25 and deploys["p"] == 1.0
    flagged = changes.flag([slow, few, deploys, *noise])
    assert [c["metric"] for c in flagged if c["changed"]] == ["flow.pickup"]
    assert all("changed" in c for c in flagged) and len(flagged) == 10


def test_ci_publishes_this_weeks_changes_against_the_four_before():
    from datetime import datetime, timedelta, timezone

    from stackvitals.ci.analyze import _changes
    now = datetime(2026, 10, 21, tzinfo=timezone.utc)
    runs, finals, events = [], {"ci.yml|test": {"g": []}}, {"ci.yml|test": []}
    for i in range(60):
        start = now - timedelta(hours=8 * i + 1)
        broken = i < 21 and i % 2 == 0  # this week: half the pushes fail
        runs.append({"id": i, "att": 1, "ev": "push", "sha": f"s{i}", "path": "ci.yml", "br": "main",
                     "c": "failure" if broken else "success", "cr": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "up": (start + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")})
        finals["ci.yml|test"]["g"].append(({"cr": runs[-1]["cr"]}, None))
    out = {c["metric"]: c for c in _changes({"runs": runs}, finals, events, now)}
    green = out["ci.first_try_green"]
    assert green["direction"] == "down" and green["p"] < 0.01 and green["worse"]
    assert out["ci.push_wait"]["p"] > 0.5 and out["ci.flake_share"]["n_now"] == 21


def test_delivery_publishes_this_weeks_changes_against_the_four_before():
    from datetime import datetime, timedelta, timezone

    from stackvitals.core.delivery import _changes
    now = datetime(2026, 10, 21, tzinfo=timezone.utc)
    stamp = lambda h: (now - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    rows = []
    for i in range(40):
        hours_ago = 12 * i + 1
        slow = hours_ago < 168
        ph = {"pickup": 30.0 + i if slow else 2.0 + (i % 3), "review": 5.0, "cycle_to_merge": 40.0 if slow else 8.0}
        rows.append(({"n": i, "mg": stamp(hours_ago)}, ph, None))
    deps = [{"id": f"d{i}", "finished": stamp(20 * i + 2)} for i in range(30)]
    incidents = [{"deployment": "d1", "created": stamp(10)}]
    out = {c["metric"]: c for c in _changes(rows, deps, incidents, now)}
    assert out["delivery.pickup"]["direction"] == "up" and out["delivery.pickup"]["p"] < 0.01
    assert "delivery.review" not in out and out["delivery.cycle_to_merge"]["direction"] == "up"
    assert out["delivery.deployments"]["n_now"] == 9 and out["delivery.change_failure"]["n_now"] == 9


def test_an_alert_misses_only_when_the_whole_range_is_past_the_limit():
    from datetime import datetime, timedelta, timezone

    from stackvitals.core import alerts
    assert alerts._level(13.0, 12, 12.0, low=8.0) == "heads_up"  # over, but the range still reaches under the limit
    assert alerts._level(20.0, 40, 12.0, low=15.0) == "miss"
    assert alerts._level(20.0, 40, 12.0) == "miss"  # no range published (older files): the old rule
    now = datetime(2026, 10, 21, tzinfo=timezone.utc)
    stamp = lambda h: (now - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    rows = [({"mg": stamp(6 * i + 1)}, {"pickup": float(i % 40), "review": 1.0, "cycle_to_merge": 2.0}, None) for i in range(100)]
    day, value, n, low = alerts.series(rows, [], [], now, days=0)["pickup_p75_hours"][-1]
    assert n == 100 and low is not None and low < value


def test_an_unsure_heads_up_says_it_is_past_the_limit_but_not_settled():
    from stackvitals.core import alerts, chat
    text = chat.text(alerts.message([{"metric": "pickup_p75_hours", "level": "heads_up", "value": 13.0, "limit": 12.0, "n": 12}], "o/r"))
    assert "past its limit, but its likely range still reaches under it: 13.0 against 12.0 (n=12)" in text


def test_the_ci_benchmark_carries_a_prior_and_a_small_repo_is_pulled_toward_it():
    from datetime import datetime, timezone

    from mergescout.bench.ci import aggregate
    from stackvitals.ci.bench import compare
    rng = random.Random(3)
    records = []
    for i in range(400):
        n = rng.randint(5, 50)
        share = round(sum(rng.random() < rng.betavariate(9, 3) for _ in range(n)) / n, 4)
        records.append({"repo": f"o/r{i}", "day": "2026-10-20", "language": "Python", "stars": 500, "pushes": n,
                        "median_s": 300, "p90_s": 600, "first_try_share": share, "fail_share": 0.1, "rerun_share": 0.05})
    bench = aggregate(records, datetime(2026, 10, 21, tzinfo=timezone.utc))
    a, b = bench["groups"]["all|all"]["first_try_prior"]
    assert a / (a + b) == pytest.approx(0.75, abs=0.03)
    mine = {"pushes": 4, "median_s": 300, "first_try_share": 0.25, "first_try_range": [0.05, 0.7]}
    pulled = next(m for m in compare(mine, bench, "Python", 500)["metrics"] if m["kind"] == "share")["pulled"]
    assert 0.25 < pulled["value"] < 0.75 and pulled["low"] < pulled["value"] < pulled["high"]
    # A file without priors (an older benchmark) still compares, without the pulled figure.
    del bench["groups"]["all|all"]["first_try_prior"]
    for g in bench["groups"].values():
        g.pop("first_try_prior", None)
    assert "pulled" not in next(m for m in compare(mine, bench, "Python", 500)["metrics"] if m["kind"] == "share")


def test_the_printable_ci_page_shows_the_share_pulled_toward_similar_repos():
    from stackvitals.ci.report import _bench
    result = {"benchmark": {"repos": 300, "group": "Python repos", "metrics": [
        {"name": "Pushes green on the first try", "kind": "share", "you": 0.25, "typical": 0.8, "place": "below about 90%",
         "pulled": {"value": 0.62, "low": 0.45, "high": 0.77, "n": 4}}]}}
    _head, lines = _bench(result)
    assert lines == ["Pushes green on the first try: 25% (typical 80%), below about 90%; from only 4 pushes, similar repos "
                     "suggest 62% (likely 45% to 77%)"]


def test_student_t_and_normal_tails_match_their_tables():
    assert stats.t_two_sided(2.306, 8) == pytest.approx(0.05, abs=5e-4)
    assert stats.t_two_sided(0.0, 5) == pytest.approx(1.0)
    assert stats.normal_isf(0.05) == pytest.approx(1.95996, abs=1e-4)
    assert stats.normal_isf(1.0) == 0.0


def test_a_change_is_judged_against_how_much_this_repos_weeks_usually_swing():
    from datetime import datetime, timezone

    from stackvitals.core import changes
    now = datetime(2026, 10, 21, tzinfo=timezone.utc)

    def checks(swing_p):
        def at(t):
            p = 0.001 if t == now else swing_p
            return [{"metric": "m", "label": "m", "now": 2.0, "base": 1.0, "n_now": 20, "n_base": 80, "p": p,
                     "direction": "up", "better": -1, "worse": True, "unit": "h", "note": None}]
        return at
    calm = changes.calibrate(checks(0.6), now)[0]  # past weeks rarely moved: p = 0.001 stays strong
    swingy = changes.calibrate(checks(0.002), now)[0]  # past weeks swung this much all the time: nothing unusual
    assert calm["p"] < 0.0125 and calm["p_raw"] == 0.001 and calm["weeks_seen"] == 8
    assert swingy["p"] > 0.2 and swingy["spread"] > 5


def test_checks_that_were_not_run_do_not_dilute_the_scan():
    from stackvitals.core import changes
    real = {"metric": "a", "label": "a", "now": 2, "base": 1, "n_now": 30, "n_base": 90, "p": 0.02, "direction": "up",
            "better": -1, "worse": True, "unit": "h", "note": None}
    skipped = [{**real, "metric": f"s{i}", "p": 1.0, "note": "too few to tell"} for i in range(6)]
    flagged = changes.flag([real, *skipped])
    assert flagged[0]["changed"] and not any(c["changed"] for c in flagged[1:])


def test_t_quantiles_invert_the_t_tail():
    assert stats.t_isf(0.05, 12) == pytest.approx(2.179, abs=1e-3)
    assert stats.t_isf(1.0, 5) == 0.0


def test_each_check_says_how_big_a_change_it_could_have_seen():
    from stackvitals.core import changes
    times = {"unit": "h", "scale": 0.5, "df": 12}
    # alpha = 0.1 / 4 checks run; t(0.025, 12) + 0.84 = 3.40 standard errors of 0.5 on the log scale: about 5.5 times.
    assert changes.detectable(times, 4) == pytest.approx(math.exp(3.40 * 0.5), rel=0.01)
    share = {"unit": "share", "scale": 0.05, "df": 12}
    assert changes.detectable(share, 4) == pytest.approx(3.40 * 0.05, rel=0.01)
    assert changes.detectable({"unit": "count", "scale": None, "df": 4}, 4) is None


def test_a_quiet_digest_says_what_size_of_change_it_could_have_caught():
    from datetime import datetime, timezone

    from stackvitals.core.digest import compose
    check = {"metric": "delivery.pickup", "label": "pickup", "now": 3.0, "base": 2.8, "n_now": 22, "n_base": 80, "p": 0.6,
             "direction": "up", "unit": "h", "scale": 0.45, "df": 12, "note": None}
    text = compose("o/r", datetime(2026, 10, 26, tzinfo=timezone.utc), {"delivery": {"phases": {}, "dora": {}, "changes": [
        check, {**check, "metric": "delivery.cycle_to_merge", "label": "opened to merged", "scale": 0.6}]}}, None, [], None)[0]
    assert "2 numbers checked against the four weeks before; all held steady within noise" in text
    assert "with 22 PRs merged this week, review times would have had to change about 4× to stand out" in text


def test_a_week_with_no_deployments_is_checked_without_crashing():
    from datetime import datetime, timezone

    from stackvitals.core import changes
    now = datetime(2026, 10, 21, tzinfo=timezone.utc)
    out = changes.calibrate(lambda t: [changes.count("delivery.deployments", "deployments", 0, 0, better=1),
                                       changes.share("x", "x", 0, 0, 0, 0, better=1)], now)
    assert out[0].get("scale") is None and out[0]["p"] == 1.0 and out[1]["note"] == "too few to tell"


def test_one_wild_past_week_counts_as_at_most_a_four_sigma_swing():
    from datetime import datetime, timezone

    from stackvitals.core import changes
    now = datetime(2026, 10, 21, tzinfo=timezone.utc)

    def at(t):
        p = 1e-6 if t == now else 1e-80 if t == now - changes.WEEK * 3 else 0.5
        return [{"metric": "m", "label": "m", "now": 2.0, "base": 1.0, "n_now": 100, "n_base": 400, "p": p, "direction": "up",
                 "better": -1, "worse": True, "unit": "h", "note": None, "log_sd": 2.0}]
    out = changes.calibrate(at, now)[0]
    assert out["spread"] < 2.5 and out["p"] < 0.01


def test_too_few_deployments_are_not_a_test():
    from stackvitals.core import changes
    assert changes.count("d", "deployments", 1, 0, better=1)["note"] == "too few to tell"
    assert changes.count("d", "deployments", 6, 4, better=1)["note"] is None


def test_a_digest_with_nothing_to_compare_says_so():
    from datetime import datetime, timezone

    from stackvitals.core import changes
    from stackvitals.core.digest import compose
    empty = [changes.times("delivery.pickup", "pickup", [], [], better=-1, unit="h"),
             changes.count("delivery.deployments", "deployments", 0, 0, better=1)]
    text = compose("o/r", datetime(2026, 10, 26, tzinfo=timezone.utc), {"delivery": {"phases": {}, "dora": {}, "changes": empty}},
                   None, [], None)[0]
    assert "**This week:** too few PRs, pushes or deployments to compare with the four weeks before." in text


def test_a_modules_checks_are_published_flagged_and_with_what_they_could_have_seen():
    from stackvitals.core import changes
    base = {"label": "x", "now": 2.0, "base": 1.0, "n_now": 30, "n_base": 90, "direction": "up", "better": -1,
            "worse": True, "unit": "h", "note": None, "scale": 0.3, "df": 12}
    out = changes.annotate([{**base, "metric": "a", "p": 0.001}, {**base, "metric": "b", "p": 0.6},
                            {**base, "metric": "c", "p": 1.0, "note": "too few to tell", "scale": None}])
    assert [c["changed"] for c in out] == [True, False, False]
    assert out[1]["detectable"] > 1 and out[2]["detectable"] is None


def test_an_open_miss_stays_a_miss_while_the_value_stays_over_the_limit():
    # Review finding: the range's low end crossing the limit back and forth sent 6 alerts in 10 days instead of 1.
    from stackvitals.core.alerts import replay
    days = [(f"d{k}", 20.0, 30, 12.0 if k % 2 else 9.0) for k in range(10)]  # value over 10 every day, low end wobbling
    # A heads-up on the first day, then one miss: no repeats while it stays over.
    assert replay({"pickup_p75_hours": days}, {"pickup_p75_hours": 10}) == {"pickup_p75_hours": 2}
