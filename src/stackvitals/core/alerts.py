"""Alerts on delivery numbers over the last 28 days: a heads-up at 80% of a threshold and a miss past it, each sent once
per change of state (and once on recovery), "would have fired N times" replayed over stored history, and payloads for
Slack, Discord, Microsoft Teams (Workflows) and plain JSON webhooks."""
from datetime import datetime, timedelta

import httpx

from stackvitals.core import chat
from stackvitals.core.stats import percentile, quantile_range, wilson
from stackvitals.core.time import iso

WINDOW_DAYS = 28
HEADS_UP = 0.8
MIN_N = 10
LEVELS = ("ok", "heads_up", "miss")
NAMES = {"pickup_p75_hours": "pickup time P75 (hours)", "review_p75_hours": "review time P75 (hours)",
         "cycle_p75_hours": "cycle time to merge P75 (hours)", "change_failure_rate": "change failure rate"}
PHASE_OF = {"pickup_p75_hours": "pickup", "review_p75_hours": "review", "cycle_p75_hours": "cycle_to_merge"}


def thresholds(cfg: dict) -> dict:
    """The thresholds in force: every metric set above 0."""
    return {k: v for k, v in cfg["alerts"].items() if k in NAMES and v}


def series(rows: list[tuple], deps: list[dict], incidents: list[dict], now: datetime, days: int = 90,
           window: int = WINDOW_DAYS) -> dict[str, list[tuple]]:
    """Each metric for each of the last `days` days, over the `window` days before it: [(day, value, n, low)], oldest
    first; `low` is the bottom of the value's likely range, so a miss can wait until the whole range is past the limit."""
    out = {k: [] for k in NAMES}
    failed = {i["deployment"] for i in incidents if i.get("deployment")}
    for k in range(days, -1, -1):
        end = now - timedelta(days=k)
        lo, hi = iso(end - timedelta(days=window)), iso(end)
        merged = [ph for p, ph, _dep in rows if p.get("mg") and lo < p["mg"] <= hi]
        for metric, phase in PHASE_OF.items():
            values = [ph[phase] for ph in merged if ph.get(phase) is not None]
            rng = quantile_range(values, 0.75)
            out[metric].append((end.date().isoformat(), percentile(values, 0.75) if values else None, len(values),
                                rng[0] if rng else None))
        shipped = [d for d in deps if lo < d["finished"] <= hi]
        bad = sum(1 for d in shipped if d["id"] in failed)
        rate = bad / len(shipped) if shipped else None
        out["change_failure_rate"].append((end.date().isoformat(), rate, len(shipped),
                                           round(wilson(bad, len(shipped))[0], 4) if shipped else None))
    return out


def _level(value: float | None, n: int, limit: float, low: float | None = None) -> str:
    if value is None or n < MIN_N:
        return "not enough data"
    if value > limit:
        # Over, but the likely range still reaches under the limit: a heads-up until the evidence settles it.
        return "miss" if low is None or low > limit else "heads_up"
    return "heads_up" if value >= HEADS_UP * limit else "ok"


def evaluate(values: dict[str, tuple], limits: dict, previous: dict) -> tuple[dict, list[dict]]:
    """(new state, events) from today's (value, n) per metric: an event when a level rises, and "recovered" when a
    metric that missed is back to ok."""
    state, events = {}, []
    for metric, limit in limits.items():
        value, n, *rest = values.get(metric, (None, 0))
        before = previous.get(metric) or {}
        last = before.get("verdict") or "ok"  # the last real verdict: a quiet week without data changes nothing
        level = _level(value, n, limit, rest[0] if rest else None)
        # An open miss stays a miss while the value stays over the limit, however its range moves.
        if level == "heads_up" and before.get("open") and value is not None and value > limit:
            level = "miss"
        now = {"level": level, "verdict": last if level == "not enough data" else level, "open": before.get("open", False),
               "value": value, "n": n}
        if level in LEVELS[1:] and LEVELS.index(level) > LEVELS.index(last):
            events.append({"metric": metric, "level": level, "value": value, "limit": limit, "n": n})
            now["open"] = now["open"] or level == "miss"
        elif level == "ok" and before.get("open"):
            events.append({"metric": metric, "level": "recovered", "value": value, "limit": limit, "n": n})
            now["open"] = False
        state[metric] = now
    return state, events


def replay(history: dict[str, list[tuple]], limits: dict) -> dict[str, int]:
    """How many alerts each threshold would have sent over the stored days."""
    fired = {m: 0 for m in limits}
    state = {}
    for k in range(max((len(v) for v in history.values()), default=0)):
        today = {m: tuple(history[m][k][1:]) for m in limits if m in history and k < len(history[m])}
        state, events = evaluate(today, limits, state)
        for e in events:
            fired[e["metric"]] += 1
    return fired


def _fmt(metric: str, value) -> str:
    return f"{value:.0%}" if metric == "change_failure_rate" else f"{value:.1f}"


def message(events: list[dict], repo: str, links=()) -> dict:
    words = {"heads_up": "heads-up: near its limit", "miss": "over its limit", "recovered": "back under its limit"}
    unsure = "heads-up: past its limit, but its likely range still reaches under it"
    lines = [f"- **{NAMES[e['metric']]}** {unsure if e['level'] == 'heads_up' and e['value'] > e['limit'] else words[e['level']]}: "
             f"{_fmt(e['metric'], e['value'])} against {_fmt(e['metric'], e['limit'])} (n={e['n']})." for e in events]
    return chat.message(f"StackVitals alerts for {repo} (last {WINDOW_DAYS} days)", lines, links,
                        {"repo": repo, "alerts": events})


def send(url: str, events: list[dict], repo: str, client: httpx.Client | None = None, links=()) -> str | None:
    """Post the alerts in the chat's own shape; trouble comes back as text for the job summary."""
    return chat.post(url, message(events, repo, links), client, "the alert webhook")


STATE = "alerts/state.json"
ISSUE_TITLE = "StackVitals: delivery alerts"
ISSUE_LABEL = "stackvitals"


def _issue_body(state: dict, limits: dict) -> str:
    words = {"ok": "ok", "heads_up": "near its limit", "miss": "over its limit", "not enough data": "not enough data"}
    lines = [f"Delivery numbers over the last {WINDOW_DAYS} days against this repo's thresholds:", ""]
    for metric, limit in limits.items():
        s = state[metric]
        value = "-" if s.get("value") is None else _fmt(metric, s["value"])
        lines.append(f"- {NAMES[metric]}: {value} against {_fmt(metric, limit)} (n={s.get('n', 0)}): {words[s['level']]}")
    lines += ["", "Change the thresholds under [alerts] in .github/stackvitals.toml (0 turns one off). This issue is kept "
              "up to date and closed when every number is back under its limit."]
    return "\n".join(lines)


def _sync_issue(api, state: dict, limits: dict) -> None:
    found = [i for i in api._get(f"/repos/{api.repo}/issues", {"labels": ISSUE_LABEL, "state": "open", "per_page": 100}) or []
             if i.get("title") == ISSUE_TITLE and "pull_request" not in i]
    bad = any(state[m]["verdict"] in ("heads_up", "miss") for m in limits)
    body = _issue_body(state, limits)
    if found and not bad:
        api.send("PATCH", f"/repos/{api.repo}/issues/{found[0]['number']}", {"body": body, "state": "closed",
                                                                          "state_reason": "completed"})
    elif found:
        api.send("PATCH", f"/repos/{api.repo}/issues/{found[0]['number']}", {"body": body})
    elif bad:
        api.send("POST", f"/repos/{api.repo}/issues", {"title": ISSUE_TITLE, "body": body, "labels": [ISSUE_LABEL]})


def alerts_step(ws, env: dict, now: datetime, make_api=None, client: httpx.Client | None = None) -> dict | None:
    """The Action's alerts after Team Flow (the schedule): today's numbers against the thresholds, sent once per change of
    state; the stored state keeps levels only, so a run where nothing crossed a line commits nothing."""
    import json

    from stackvitals.ci.store import DataStore
    from stackvitals.core.config import parse
    from stackvitals.core.delivery import apply_identity, shipped
    from stackvitals.flow.store import FlowStore
    if ws.results.get("Team Flow") is None:
        return None
    cfg = ws.cache.get("settings") or parse("")[0]
    limits = thresholds(cfg)
    if not limits:
        return None
    store = FlowStore(ws.path)
    from stackvitals.core.decisions import visible
    flow = visible(ws.path, apply_identity(ws.cache.get("flow") or store.load(), cfg.get("identity")), now.date())
    ci = ws.cache.get("ci") or (DataStore(ws.path).load() if (ws.path / "ci" / "days").is_dir() else {"runs": [], "jobs": []})
    issues = []
    if (ws.path / "community" / "issues").is_dir():
        got = FlowStore(ws.path, "community/issues").load()
        issues = got["open"] + got["closed"]
    info = store.repo()
    deps, _source, rows = shipped(flow, info, ci, cfg)
    from stackvitals.connectors import active, public
    from stackvitals.connectors import load as load_tracker
    from stackvitals.core.delivery import incidents_for
    tracker = ws.cache.get("tracker") or load_tracker(ws.path, redact=public(ws), names=active(env, cfg))
    incidents = incidents_for(flow["closed"] + flow["open"], issues, deps, cfg, tracker, info.get("recorded"))[0]
    history = series(rows, deps, incidents, now)
    # Whole days only for the app's "would have fired" preview, so the published file changes at most once a day.
    from stackvitals.core.store import published, write_if_changed
    daily = series(rows, deps, incidents, now.replace(hour=0, minute=0, second=0, microsecond=0))
    (ws.path / "docs").mkdir(parents=True, exist_ok=True)
    write_if_changed(ws.path / "docs" / "alerts.json", published({
        "window_days": WINDOW_DAYS, "heads_up": HEADS_UP, "min_n": MIN_N, "limits": limits, "names": NAMES,
        "series": {m: [[d, None if v is None else round(v, 3), n, None if low is None else round(low, 3)]
                       for d, v, n, low in points] for m, points in daily.items()}}))
    today = {m: tuple(history[m][-1][1:]) for m in limits}
    path = ws.path / STATE
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = {}
    state, events = evaluate(today, limits, old.get("metrics") or {})
    fired = replay(history, limits) if old.get("limits") != limits else None
    notes, channels = [], cfg["alerts"]["channels"]
    if events and "webhook" in channels and env.get("STACKVITALS_WEBHOOK"):
        app = chat.app_url(ws.repo, ws.cache.get("repo_info"), "delivery")
        links = [("Open Delivery", app)] if app else []
        links.append(("Alerts issue", f"https://github.com/{ws.repo}/issues?q=is%3Aissue+label%3Astackvitals+alerts"))
        failed = send(env["STACKVITALS_WEBHOOK"], events, ws.repo, client=client, links=links)
        if failed:
            notes.append(failed)
    if (events or fired is not None) and "issue" in channels:
        if make_api is None:
            from stackvitals.ci.api import ActionsAPI as make_api
        try:
            _sync_issue(make_api(env.get("STACKVITALS_TOKEN"), ws.repo, max_requests=10), state, limits)
        except Exception as exc:  # noqa: BLE001 - a missing permission must not stop the job
            notes.append(f"Could not update the alerts issue ({type(exc).__name__}); it needs `issues: write`.")
    keep = {"limits": limits, "metrics": {m: {"verdict": s["verdict"], "open": s["open"]} for m, s in state.items()}}
    if keep != old:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(keep, indent=1, sort_keys=True), encoding="utf-8")

    def after_commit():
        summary = env.get("GITHUB_STEP_SUMMARY")
        if not summary or not (events or fired is not None or notes):
            return
        lines = []
        if events:
            lines.append(chat.text(message(events, ws.repo)))
        if fired is not None:
            lines.append("With these thresholds, alerts would have fired " + ", ".join(
                f"{n} times for {NAMES[m]}" for m, n in fired.items()) + f" over the last 90 days (n of each day's {WINDOW_DAYS}-day window shown with every alert).")
        lines += notes
        with open(summary, "a", encoding="utf-8") as f:
            f.write("### StackVitals alerts\n" + "\n\n".join(lines) + "\n")
    ws.after_commit(after_commit, "Alerts")
    return {"events": len(events), "levels": {m: s["level"] for m, s in state.items()}, "would_have_fired": fired}
