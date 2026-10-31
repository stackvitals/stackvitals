"""Where a repo's delivery stands among similar public repos: its own P75s measured with exactly the crawl benchmarks'
definitions (people's PRs opened in the last 90 days; pickup from opening to the first maintainer review), placed in the
closest group with enough repos, with the median's range, LinearB's band shares, and what the comparison can't see."""
import math
from datetime import datetime, timedelta
from pathlib import Path

from mergescout.bench.ci import tier
from stackvitals.ci import bench as ci_bench
from stackvitals.ci.bench import RANKS, _about, _label, _rank, fit
from stackvitals.core.actors import People
from stackvitals.flow.analyze import _human_reviews, _iso, _secs, is_bot

DELIVERY_FILE = "delivery-benchmarks.json"
MIN_PRS = 10
MIN_VALUES = 5
METRICS = [("pickup_p75_hours", "Pickup: opened to first maintainer review (P75)"),
           ("review_p75_hours", "Review: first review to merge (P75)"),
           ("cycle_to_merge_p75_hours", "Opened to merged (P75)")]


def _p75(values: list[float]) -> float | None:
    if len(values) < MIN_VALUES:
        return None
    s = sorted(values)
    return round(s[min(len(s) - 1, max(0, math.ceil(0.75 * len(s)) - 1))], 4)


def own_metrics(prs: list[dict], now: datetime, window_days: int = 90, people: People | None = None) -> dict | None:
    """This repo's P75s by the crawl's rules, so the comparison is like with like."""
    since = _iso(now - timedelta(days=window_days))
    people = people or People(prs)
    mine = [p for p in prs if p["cr"] >= since and not is_bot(p)]
    if len(mine) < MIN_PRS:
        return None
    pickup, review, cycle = [], [], []
    for p in mine:
        humans = _human_reviews(p)
        first = humans[0] if humans and people.is_insider(humans[0][2]) and humans[0][2] != p.get("au") else None
        if first and (wait := _secs(p["cr"], first[1])) is not None:
            pickup.append(wait / 3600)
        if p.get("mg"):
            if first and (wait := _secs(first[1], p["mg"])) is not None:
                review.append(wait / 3600)
            if (wait := _secs(p["cr"], p["mg"])) is not None:
                cycle.append(wait / 3600)
    return {"prs": len(mine), "pickup_p75_hours": _p75(pickup), "review_p75_hours": _p75(review),
            "cycle_to_merge_p75_hours": _p75(cycle)}


def _ok(q) -> bool:
    return isinstance(q, dict) and all(isinstance(q.get(f"p{int(r * 100)}"), (int, float)) for r in RANKS)


def valid(data) -> dict | None:
    # A bad file is ignored, metric by metric, so it can neither break a run nor reach a page.
    if not isinstance(data, dict) or not isinstance(data.get("groups"), dict):
        return None
    groups = {}
    for key, g in data["groups"].items():
        if isinstance(key, str) and key.count("|") == 1 and isinstance(g, dict) and isinstance(g.get("repos"), int):
            kept = {m: g[m] for m, _ in METRICS if _ok(g.get(m))}
            if kept:
                groups[key] = {"repos": g["repos"], **kept}
    return {**data, "groups": groups} if groups else None


def load(token: str | None, cache_dir: Path, client=None) -> dict | None:
    return ci_bench.load(token, cache_dir, client=client, name=DELIVERY_FILE, url_env="STACKVITALS_DELIVERY_BENCH_URL",
                         validate=valid, default_url=None)


def compare(own: dict | None, bench: dict | None, language: str | None, stars: int | None) -> dict | None:
    """The closest group with the metric (language and size, then wider), and this repo's place in it."""
    bench = valid(bench) if bench else None
    if not own or not bench:
        return None
    groups, size = bench["groups"], tier(stars)
    metrics, chosen = [], None
    for name, label in METRICS:
        if own.get(name) is None:
            continue
        key = next((k for k in (f"{language}|{size}", f"{language}|all", f"all|{size}", "all|all")
                    if k in groups and name in groups[k]), None)
        if key is None:
            continue
        chosen = chosen or key
        q = groups[key][name]
        r = _rank(own[name], q)
        place = f"slower than about {_about(r)}%" if r >= 0.5 else f"faster than about {_about(1 - r)}%"
        metrics.append({"key": name, "name": label, "you": own[name], "typical": q["p50"], "low": q.get("p50_low"),
                        "high": q.get("p50_high"), "p25": q["p25"], "p75": q["p75"], "place": place, "repos": q["repos"],
                        "group": _label(key), "linearb": q.get("linearb")})
    if not metrics:
        return None
    return {"group": _label(chosen), "repos": groups[chosen]["repos"], "built_at": bench.get("built_at"), "metrics": metrics,
            "fit": fit(chosen, language, size),
            "population": bench.get("population"), "gaps": bench.get("gaps")}
