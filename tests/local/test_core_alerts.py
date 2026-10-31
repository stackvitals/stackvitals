"""Alerts on delivery numbers: thresholds from LinearB's "good" band unless the repo sets its own, a heads-up at 80% and a
miss past it, each sent once per change of state, "would have fired N times" replayed over stored history, and payloads
for Slack, Discord, Teams and plain JSON webhooks."""
import json
from datetime import datetime, timedelta, timezone

import httpx

from stackvitals.core import alerts
from stackvitals.core.config import parse

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)


def day(k):
    return (NOW - timedelta(days=k)).date().isoformat()


def test_defaults_come_from_linearbs_good_band_and_the_file_can_change_or_turn_them_off():
    cfg, notes = parse('[alerts]\npickup_p75_hours = 8\ncycle_p75_hours = 0\nchannels = ["webhook", "issue"]\n')
    assert cfg["alerts"]["pickup_p75_hours"] == 8 and cfg["alerts"]["review_p75_hours"] == 14
    assert alerts.thresholds(cfg) == {"pickup_p75_hours": 8, "review_p75_hours": 14, "change_failure_rate": 0.15}
    assert cfg["alerts"]["channels"] == ["webhook", "issue"] and notes == []
    assert parse('[alerts]\npickup_p75_hours = "fast"\n')[1]  # a bad value is named and the default kept


def test_a_metric_alerts_once_per_change_heads_up_then_miss_then_recovered():
    limits = {"pickup_p75_hours": 10}
    state, events = alerts.evaluate({"pickup_p75_hours": (5.0, 30)}, limits, {})
    assert events == [] and state["pickup_p75_hours"]["level"] == "ok"
    state, events = alerts.evaluate({"pickup_p75_hours": (8.5, 30)}, limits, state)
    assert [e["level"] for e in events] == ["heads_up"]
    state, events = alerts.evaluate({"pickup_p75_hours": (9.0, 30)}, limits, state)
    assert events == []  # still a heads-up: nothing new to say
    state, events = alerts.evaluate({"pickup_p75_hours": (12.0, 30)}, limits, state)
    assert [e["level"] for e in events] == ["miss"] and events[0]["value"] == 12.0 and events[0]["n"] == 30
    state, events = alerts.evaluate({"pickup_p75_hours": (4.0, 30)}, limits, state)
    assert [e["level"] for e in events] == ["recovered"]


def test_too_few_prs_never_alert():
    state, events = alerts.evaluate({"pickup_p75_hours": (99.0, 4)}, {"pickup_p75_hours": 10}, {})
    assert events == [] and state["pickup_p75_hours"]["level"] == "not enough data"


def test_would_have_fired_replays_the_stored_days():
    series = {"pickup_p75_hours": [(day(k), v, 30) for k, v in enumerate([5, 9, 12, 12, 3, 11, 2])][::-1]}
    # Oldest first: 2 ok, 11 miss (1), 3 recovered (2), 12 miss (3), 12 still, 9 falls to a heads-up (no news), 5 recovered (4).
    assert alerts.replay(series, {"pickup_p75_hours": 10}) == {"pickup_p75_hours": 4}


def test_the_series_is_measured_over_trailing_28_days_from_merged_prs():
    rows = []
    for k in range(40):
        merged = (NOW - timedelta(days=k * 2, hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows.append(({"mg": merged}, {"pickup": 2.0 if k < 14 else 20.0, "review": 1.0, "cycle_to_merge": 5.0}, None))
    s = alerts.series(rows, [], [], NOW, days=60)
    today = s["pickup_p75_hours"][-1]
    assert today[0] == NOW.date().isoformat() and today[1] == 2.0 and today[2] == 14  # last 28 days: 14 fast PRs
    assert s["pickup_p75_hours"][0][1] == 20.0  # 60 days ago only slow ones were in its window


def test_payloads_fit_each_channel():
    events = [{"metric": "pickup_p75_hours", "level": "miss", "value": 12.0, "limit": 10, "n": 30}]
    from stackvitals.core import chat
    msg = alerts.message(events, "o/r")
    text = "\n".join([msg["title"], *msg["lines"]])
    assert "o/r" in text and "12" in text and "n=30" in text
    assert chat.payload("https://hooks.slack.com/services/x", msg)["blocks"][0]["type"] == "header"
    assert chat.payload("https://discord.com/api/webhooks/1/x", msg)["embeds"][0]["title"].startswith("StackVitals alerts")
    teams = chat.payload("https://prod-01.westus.logic.azure.com/workflows/x", msg)
    assert teams["attachments"][0]["content"]["type"] == "AdaptiveCard"
    plain = chat.payload("https://example.com/hook", msg)
    assert plain["source"] == "stackvitals" and plain["alerts"][0]["metric"] == "pickup_p75_hours"


def test_sending_posts_once_and_reports_failures_without_raising():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    events = [{"metric": "pickup_p75_hours", "level": "miss", "value": 12.0, "limit": 10, "n": 30}]
    assert alerts.send("https://hooks.slack.com/services/x", events, "o/r", client=client) is None and len(seen) == 1
    broken = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert "500" in alerts.send("https://hooks.slack.com/services/x", events, "o/r", client=broken)


def test_the_action_step_alerts_once_keeps_only_levels_and_replays_new_thresholds(tmp_path):
    import subprocess

    from stackvitals.ci.api import ActionsAPI
    from stackvitals.core.alerts import alerts_step
    from stackvitals.core.workspace import run_job
    from stackvitals.flow.store import FlowStore
    from test_core_delivery import pr, review

    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    summary = tmp_path / "s.md"
    env = {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": bare.as_uri(),
           "RUNNER_TEMP": str(tmp_path / "tmp"), "GITHUB_STEP_SUMMARY": str(summary),
           "STACKVITALS_WEBHOOK": "https://hooks.slack.com/services/x"}
    # 20 PRs merged in the last 3 weeks, each picked up 30 hours after it was opened: pickup P75 30 h, over the 4 h default.
    merged = [pr(100 + k, cr=24 * k + 40, mg=24 * k + 2, fa=24 * k + 41, ev=[review(24 * k + 10)]) for k in range(20)]
    posted, issues = [], []

    def hook(request):
        posted.append(json.loads(request.content))
        return httpx.Response(200)

    def gh(request):
        if request.method == "GET":
            return httpx.Response(200, json=[])
        issues.append((request.method, json.loads(request.content)))
        return httpx.Response(201, json={"number": 1})
    make = lambda token, repo, **kw: ActionsAPI(token, repo, client=httpx.Client(transport=httpx.MockTransport(gh)),  # noqa: E731
                                                sleep=lambda s: None, **kw)
    cfg = parse('[alerts]\nchannels = ["webhook", "issue"]\n')[0]

    def seed(ws):
        ws.results["Team Flow"] = {"prs": 20}
        ws.cache["settings"] = cfg
        if not (ws.path / "flow" / "closed").is_dir():
            FlowStore(ws.path).put(merged, "2026-10-19")
        return {}
    step = ("Alerts", lambda ws: alerts_step(ws, env, NOW, make_api=make,
                                             client=httpx.Client(transport=httpx.MockTransport(hook))))
    out = run_job(env, [("seed", seed), step], NOW)
    assert out["errors"] == {} and out["results"]["Alerts"]["events"] >= 1
    assert len(posted) == 1 and "pickup time P75" in posted[0]["text"]
    assert issues and issues[0][0] == "POST" and issues[0][1]["title"] == "StackVitals: delivery alerts"
    text = summary.read_text(encoding="utf-8")
    assert "would have fired" in text
    stored = json.loads(subprocess.run(["git", "show", "stackvitals-data:alerts/state.json"], cwd=bare, capture_output=True,
                                       text=True).stdout)
    assert stored["metrics"]["pickup_p75_hours"]["verdict"] == "miss" and "value" not in stored["metrics"]["pickup_p75_hours"]
    # The next run sees the same miss: nothing is sent again and nothing new is committed.
    head = subprocess.run(["git", "rev-parse", "stackvitals-data"], cwd=bare, capture_output=True, text=True).stdout
    run_job(env, [("seed", seed), step], NOW + timedelta(hours=3))
    assert len(posted) == 1
    assert subprocess.run(["git", "rev-parse", "stackvitals-data"], cwd=bare, capture_output=True, text=True).stdout == head


def test_the_app_gets_the_daily_series_to_replay_any_threshold(tmp_path):
    """docs/alerts.json: 91 whole days per metric with n, the limits and the rule's constants, for the settings preview."""
    import subprocess

    from stackvitals.core.alerts import alerts_step, replay
    from stackvitals.core.workspace import run_job
    from stackvitals.flow.store import FlowStore
    from test_core_delivery import pr, review

    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    env = {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": bare.as_uri(),
           "RUNNER_TEMP": str(tmp_path / "tmp")}
    merged = [pr(100 + k, cr=24 * k + 40, mg=24 * k + 2, fa=24 * k + 41, ev=[review(24 * k + 10)]) for k in range(20)]

    def seed(ws):
        ws.results["Team Flow"] = {"prs": 20}
        ws.cache["settings"] = parse('[alerts]\nchannels = []\n')[0]
        FlowStore(ws.path).put(merged, "2026-10-19")
        return {}
    run_job(env, [("seed", seed), ("Alerts", lambda ws: alerts_step(ws, env, NOW))], NOW)
    doc = json.loads(subprocess.run(["git", "show", "stackvitals-data:docs/alerts.json"], cwd=bare, capture_output=True,
                                    text=True).stdout)
    assert doc["window_days"] == 28 and doc["min_n"] == 10 and doc["limits"]["pickup_p75_hours"] == 4.0
    assert len(doc["series"]["pickup_p75_hours"]) == 91 and doc["series"]["pickup_p75_hours"][-1][2] >= 10
    # The browser replays these points with the same rule the Action uses.
    points = {m: [tuple(p) for p in v] for m, v in doc["series"].items()}
    assert replay(points, {"pickup_p75_hours": 4.0})["pickup_p75_hours"] >= 1
