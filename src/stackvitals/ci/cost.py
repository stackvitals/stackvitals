"""CI cost: billed minutes and money per workflow and job at GitHub's published per-minute prices (docs.github.com,
"Actions runner pricing", read 2026-10-29), each job rounded up to a whole minute as GitHub bills it; the minutes spent
on attempts that failed and then passed on a re-run (what flaky jobs cost); and, for a public repo, where standard
runners are free, what the same use would cost on a private one. Self-hosted runners count in minutes only."""
import math
import re
from collections import defaultdict
from datetime import datetime, timedelta

# USD per minute: standard runners, then larger ones by OS, architecture and cores.
STANDARD = {"linux": 0.006, "linux arm": 0.005, "windows": 0.010, "windows arm": 0.010, "macos": 0.062}
LARGER = {("linux", 4): 0.012, ("linux", 8): 0.022, ("linux", 16): 0.042, ("linux arm", 4): 0.008,
          ("linux arm", 8): 0.014, ("linux arm", 16): 0.026, ("windows", 8): 0.042, ("windows", 16): 0.082,
          ("windows arm", 8): 0.026, ("windows arm", 16): 0.050}
CORES = re.compile(r"(\d+)[-_ ]?(core|cores|cpu|vcpu)", re.I)


def rate(labels: list[str]) -> tuple[str, float | None]:
    """(runner kind, USD per minute) from a job's runner labels; self-hosted runners have no price."""
    low = [x.lower() for x in labels or []]
    if "self-hosted" in low:
        return "self-hosted", None
    text = " ".join(low)
    os_ = "windows" if "windows" in text else "macos" if "macos" in text or "mac" in text else "linux"
    if os_ != "macos" and ("arm" in text or "aarch64" in text):
        os_ += " arm"
    cores = CORES.search(text)
    if cores and os_ != "macos":
        n = int(cores.group(1))
        size = min((s for (o, s) in LARGER if o == os_ and s >= n), default=None)
        if size:
            return f"{os_} {size}-core", LARGER[(os_, size)]
    if os_ == "macos" and ("xlarge" in text or "large" in text):
        return "macos large", 0.077 if "xlarge" not in text else 0.102
    return os_, STANDARD[os_]


def _minutes(j: dict) -> int:
    try:
        secs = (datetime.fromisoformat(j["en"].replace("Z", "+00:00")) - datetime.fromisoformat(j["st"].replace("Z", "+00:00"))).total_seconds()
    except (KeyError, TypeError, AttributeError, ValueError):
        return 0
    return max(1, math.ceil(secs / 60)) if secs > 0 else 0


def report(data: dict, now: datetime, private: bool, days: int = 30) -> dict:
    since = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    runs = {(r["id"], r["att"]): r for r in data.get("runs") or []}
    jobs = [j for j in data.get("jobs") or [] if (j.get("st") or "") >= since and j.get("en")]
    # A failed attempt followed by a later attempt of the same job that passed: the re-run's cost of a flake.
    passed_later = {(j["run"], j["n"]) for j in jobs if j.get("c") == "success" and j.get("att", 1) > 1}
    by_wf, by_job = defaultdict(lambda: [0, 0.0]), defaultdict(lambda: [0, 0.0, ""])
    by_runner = defaultdict(int)
    minutes = usd = private_usd = rerun_min = rerun_usd = self_hosted = 0
    for j in jobs:
        m = _minutes(j)
        kind, price = rate(j.get("lb"))
        run = runs.get((j["run"], j.get("att", 1))) or runs.get((j["run"], 1)) or {}
        wf = run.get("wfn") or run.get("path") or "unknown workflow"
        # Standard runners are free on public repos; larger runners never are.
        paid = 0.0 if price is None else (m * price if private or kind not in STANDARD else 0.0)
        minutes += m
        usd += paid
        private_usd += 0.0 if price is None else m * price
        by_runner[kind] += m
        if price is None:
            self_hosted += m
        by_wf[wf][0] += m
        by_wf[wf][1] += paid
        key = (wf, j.get("n") or "job")
        by_job[key][0] += m
        by_job[key][1] += paid
        if j.get("c") in ("failure", "timed_out") and (j["run"], j.get("n")) in passed_later:
            rerun_min += m
            rerun_usd += paid
    top = lambda d, label: [{label: k if isinstance(k, str) else k[1], **({"workflow": k[0]} if not isinstance(k, str) else {}),  # noqa: E731
                             "minutes": v[0], "usd": round(v[1], 2)} for k, v in sorted(d.items(), key=lambda kv: -kv[1][0])][:20]
    return {"days": days, "private": private, "minutes": minutes, "usd": round(usd, 2), "private_usd": round(private_usd, 2),
            "rerun_minutes": rerun_min, "rerun_usd": round(rerun_usd, 2), "self_hosted_minutes": self_hosted,
            "by_runner": dict(by_runner), "workflows": top(by_wf, "workflow"), "jobs": top(by_job, "job"),
            "prices_read": "2026-10-29"}


def flaky_tests(data: dict, tests: list[dict], private: bool, most: int = 20) -> list[dict]:
    """What each flaky test cost: the job minutes (and money) of the attempts it flaked in, an attempt's cost split
    evenly between the tests that flaked in it, plus the pull requests it got in the way of; costliest first."""
    by_attempt = defaultdict(list)
    for j in data.get("jobs") or []:
        if j.get("c") in ("failure", "timed_out") and j.get("en"):
            by_attempt[(j["run"], j.get("att", 1))].append(j)
    sharing = defaultdict(int)
    for t in tests:
        for a in t.get("_attempts") or []:
            sharing[tuple(a)] += 1
    out = []
    for t in tests:
        minutes = paid = 0.0
        for a in t.get("_attempts") or []:
            for j in by_attempt.get(tuple(a), []):
                m = _minutes(j) / sharing[tuple(a)]
                kind, price = rate(j.get("lb"))
                minutes += m
                paid += 0.0 if price is None else (m * price if private or kind not in STANDARD else 0.0)
        if minutes:
            out.append({"id": t.get("id"), "suite": t.get("suite"), "minutes": round(minutes, 1), "usd": round(paid, 2),
                        "flakes": len(t.get("_attempts") or []), "prs": len(t.get("prs_affected") or [])})
    return sorted(out, key=lambda x: -x["minutes"])[:most]
