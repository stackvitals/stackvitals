from datetime import datetime, timedelta
from pathlib import Path

from mergescout.bench.ci import tier
from stackvitals.ci import bench as ci_bench
from stackvitals.ci.bench import RANKS, _about, _label, _rank, fit
from stackvitals.core.actors import People
from stackvitals.flow.analyze import _human_reviews, _iso, _median, _secs, is_bot

FLOW_FILE = "flow-benchmarks.json"
MIN_PRS = 10
# Lower is better for waits; a higher merge rate is better; size is neither, so it gets plain words.
METRICS = [("first_review_hours", "First maintainer review after", "hours", -1),
           ("merge_hours", "Opened to merged", "hours", -1),
           ("outsider_merge_rate", "Outside contributors' PRs merged", "share", 1),
           ("size_lines", "Typical PR size", "lines", 0)]


def own_metrics(prs: list[dict], now: datetime, window_days: int = 90, people: People | None = None) -> dict | None:
    """This repo's numbers with exactly the crawl benchmarks' definitions (PRs opened in the window, people only,
    maintainers found by what they do)."""
    since = _iso(now - timedelta(days=window_days))
    if people is None:
        people = People(prs)
    mine = [p for p in prs if p["cr"] >= since and not is_bot(p)]
    if len(mine) < MIN_PRS:
        return None
    reviews, merges, sizes = [], [], []
    for p in mine:
        # Like the crawl: the first human review, counted only when a maintainer gave it.
        humans = _human_reviews(p)
        first = [humans[0][1]] if humans and people.is_insider(humans[0][2]) else []
        # Times out of order (clock skew, imported history) are skipped, never divided.
        if first and (wait := _secs(p["cr"], first[0])) is not None:
            reviews.append(wait / 3600)
        if p.get("mg") and (wait := _secs(p["cr"], p["mg"])) is not None:
            merges.append(wait / 3600)
        sizes.append((p.get("add") or 0) + (p.get("del") or 0))
    outsiders = [p for p in mine if people.is_outside(p) and p.get("st") in ("MERGED", "CLOSED")]
    return {"prs": len(mine), "first_review_hours": _median(reviews), "merge_hours": _median(merges),
            "outsider_merge_rate": round(sum(p["st"] == "MERGED" for p in outsiders) / len(outsiders), 4) if outsiders else None,
            "size_lines": _median(sizes)}


def _ok(q) -> bool:
    return isinstance(q, dict) and all(isinstance(q.get(f"p{int(r * 100)}"), (int, float)) for r in RANKS)


def valid(data) -> dict | None:
    # A bad file is ignored, metric by metric, so it can neither break a run nor reach a page.
    if not isinstance(data, dict) or not isinstance(data.get("groups"), dict):
        return None
    groups = {}
    for key, g in data["groups"].items():
        if isinstance(key, str) and key.count("|") == 1 and isinstance(g, dict) and isinstance(g.get("repos"), int):
            kept = {m: g[m] for m, *_ in METRICS if _ok(g.get(m))}
            if kept:
                groups[key] = {"repos": g["repos"], **kept}
    return {**data, "groups": groups} if groups else None


def load(token: str | None, cache_dir: Path, client=None) -> dict | None:
    return ci_bench.load(token, cache_dir, client=client, name=FLOW_FILE, url_env="STACKVITALS_FLOW_BENCH_URL",
                         validate=valid, default_url=None)


def compare(own: dict | None, bench: dict | None, language: str | None, stars: int | None) -> dict | None:
    """Where this repo's review flow stands among similar public repos: the closest group with enough repos."""
    bench = valid(bench) if bench else None
    if not own or not bench:
        return None
    groups, size = bench["groups"], tier(stars)
    key = next((k for k in (f"{language}|{size}", f"{language}|all", f"all|{size}", "all|all") if k in groups), None)
    if key is None:
        return None
    g, metrics = groups[key], []
    for name, label, kind, better in METRICS:
        if own.get(name) is None or name not in g:
            continue
        r = _rank(own[name], g[name])
        if better < 0:
            place = f"slower than about {_about(r)}%" if r >= 0.5 else f"faster than about {_about(1 - r)}%"
        elif better > 0:
            place = f"above about {_about(r)}%" if r >= 0.5 else f"below about {_about(1 - r)}%"
        else:
            place = f"bigger than about {_about(r)}%" if r >= 0.5 else f"smaller than about {_about(1 - r)}%"
        metrics.append({"key": name, "name": label, "kind": kind, "you": own[name], "typical": g[name]["p50"],
                        "place": place, "repos": g[name]["repos"]})
    return {"group": _label(key), "repos": g["repos"], "built_at": bench.get("built_at"), "metrics": metrics,
            "fit": fit(key, language, size)} if metrics else None
