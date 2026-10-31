"""Test monitors in Trunk's documented shape: pass-on-retry (failed and passed on the same code) that heals after quiet
days, failure rate and broken with separate switch-on and switch-off thresholds, and slow and timeout-inflation labels.
Each test's status is kept in the data branch with the day it began, and every change is logged."""
from datetime import datetime, timedelta
from fnmatch import fnmatchcase

from stackvitals.core.config import DEFAULTS
from stackvitals.core.stats import median, percentile

ACTIVE = {"flaky", "broken", "suspect"}


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _cluster_start(events: list, quiet: timedelta) -> datetime | None:
    # The first event of the latest unbroken stretch: flakes closer together than the heal time.
    if not events:
        return None
    start = events[-1][0]
    for i in range(len(events) - 1, 0, -1):
        if events[i][0] - events[i - 1][0] >= quiet:
            break
        start = events[i - 1][0]
    return start


def evaluate(ev_all: list, ev_win: list, hist: list[tuple[datetime, bool]], runs_since: int, now: datetime, cfg: dict,
             previous: dict | None = None, pass_ms=(), fail_ms=(), test_id: str | None = None) -> dict:
    """One test's state from its flake events (oldest first), its default-branch results ([(time, failed)], oldest
    first) and, when kept, its previous status; plus labels and a mute."""
    m = (cfg or DEFAULTS)["ci"]["monitors"]
    was = set((previous or {}).get("monitors") or [])
    fails = [f for _, f in hist]
    b = m["broken"]
    window = fails[-int(b["window_runs"]):] if b["window_runs"] else []
    rate_b = sum(window) / len(window) if window else 0.0
    streak = int(b["streak"])
    by_streak = streak > 0 and len(fails) >= streak and all(fails[-streak:])
    broken = by_streak or (len(window) >= b["window_runs"] and rate_b >= b["activate"]) or \
        ("broken" in was and bool(window) and rate_b >= b["resolve"])
    p = m["pass_on_retry"]
    quiet = timedelta(days=p["quiet_days"])
    last = ev_all[-1][0] if ev_all else None
    retry = len(ev_win) >= p["min_events"] or (len(ev_all) >= p["min_events"] and last is not None and now - last < quiet)
    fr = m["failure_rate"]
    win = fails[-int(fr["window_runs"]):] if fr["window_runs"] else []
    rate = sum(win) / len(win) if win else None
    by_rate = bool(fr["enabled"]) and len(win) >= fr["min_runs"] and rate is not None and \
        (rate >= fr["activate"] or ("failure_rate" in was and rate > fr["resolve"]))
    monitors = [name for name, on in (("broken", broken), ("pass_on_retry", retry), ("failure_rate", by_rate)) if on]
    if broken:
        state = "broken"
        if by_streak:
            i = len(fails)
            while i > 0 and fails[i - 1]:
                i -= 1
            since = hist[i][0]
        else:
            since = next(t for t, f in hist[-len(window):] if f)
    elif retry or by_rate:
        state = "flaky"
        since = _cluster_start(ev_all, quiet) if retry else next((t for t, f in hist[-len(win):] if f), None)
    elif ev_win:
        state, since = "suspect", ev_win[0][0]
    elif len(ev_all) >= p["min_events"] and runs_since >= p["quiet_runs"]:
        state, since = "fixed", last
    else:
        state, since = "ok", None
    out = {"state": state, "monitors": monitors, "since": _iso(since) if since else None,
           "failure_rate": round(rate, 4) if rate is not None else None, "labels": []}
    if previous and previous.get("state") == state and previous.get("since"):
        out["since"] = previous["since"]
    pass_ms, fail_ms = [x for x in pass_ms if x is not None], [x for x in fail_ms if x is not None]
    if pass_ms and median(pass_ms) > m["slow"]["p50_ms"]:
        out["labels"].append("slow")
    t = m["timeout_inflation"]
    if pass_ms and len(fail_ms) >= t["min_failures"] and median(fail_ms) >= t["ratio"] * percentile(pass_ms, 0.95):
        out["labels"].append("timeout_inflation")
    today = now.date().isoformat()
    for pattern, until in ((cfg or DEFAULTS)["ci"].get("mute") or {}).items():
        if test_id and until >= today and fnmatchcase(test_id, pattern):
            out["muted_until"] = until
            break
    return out


def transitions(previous: dict, tests: list[dict], now: datetime) -> tuple[dict, list[dict]]:
    """The status file to keep (tests that are flaky, broken or suspect, with the day it began) and the changes since the
    last run, each one line for the transitions log."""
    at = _iso(now)
    previous = previous or {}
    status, changes = {}, []
    current = {t["id"]: t for t in tests}
    for tid in sorted(set(current) | set(previous)):
        t, prev = current.get(tid), previous.get(tid) or {}
        state = t["state"] if t else "ok"
        before = prev.get("state", "ok")
        if state in ACTIVE:
            since = prev["since"] if before == state and prev.get("since") else (t.get("since") or at)
            status[tid] = {"state": state, "since": since, "monitors": t.get("monitors") or []}
        if state != before:
            changes.append({"at": at, "id": tid, "from": before, "to": state, "monitors": (t or {}).get("monitors") or []})
    return status, changes
