import math
import re
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from stackvitals.ci import monitors
from stackvitals.ci.kinds import kind_of
from stackvitals.ci.bench import push_stats, push_stats_by, push_window
from stackvitals.ci.triggers import PR_EVENTS
from stackvitals.core import changes
from stackvitals.core.stats import fisher
from stackvitals.core.stats import median as _median
from stackvitals.core.stats import percentile as _pct
from stackvitals.core.stats import wilson
from stackvitals.core.time import parse as _t
from stackvitals.core.time import secs as _secs
from stackvitals.core.time import week_of
from stackvitals.core.config import DEFAULTS

FAIL = {"failure", "timed_out"}
PASS = {"success"}
# Detection rules, the same shape the paid tools describe: on after 2 flakes, off after 2 quiet weeks.
FLAKY_MIN_EVENTS = 2
QUIET_DAYS = 14
QUIET_RUNS = 10
OUTAGE_MIN_JOBS = 5
OUTAGE_SHARE = 0.8
BROKEN_RUNS = 3
SAME_CODE_EVENTS = {"push", "pull_request", "pull_request_target", "merge_group"}
# States the dashboard lists, so each gets a history page (at most MAX_HISTORY per kind, the worst first).
SHOWN = {"flaky", "suspect", "broken"}
MAX_HISTORY = 100


def _os(labels: list[str]) -> str:
    text = " ".join(labels).lower()
    for name in ("windows", "macos"):
        if name in text:
            return name
    return "linux" if ("ubuntu" in text or "linux" in text) else "other"


def _failed_step(job: dict) -> str:
    return next((s[1] for s in job.get("steps") or [] if s[2] in FAIL), "unknown step")


# A flake's start is called clear only with this many clean runs before it and a difference chance can't explain.
BEGAN_MIN_RUNS = 20


def _began(times: list, flakes: list, pushes: list) -> dict | None:
    """When a job or test began to flake: its first flake, its runs before and after it, Fisher's test of "never
    before, often after" against chance, and the commits that reached the default branch in the day before it."""
    if not flakes:
        return None
    first = min(flakes)
    before = sum(1 for t in times if t < first)
    after = max(len(times) - before, len(flakes))
    p = fisher(0, before, len(flakes), after)
    landed = []
    for t, sha in pushes:
        if first - timedelta(days=1) <= t <= first and sha not in landed:
            landed.append(sha)
    return {"first": first.strftime("%Y-%m-%dT%H:%M:%SZ"), "runs_before": before, "runs_after": after,
            "flakes": len(flakes), "p": round(p, 4), "clear": before >= BEGAN_MIN_RUNS and p < 0.05, "landed": landed[-5:]}


def _pushes(runs: dict, final_att: dict, default_branch: str | None) -> list:
    """(when, commit) of each push to the default branch, oldest first."""
    return sorted((_t(r["cr"]), r["sha"]) for (rid, att), r in runs.items() if att == final_att[rid] and r.get("sha")
                  and r.get("ev") == "push" and default_branch is not None and r.get("br") == default_branch)


def _only_pr(prs: list) -> int | None:
    """The one pull request every flake came from (each flake's pull request numbers), else None."""
    found = {tuple(p) for p in prs}
    only = found.pop() if len(found) == 1 else ()
    return only[0] if len(only) == 1 else None


def _state(ev_all: list, ev_win: list, runs_since: int, broken: bool, now: datetime) -> str:
    if broken:
        return "broken"
    last = ev_all[-1][0] if ev_all else None
    if len(ev_win) >= FLAKY_MIN_EVENTS or (len(ev_all) >= FLAKY_MIN_EVENTS and (now - last).days < QUIET_DAYS):
        return "flaky"
    if len(ev_all) >= FLAKY_MIN_EVENTS and runs_since >= QUIET_RUNS:
        return "fixed"
    return "suspect" if ev_win else "ok"


def _tests(data: dict, runs: dict, final_att: dict, since: datetime, now: datetime, default_branch: str | None,
           config: dict | None = None, previous: dict | None = None) -> tuple[list, list, int, dict]:
    """Flaky, broken and slow tests from the test reports found in run artifacts."""
    # Run and job ids inside artifact names (6+ digits) would make every run a new suite; shard numbers stay.
    reports = [{**r, "name": re.sub(r"\d{6,}", "#", r.get("name") or "")} for r in data.get("tests") or []
               if (r["run"], r["att"]) in runs]
    when = {id(r): _t(runs[(r["run"], r["att"])]["cr"]) for r in reports}
    # Indexed once: the loops below used to rebuild these sets for every test id and report.
    failed_ids = {id(r): {f[0] for f in r["failed"]} for r in reports}
    outage = {id(r) for r in reports if r["total"] >= 10 and len(r["failed"]) / r["total"] >= OUTAGE_SHARE}
    events, messages, suite = defaultdict(list), defaultdict(Counter), {}
    by_attempt = defaultdict(list)
    for r in reports:
        by_attempt[(r["run"], r["att"])].append(r)
        for f in r["failed"]:
            tid, msg = f[0], f[2]
            messages[tid][msg] += 1
            suite.setdefault(tid, r["name"])
        for tid in r["flaky"]:
            suite.setdefault(tid, r["name"])
            # Retried and passed inside one job: the report itself proves the flake.
            if id(r) not in outage:
                events[tid].append((when[id(r)], "in_job", runs[(r["run"], r["att"])].get("pr") or [],
                                    {"run": r["run"], "att": r["att"], "kind": "in_job", "variant": r["name"]}))
    # A later attempt of the same run with the same report passed the test: one flake per run, like jobs.
    counted = set()
    for rid, last in final_att.items():
        for att in range(1, last):
            for r in by_attempt.get((rid, att), []):
                if id(r) in outage:
                    continue
                later = [o for a in range(att + 1, last + 1) for o in by_attempt.get((rid, a), []) if o["name"] == r["name"]]
                for f in r["failed"]:
                    tid = f[0]
                    if (rid, tid) not in counted and any(tid not in {f[0] for f in o["failed"]} for o in later):
                        counted.add((rid, tid))
                        events[tid].append((when[id(r)], "retry", runs[(rid, att)].get("pr") or [],
                                            {"run": rid, "att": att, "kind": "retry", "variant": r["name"]}))
    # The same code passed the test in another push or PR run.
    finals = defaultdict(list)
    for r in reports:
        run = runs[(r["run"], r["att"])]
        if r["att"] == final_att[r["run"]] and run.get("tree") and run.get("ev") in SAME_CODE_EVENTS:
            # Same branch or tag too: workflows often act on the ref (version checks on tags, deploys on main).
            finals[(run["tree"], run["ev"], run.get("br"), r["name"])].append(r)
    for group in finals.values():
        failed_by = defaultdict(list)
        for r in group:
            if id(r) not in outage:
                for f in r["failed"]:
                    failed_by[f[0]].append(r)
        for tid, bad in failed_by.items():
            if any(tid not in failed_ids[id(r)] for r in group):
                r = max(bad, key=lambda x: when[id(x)])
                events[tid].append((when[id(r)], "flip", runs[(r["run"], r["att"])].get("pr") or [],
                                    {"run": r["run"], "att": r["att"], "kind": "flip", "variant": r["name"]}))
    final_reports = sorted((r for r in reports if r["att"] == final_att[r["run"]]), key=lambda r: when[id(r)])
    # Per suite, once: its reports, the ones in the window, the ones on the default branch, and their times in order.
    by_name, win_by_name, default_by_name, times_by_name = defaultdict(list), {}, {}, {}
    for r in final_reports:
        by_name[r["name"]].append(r)
    for name, mine in by_name.items():
        win_by_name[name] = [r for r in mine if when[id(r)] >= since]
        default_by_name[name] = [r for r in mine if default_branch is None or runs[(r["run"], r["att"])].get("br") == default_branch]
        times_by_name[name] = [when[id(r)] for r in mine]
    fail_win = Counter()
    pass_ms, fail_ms = defaultdict(list), defaultdict(list)
    for r in final_reports:
        if when[id(r)] >= since:
            for tid in failed_ids[id(r)]:
                if suite.get(tid) == r["name"]:
                    fail_win[tid] += 1
            for tid, ms in r["slow"]:
                if tid not in failed_ids[id(r)]:
                    pass_ms[tid].append(ms)
            for f in r["failed"]:
                if len(f) > 6 and f[6] is not None:
                    fail_ms[f[0]].append(f[6])
    cfg = config or DEFAULTS
    mon = cfg["ci"]["monitors"]
    # The monitors look at the newest default-branch results only, so big suites stay fast.
    hist_n = max(int(mon["failure_rate"]["window_runs"]), int(mon["broken"]["window_runs"]), int(mon["broken"]["streak"]), 1)
    out, history, pushes = [], {}, _pushes(runs, final_att, default_branch)
    for tid in sorted(set(messages) | set(events)):
        name = suite.get(tid)
        mine, win, default = by_name.get(name, []), win_by_name.get(name, []), default_by_name.get(name, [])
        ev_all = sorted(events.get(tid, []), key=lambda e: e[0])
        ev_win = [e for e in ev_all if e[0] >= since]
        last = ev_all[-1][0] if ev_all else None
        runs_since = len(mine) - bisect_right(times_by_name.get(name, []), last) if last else 0
        hist = [(when[id(r)], tid in failed_ids[id(r)]) for r in default[-hist_n:]]
        status = monitors.evaluate(ev_all, ev_win, hist, runs_since, now, cfg, (previous or {}).get(tid),
                                   pass_ms.get(tid, ()), fail_ms.get(tid, ()), tid)
        lo, hi = wilson(len(ev_win), len(win))
        main_win = [r for r in default if when[id(r)] >= since]
        out.append({"id": tid, "suite": name, "runs": len(win),
                    # Its record on the default branch, so a first failure on a pull request can be checked against it.
                    "main_runs": len(main_win), "main_failures": sum(tid in failed_ids[id(r)] for r in main_win),
                    "workflow": runs[(mine[-1]["run"], mine[-1]["att"])].get("path") if mine else None,
                    "failures": fail_win[tid],
                    "flake_events": len(ev_win), "flake_rate": round(len(ev_win) / len(win), 4) if win else 0.0,
                    "rate_low": round(lo, 4), "rate_high": round(hi, 4),
                    "state": status["state"], "monitors": status["monitors"], "labels": status["labels"],
                    "since": status["since"], "failure_rate": status["failure_rate"],
                    **({"muted_until": status["muted_until"]} if status.get("muted_until") else {}),
                    "last_flake": last.strftime("%Y-%m-%dT%H:%M:%SZ") if last else None,
                    "message": messages[tid].most_common(1)[0][0] if messages[tid] else None,
                    # What kind of flake its usual failure looks like (timing, network, ...), only once it has flaked.
                    "flake": kind_of(messages[tid].most_common(1)[0][0]) if messages[tid] and ev_all else None,
                    "prs_affected": sorted({p for e in ev_win for p in e[2]}),
                    # Flakes from one pull request alone are that change's (a race it added), not a known flake.
                    "only_pr": _only_pr([e[2] for e in ev_win]),
                    # Which report (an OS or version in a matrix) the window's flakes came from.
                    "variants": dict(Counter(e[3].get("variant") for e in ev_win if e[3].get("variant")).most_common(5)),
                    # The newest runs that prove it, so anyone can open them.
                    "evidence": [{k: v for k, v in e[3].items() if k != "variant"} for e in ev_all[-5:]],
                    # The window's attempts it flaked in, for its cost (taken off before the page is written).
                    "_attempts": sorted({(e[3]["run"], e[3]["att"]) for e in ev_win if e[3].get("run")})[-50:],
                    "began": _began(times_by_name.get(name, []), [e[0] for e in ev_all], pushes)})
    # History pages only for the tests that get one (the worst MAX_HISTORY): building rows for every shown test cost
    # tests x reports on big suites.
    order = {"flaky": 0, "broken": 1, "suspect": 2}
    worst = sorted((t for t in out if t["state"] in SHOWN), key=lambda t: (order.get(t["state"], 3), -t["flake_events"]))
    for t in worst[:MAX_HISTORY]:
        tid = t["id"]
        flaked = {e[3]["run"]: e[3] for e in sorted(events.get(tid, []), key=lambda e: e[0])}
        history[tid] = [_row(runs[(r["run"], r["att"])], flaked, tid not in failed_ids[id(r)]) for r in by_name.get(suite.get(tid), [])]
    durations = defaultdict(list)
    for r in final_reports:
        if when[id(r)] >= since:
            for tid, ms in r["slow"]:
                durations[tid].append((when[id(r)], ms))
    slow = []
    for tid, items in durations.items():
        values = [ms for _, ms in items]
        recent = [ms for t, ms in items if t >= now - timedelta(days=7)]
        before = [ms for t, ms in items if t < now - timedelta(days=7)]
        slower = None
        if len(recent) >= 5 and len(before) >= 5:
            a, b = _median(before), _median(recent)
            if b >= a * 1.25 and b - a >= 5000:
                slower = {"before_ms": a, "after_ms": b, "pct": round((b / a - 1) * 100)}
        slow.append({"id": tid, "median_ms": _median(values), "p95_ms": _pct(values, 0.95), "samples": len(values),
                     "slower": slower, "trend": _trend(items)})
    slow.sort(key=lambda s: -(s["median_ms"] or 0))
    outages = len({r["run"] for r in reports if id(r) in outage and when[id(r)] >= since})
    return out, slow[:20], outages, history


MAX_GROUPS = 50
NEW_DAYS, NEW_SHOWN, SKIP_SHOWN, NEW_SKIP_DAYS = 14, 50, 100, 7
# Runs of this repo's own branch: pull request events (forks too) can carry a branch named like the default one.
OWN_EVENTS = {"push", "schedule", "workflow_dispatch", None}


def _trend(items) -> list:
    """Daily medians of (time, value) pairs, oldest first."""
    by_day = defaultdict(list)
    for when, value in items:
        by_day[when.strftime("%Y-%m-%d")].append(value)
    return [[d, _median(v)] for d, v in sorted(by_day.items())]


def _inventory(data: dict, runs: dict, final_att: dict, now: datetime, default_branch: str | None, tests: list[dict]) -> tuple[list, list]:
    """Tests added in the last two weeks and how they have done since; tests skipped now and since when."""
    reports = sorted(({**r, "name": re.sub(r"\d{6,}", "#", r.get("name") or "")} for r in data.get("tests") or []
                      if (r["run"], r["att"]) in runs), key=lambda r: runs[(r["run"], r["att"])]["cr"])
    finals = [r for r in reports if r["att"] == final_att[r["run"]]]
    first = {}
    for r in reports:
        for tid in r.get("new") or []:
            first.setdefault(tid, (runs[(r["run"], r["att"])]["cr"], r["name"]))
    state = {t["id"]: t for t in tests}
    new = []
    for tid, (when, name) in first.items():
        if _t(when) < now - timedelta(days=NEW_DAYS):
            continue
        since = [r for r in finals if r["name"] == name and runs[(r["run"], r["att"])]["cr"] >= when]
        t = state.get(tid) or {}
        new.append({"id": tid, "suite": name, "first": when, "runs": len(since),
                    "failures": sum(1 for r in since if any(f[0] == tid for f in r["failed"])),
                    "flake_events": t.get("flake_events", 0), "state": t.get("state", "ok")})
    # Newest first, and the ones already failing or flaky above the rest.
    new.sort(key=lambda x: x["first"], reverse=True)
    new.sort(key=lambda x: x["state"] == "ok")
    # Skips: only reports that carry a skip list prove anything, and only the default branch's.
    listed = defaultdict(list)
    for r in finals:
        run = runs[(r["run"], r["att"])]
        if "sk" in r and run.get("ev") in OWN_EVENTS and (default_branch is None or run.get("br") == default_branch):
            listed[r["name"]].append(r)
    found = {}
    for name, rs in listed.items():
        sets = [set(r["sk"]) for r in rs]
        for tid in rs[-1]["sk"]:
            k = len(rs) - 1
            while k > 0 and tid in sets[k - 1]:
                k -= 1
            since = runs[(rs[k]["run"], rs[k]["att"])]["cr"]
            fresh = k > 0 and _t(since) >= now - timedelta(days=NEW_SKIP_DAYS)
            # One row per test across matrix jobs: skipped since the earliest, new only if new everywhere.
            if tid in found:
                t = found[tid]
                t["suites"] += 1
                t["new"] = t["new"] and fresh
                t["since"] = min(t["since"], since)
            else:
                found[tid] = {"id": tid, "suite": name, "suites": 1, "since": since, "new": fresh}
    skipped = [{**t, "days": (now - _t(t["since"])).days} for t in found.values()]
    skipped.sort(key=lambda x: (not x["new"], -x["days"], x["id"]))
    return new[:NEW_SHOWN], skipped[:SKIP_SHOWN]


PRS_SHOWN = 50


def _coverage(data: dict, runs: dict, now: datetime, since: datetime, default_branch: str | None) -> dict | None:
    """Line coverage on the default branch (latest, daily trend, change over the window) and each pull request's latest
    patch coverage; a run's widest report counts (matrix jobs measure the same code)."""
    best = {}
    for r in data.get("tests") or []:
        run = runs.get((r["run"], r["att"]))
        if run and r.get("cov") and r["cov"].get("lines") and (r["run"] not in best or r["cov"]["lines"] > best[r["run"]][1]["cov"]["lines"]):
            best[r["run"]] = (run, r)
    if not best:
        return None
    pct = lambda c: round(c["covered"] / c["lines"], 4) if c.get("lines") else None  # noqa: E731
    main = sorted(((run, r) for run, r in best.values() if run.get("ev") in OWN_EVENTS
                   and (default_branch is None or run.get("br") == default_branch)), key=lambda x: x[0]["cr"])
    trend = _trend((_t(run["cr"]), pct(r["cov"])) for run, r in main)
    in_window = [pct(r["cov"]) for run, r in main if _t(run["cr"]) >= since]
    latest = main[-1] if main else None
    prs = {}
    for run, r in sorted(best.values(), key=lambda x: x[0]["cr"]):
        p = r.get("patch")
        if p and p.get("pr") and _t(run["cr"]) >= since:
            prs[p["pr"]] = {"pr": p["pr"], "lines": p["lines"], "covered": p["covered"],
                            "pct": round(p["covered"] / p["lines"], 4) if p["lines"] else None, "missed": p.get("missed") or {},
                            "at": run["cr"]}
    return {"latest": {"pct": pct(latest[1]["cov"]), "lines": latest[1]["cov"]["lines"], "covered": latest[1]["cov"]["covered"],
                       "format": latest[1]["cov"].get("format"), "at": latest[0]["cr"], "run": latest[0]["id"]} if latest else None,
            "trend": trend, "change": round(in_window[-1] - in_window[0], 4) if len(in_window) >= 2 else None,
            "prs": sorted(prs.values(), key=lambda x: x["at"], reverse=True)[:PRS_SHOWN]}


def _groups(data: dict, runs: dict, final_att: dict, since: datetime, tests: list[dict]) -> list[dict]:
    """Failures with one cause (same root exception at the same place), across tests and runs, in the window; each
    test also names the group it most often fails with. Records saved before causes existed are left out."""
    seen = defaultdict(lambda: {"failures": 0, "tests": Counter(), "runs": set(), "first": None, "last": None,
                                "messages": Counter(), "examples": []})
    for r in sorted(data.get("tests") or [], key=lambda r: runs.get((r["run"], r["att"]), {}).get("cr") or ""):
        run = runs.get((r["run"], r["att"]))
        if not run or r["att"] != final_att.get(r["run"]) or _t(run["cr"]) < since:
            continue
        for f in r["failed"]:
            if len(f) < 6 or not f[3]:
                continue
            g = seen[f[3]]
            g["failures"] += 1
            g["tests"][f[0]] += 1
            g["runs"].add(r["run"])
            g["first"] = g["first"] or run["cr"]
            g["last"] = run["cr"]
            g["messages"][f[2]] += 1
            g.update(where=f[4], type=f[5])
            g["examples"] = ([{"run": r["run"], "att": r["att"], "test": f[0]}] + g["examples"])[:5]
    out = [{"id": cid, "type": g["type"], "where": g["where"], "message": g["messages"].most_common(1)[0][0],
            "failures": g["failures"], "tests": len(g["tests"]), "runs": len(g["runs"]), "first": g["first"],
            "last": g["last"], "top_tests": [t for t, _ in g["tests"].most_common(5)], "examples": g["examples"]}
           for cid, g in seen.items()]
    out.sort(key=lambda g: (-g["tests"], -g["failures"], g["id"]))
    usual = {}
    for cid, g in seen.items():
        for tid, n in g["tests"].items():
            if n > usual.get(tid, (0, None))[0]:
                usual[tid] = (n, cid)
    for t in tests:
        if t["id"] in usual:
            t["group"] = usual[t["id"]][1]
    return out[:MAX_GROUPS]


def _worst(history: dict, items: list[dict], key) -> dict:
    # Flaky first, then keeps failing, then one-off flakes; the most flakes first within each.
    order = {"flaky": 0, "broken": 1, "suspect": 2}
    ranked = sorted((i for i in items if key(i) in history), key=lambda i: (order.get(i["state"], 3), -i["flake_events"]))
    return {key(i): history[key(i)] for i in ranked[:MAX_HISTORY]}


def _job_reads_pr(name: str, jobs) -> bool:
    # A matrix job is shown as "name (a, b)".
    return any(name == j or name.startswith(j + " (") for j in jobs)


def _row(run: dict, flaked: dict, passed: bool) -> list:
    # One run on a history page: when, which attempt to open (the flaky one if any), passed, flake kind, branch, event.
    ev = flaked.get(run["id"])
    return [run["cr"], run["id"], ev["att"] if ev else run["att"], passed, ev["kind"] if ev else None, run.get("br"), run.get("ev")]


def _downstream(job: dict, attempt_jobs: list[dict]) -> bool:
    # A gatekeeper job (alls-green, "Status") fails because another job already failed or was cancelled.
    start = _t(job.get("st"))
    return bool(start) and any(o is not job and (o["c"] in FAIL or o["c"] == "cancelled") and _t(o.get("en"))
                               and _t(o["en"]) <= start for o in attempt_jobs)


def analyze(data: dict, now: datetime, window_days: int = 30, default_branch: str | None = None,
            pr_metadata: dict | None = None, config: dict | None = None, previous: dict | None = None,
            pr_edits: set | None = None, attempts: bool = False) -> dict:
    """pr_metadata: {workflow path: job names} for jobs that read the PR's title, description or labels in workflows that
    also run on PR edits or labels; the same code may pass and fail there, so those flips are not flakes. pr_edits: the
    workflows that run on PR edits, published so a failure verdict can say "fix the PR"."""
    pr_metadata = pr_metadata or {}
    since = now - timedelta(days=window_days)
    runs = {(r["id"], r["att"]): r for r in data["runs"]}
    final_att = {}
    for rid, att in runs:
        final_att[rid] = max(att, final_att.get(rid, 0))
    by_attempt = defaultdict(list)
    for j in data["jobs"]:
        by_attempt[(j["run"], j["att"])].append(j)

    def key(rid, name):
        return (runs[(rid, final_att[rid])].get("path"), name)

    events = defaultdict(list)  # (path, job) -> [(time, kind, failing step, minutes lost, pr numbers)]
    infra = set()
    # Signal 1: an attempt failed and a later attempt of the same run passed.
    for rid, last in final_att.items():
        outcome = {}
        outage = set()
        for att in range(1, last + 1):
            jobs = [j for j in by_attempt.get((rid, att), []) if j["c"] in FAIL | PASS]
            if len(jobs) >= OUTAGE_MIN_JOBS and sum(j["c"] in FAIL for j in jobs) / len(jobs) >= OUTAGE_SHARE:
                outage.add(att)
            for j in jobs:
                outcome.setdefault(j["n"], []).append((att, j))
        for name, seq in outcome.items():
            fails = [(a, j) for a, j in seq if j["c"] in FAIL]
            passes = [a for a, j in seq if j["c"] in PASS]
            if not fails or not passes or min(fails, key=lambda x: x[0])[0] > max(passes):
                continue
            att, failed = min(fails, key=lambda x: x[0])
            if att in outage:
                infra.add(rid)
                continue
            if _downstream(failed, by_attempt.get((rid, att), [])):
                continue
            run = runs.get((rid, att)) or runs[(rid, final_att[rid])]
            lost = (_secs(failed["st"], failed["en"]) or 0) / 60
            events[key(rid, name)].append((_t(failed["en"]) or _t(run["cr"]), "retry", _failed_step(failed), lost,
                                           run.get("pr") or [], {"run": rid, "att": att, "job": failed["id"], "kind": "retry"}))
    # Signal 2: final results differ on the same code (tree) for the same event type.
    finals = defaultdict(lambda: defaultdict(list))
    for rid, last in final_att.items():
        run = runs[(rid, last)]
        for j in by_attempt.get((rid, last), []):
            if j["c"] in FAIL | PASS:
                finals[key(rid, j["n"])][(run.get("tree"), run.get("ev"), run.get("br"))].append((run, j))
    for k, groups in finals.items():
        for (tree, ev, _ref), items in groups.items():
            # Scheduled and triggered runs on the same code can differ for real reasons (inputs, upstream runs).
            reads_pr = ev in PR_EVENTS and _job_reads_pr(k[1], pr_metadata.get(k[0], ()))
            if not tree or ev not in SAME_CODE_EVENTS or reads_pr:
                continue
            failed = [(r, j) for r, j in items if j["c"] in FAIL and r["id"] not in infra
                      and not _downstream(j, by_attempt.get((r["id"], r["att"]), []))]
            if failed and any(j["c"] in PASS for _, j in items):
                r, j = max(failed, key=lambda x: x[0]["cr"])
                events[k].append((_t(j["en"]) or _t(r["cr"]), "flip", _failed_step(j), 0.0, r.get("pr") or [],
                                  {"run": r["id"], "att": r["att"], "job": j["id"], "kind": "flip"}))

    out_jobs, queue, minutes, job_history = [], [], Counter(), {}
    pushes = _pushes(runs, final_att, default_branch)
    for k in sorted(finals):
        path, name = k
        items = sorted(((r, j) for g in finals[k].values() for r, j in g), key=lambda x: (x[0]["cr"], x[0]["id"]))
        in_window = [(r, j) for r, j in items if _t(r["cr"]) >= since]
        ev_all = sorted(events.get(k, []), key=lambda e: e[0])
        ev_win = [e for e in ev_all if e[0] >= since]
        last_event = ev_all[-1][0] if ev_all else None
        runs_since = sum(1 for r, _ in items if last_event and _t(r["cr"]) > last_event)
        default = [j for r, j in items if default_branch is None or r.get("br") == default_branch]
        broken = len(default) >= BROKEN_RUNS and all(j["c"] in FAIL for j in default[-BROKEN_RUNS:])
        state = _state(ev_all, ev_win, runs_since, broken, now)
        durations = [(r, s) for r, j in in_window if j["c"] in PASS and (s := _secs(j["st"], j["en"])) is not None]
        recent = [s for r, s in durations if _t(r["cr"]) >= now - timedelta(days=7)]
        before = [s for r, s in durations if _t(r["cr"]) < now - timedelta(days=7)]
        slower = None
        if len(recent) >= 5 and len(before) >= 5:
            a, b = _median(before), _median(recent)
            if b >= a * 1.25 and b - a >= 60:
                slower = {"before_s": a, "after_s": b, "pct": round((b / a - 1) * 100)}
        lo, hi = wilson(len(ev_win), len(in_window))
        steps = Counter(e[2] for e in ev_win)
        main_win = [j for r, j in in_window if default_branch is None or r.get("br") == default_branch]
        out_jobs.append({
            "workflow": path, "job": name, "runs": len(in_window),
            "main_runs": len(main_win), "main_failures": sum(j["c"] in FAIL for j in main_win),
            "failures": sum(1 for _, j in in_window if j["c"] in FAIL),
            "flake_events": len(ev_win), "flake_rate": round(len(ev_win) / len(in_window), 4) if in_window else 0.0,
            "rate_low": round(lo, 4), "rate_high": round(hi, 4), "state": state,
            "last_flake": last_event.strftime("%Y-%m-%dT%H:%M:%SZ") if last_event else None,
            "top_step": steps.most_common(1)[0][0] if steps else None, "flake_steps": sorted(steps),
            "retry_minutes": round(sum(e[3] for e in ev_win), 1),
            "prs_affected": sorted({p for e in ev_win for p in e[4]}), "only_pr": _only_pr([e[4] for e in ev_win]),
            "evidence": [e[5] for e in ev_all[-5:]],
            "median_s": _median([s for _, s in durations]), "p95_s": _pct([s for _, s in durations], 0.95),
            "slower": slower, "trend": _trend((_t(r["cr"]), s) for r, s in durations),
            # Each flake is placed at its run's start, so the run that flaked first counts after it, not before.
            "began": _began([_t(r["cr"]) for r, _j in items],
                            [_t(runs[key]["cr"]) for e in ev_all if (key := (e[5]["run"], e[5]["att"])) in runs], pushes)})
        if state in SHOWN:
            flaked = {e[5]["run"]: e[5] for e in ev_all}
            job_history[f"{path}|{name}"] = [_row(r, flaked, j["c"] in PASS) for r, j in items]
    window_runs = {rid for (rid, att), r in runs.items() if _t(r["cr"]) >= since}
    for (rid, att), jobs in by_attempt.items():
        run = runs.get((rid, att)) or runs.get((rid, final_att.get(rid, att)))
        if not run or rid not in window_runs:
            continue
        for j in jobs:
            q = _secs(j.get("cr"), j.get("st"))
            if q is not None:
                queue.append(q)
            d = _secs(j.get("st"), j.get("en"))
            if d:
                minutes[_os(j.get("lb") or [])] += math.ceil(d / 60)
    reruns = sum(1 for rid in window_runs if final_att[rid] > 1)
    tests, slow_tests, test_outages, test_history = _tests(data, runs, final_att, since, now, default_branch, config, previous)
    failure_groups = _groups(data, runs, final_att, since, tests)
    new_tests, skipped_tests = _inventory(data, runs, final_att, now, default_branch, tests)
    if not attempts:
        # Each flaky test's attempts feed only the Action's cost step, never a page.
        for t in tests:
            t.pop("_attempts", None)
    return {
        "failure_groups": failure_groups,
        "weekly": _weekly(data, finals, events, now),
        "changes": changes.annotate(_changes(data, finals, events, now)),
        "history": {"jobs": _worst(job_history, out_jobs, lambda j: f"{j['workflow']}|{j['job']}"), "tests": test_history},
        "tests": tests, "slow_tests": slow_tests, "test_outages": test_outages,
        "new_tests": new_tests, "skipped_tests": skipped_tests,
        "coverage": _coverage(data, runs, now, since, default_branch),
        "has_test_reports": bool(data.get("tests")),
        "window_days": window_days, "generated": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "default_branch": default_branch,
        "runs": len(window_runs), "rerun_share": round(reruns / len(window_runs), 4) if window_runs else 0.0,
        "infra_events": sum(1 for rid in infra if rid in window_runs),
        "queue": {"median_s": _median(queue), "p95_s": _pct(queue, 0.95)},
        "minutes": {k: minutes.get(k, 0) for k in ("linux", "windows", "macos", "other")},
        "pushes": push_stats(data, now, window_days), "jobs": out_jobs,
        # Workflows run by PR edits, so a failure there about the PR itself reads "fix the PR" (feedback.classify_run).
        "pr_edit_workflows": sorted(set(pr_edits or ()) | {p for p, jobs in pr_metadata.items() if jobs})}


def _changes(data: dict, finals: dict, events: dict, now: datetime) -> list[dict]:
    """This week's first-try green, push wait and flake share against the four weeks before, each judged against how
    much this repo's weeks usually swing."""
    return changes.calibrate(lambda t: _week_checks(data, finals, events, t), now)


def _week_checks(data: dict, finals: dict, events: dict, now: datetime) -> list[dict]:
    (ws, we), (bs, be) = changes.windows(now)
    week, base = push_window(data, ws, we) or {}, push_window(data, bs, be) or {}
    green = lambda p: round((p.get("first_try_share") or 0) * (p.get("pushes") or 0))  # noqa: E731
    # Run and flake times come as text or as datetimes; both compare as UTC text.
    at = lambda v: v.strftime("%Y-%m-%dT%H:%M:%SZ") if isinstance(v, datetime) else v or ""  # noqa: E731
    runs_in = lambda a, b: sum(1 for groups in finals.values() for items in groups.values()  # noqa: E731
                               for r, _j in items if a <= at(r["cr"]) < b)
    flakes_in = lambda a, b: sum(1 for evs in events.values() for e in evs if a <= at(e[0]) < b)  # noqa: E731
    jobs_now, jobs_base = runs_in(ws, we), runs_in(bs, be)
    return [changes.share("ci.first_try_green", "pushes green on the first try", green(week), week.get("pushes") or 0,
                          green(base), base.get("pushes") or 0, better=1),
            changes.times("ci.push_wait", "push to all checks done", [d / 60 for d in week.get("durations") or []],
                          [d / 60 for d in base.get("durations") or []], better=-1, unit="min"),
            changes.share("ci.flake_share", "job runs that flaked", min(flakes_in(ws, we), jobs_now), jobs_now,
                          min(flakes_in(bs, be), jobs_base), jobs_base, better=-1)]


def _weekly(data: dict, finals: dict, events: dict, now: datetime) -> list[dict]:
    """Each week of the kept history: job runs, how many flaked, and the push wait measured like the benchmark."""
    job_runs, flakes = Counter(), Counter()
    for groups in finals.values():
        for items in groups.values():
            for r, _j in items:
                job_runs[week_of(r["cr"])] += 1
    for evs in events.values():
        for e in evs:
            flakes[week_of(e[0])] += 1
    pushes = push_stats_by(data, week_of)
    if not job_runs and not pushes:
        return []
    out, day, last = [], _t(min([*job_runs, *pushes]) + "T00:00:00Z"), week_of(now)
    while (week := day.strftime("%Y-%m-%d")) <= last:
        p = pushes.get(week) or {}
        out.append({"week": week, "job_runs": job_runs[week], "flakes": flakes[week],
                    "flake_share": round(min(100.0, 100 * flakes[week] / job_runs[week]), 2) if job_runs[week] else None,
                    "push_median_s": p.get("median_s"), "first_try_share": p.get("first_try_share")})
        day += timedelta(days=7)
    return out
