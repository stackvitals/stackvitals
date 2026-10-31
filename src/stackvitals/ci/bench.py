import json
import math
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from mergescout.bench.ci import repo_stats, tier
from mergescout.github.releases import ReleaseError, Releases
from stackvitals.core.stats import median_range, shrink, wilson

# The public repo whose bench-latest release holds copies of the CI and shared benchmark files ("owner/repo").
PUBLIC_HOME: str | None = "stackvitals/stackvitals"
# Built daily by the crawler from about 90k active public repos; the private store keeps every file, read with a token.
BENCH_REPO, BENCH_TAG, BENCH_FILE = "kaushik-yadav/merge-scout", "bench-latest", "ci-benchmarks.json"


def _asset_url(name: str) -> str | None:
    return f"https://github.com/{PUBLIC_HOME}/releases/download/{BENCH_TAG}/{name}" if PUBLIC_HOME else None


# A missing or unreachable public file (before launch, say) just leaves the comparison out.
DEFAULT_URL = _asset_url(BENCH_FILE)
RANKS = (0.10, 0.25, 0.50, 0.75, 0.90)
EVIDENCE_MAX = 300  # pushes listed behind the first-try share, newest first


def _push_runs(data: dict) -> list[dict]:
    final = {}
    for r in data.get("runs", []):
        if r.get("ev") == "push" and r["att"] >= final.get(r["id"], {}).get("att", 0):
            final[r["id"]] = r
    return [{"id": r["id"], "head_sha": r.get("sha"), "path": r.get("path"), "conclusion": r.get("c"),
              "head_branch": r.get("br"), "run_attempt": r["att"], "status": "completed", "created_at": r.get("cr"),
              "run_started_at": r.get("st"), "updated_at": r.get("up")} for r in final.values()]


def push_stats(data: dict, now: datetime, days: int = 30) -> dict | None:
    """This repo's pushes measured exactly like the benchmark sampler measures every other repo, with each number's
    likely range."""
    out = repo_stats(_push_runs(data), since=now - timedelta(days=days), durations=True, evidence=EVIDENCE_MAX)
    if not out:
        return out
    durations = out.pop("durations")
    green = round(out["first_try_share"] * out["pushes"])
    out["first_try_range"] = [round(x, 4) for x in wilson(green, out["pushes"])]
    rng = median_range(durations)
    out["median_range_s"] = [round(x) for x in rng] if rng else None
    return out


def push_window(data: dict, start: str, end: str) -> dict | None:
    """The push measure over runs created from `start` up to `end`, with each push's wait kept for change tests."""
    return repo_stats([r for r in _push_runs(data) if r["created_at"] and start <= r["created_at"] < end], durations=True)


def push_stats_by(data: dict, period) -> dict[str, dict]:
    """The same push measure for each period (a week, say); periods with too few pushes are left out."""
    groups = {}
    for r in _push_runs(data):
        if r["created_at"]:
            groups.setdefault(period(r["created_at"]), []).append(r)
    return {k: s for k, g in groups.items() if (s := repo_stats(g))}


def load(token: str | None, cache_dir: Path, client: httpx.Client | None = None, name: str = BENCH_FILE,
         url_env: str = "STACKVITALS_BENCH_URL", validate=None, default_url: str | None = DEFAULT_URL) -> dict | None:
    """The latest benchmarks, or None: comparisons are extra and must never break a run."""
    validate = validate or _valid
    source = os.environ.get(url_env) or default_url
    if not source and not token:
        return None
    cache = Path(cache_dir) / name
    try:
        if source and not source.startswith(("http://", "https://")):
            return validate(json.loads(Path(source).read_text(encoding="utf-8")))
        if cache.exists() and time.time() - cache.stat().st_mtime < 86400:
            return validate(json.loads(cache.read_text(encoding="utf-8")))
        cache.parent.mkdir(parents=True, exist_ok=True)
        if source and _fetch(source, cache, client):
            return validate(json.loads(cache.read_text(encoding="utf-8")))
        # A token falls back to the private store, so a missing public copy changes nothing for those who can read it.
        if not token or (source and os.environ.get(url_env)):
            return None
        if not Releases(token, BENCH_REPO, client=client).download(BENCH_TAG, name, cache):
            return None
        return validate(json.loads(cache.read_text(encoding="utf-8")))
    except (httpx.HTTPError, ReleaseError, OSError, ValueError):
        return None


def _fetch(url: str, cache: Path, client: httpx.Client | None) -> bool:
    try:
        # Release downloads redirect to a file host; the caller's client may not follow redirects by default.
        resp = (client or httpx.Client(timeout=30)).get(url, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError:
        return False
    cache.write_bytes(resp.content)
    return True


def _group_ok(g) -> bool:
    nums = lambda q: isinstance(q, dict) and all(isinstance(q.get(f"p{int(r * 100)}"), (int, float)) for r in RANKS)  # noqa: E731
    return (isinstance(g, dict) and isinstance(g.get("repos"), int) and not isinstance(g.get("repos"), bool)
            and nums(g.get("median_s")) and nums(g.get("first_try_share")))


def _valid(bench) -> dict | None:
    # Only well-formed groups are kept, so a bad file can neither break a run nor reach a page.
    if not isinstance(bench, dict) or not isinstance(bench.get("groups"), dict):
        return None
    groups = {k: g for k, g in bench["groups"].items() if isinstance(k, str) and k.count("|") == 1 and _group_ok(g)}
    return {**bench, "groups": groups} if groups else None


# Who every comparison is with: the crawl's sample, which may not resemble a private team's work.
PEERS_ARE = "active public open-source repos (100+ stars, pushed in the last 90 days)"
# Opt-in figures that repos filed themselves ([benchmarks] share), public and private; published at launch.
SHARED_FILE = "shared-benchmarks.json"
SHARED_URL = _asset_url(SHARED_FILE)
SHARED_ARE = "repos that chose to share their rounded CI figures, public and private, latest month each"


def fit(key: str, language: str | None, size: str) -> str:
    # The closest group is a loose fit when it had to drop the language or the size; the pages say so.
    return "" if key == f"{language}|{size}" else "a loose fit: too few repos share this language and size, so a wider group"


def _label(key: str, everyone: str = "public repos we track") -> str:
    lang, size = key.split("|")
    stars = f"with {size} stars" if size != "all" else ""
    if lang == "all":
        return f"repos {stars}" if stars else everyone
    return f"{lang} repos {stars}".strip()


def _rank(value: float, q: dict) -> float:
    # Rough place in the group from its published percentiles, kept between 10% and 90%.
    points = [(r, q[f"p{int(r * 100)}"]) for r in RANKS]
    if value <= points[0][1]:
        return RANKS[0]
    if value >= points[-1][1]:
        return RANKS[-1]
    for (r1, v1), (r2, v2) in zip(points, points[1:]):
        if v1 <= value <= v2 and v2 > v1:
            return r1 + (value - v1) / (v2 - v1) * (r2 - r1)
    return 0.5


def _about(share: float) -> int:
    return int(math.floor(share * 100 / 5) * 5)


def _pulled(stats: dict, group: dict) -> dict:
    # The share pulled toward the group's prior: few pushes move little; many keep the repo's own share.
    prior = group.get("first_try_prior")
    if not (isinstance(prior, list) and len(prior) == 2 and all(isinstance(x, (int, float)) and x > 0 for x in prior)):
        return {}
    green = round(stats["first_try_share"] * stats["pushes"])
    return {"pulled": shrink(green, stats["pushes"], tuple(prior))}


def compare(stats: dict | None, bench: dict | None, language: str | None, stars: int | None,
            everyone: str = "public repos we track") -> dict | None:
    """Where this repo stands among similar public repos: the closest group with enough repos."""
    bench = _valid(bench) if bench else None
    if not stats or not bench:
        return None
    groups, size = bench["groups"], tier(stars)
    key = next((k for k in (f"{language}|{size}", f"{language}|all", f"all|{size}", "all|all") if k in groups), None)
    if key is None:
        return None
    g = groups[key]
    r = _rank(stats["median_s"], g["median_s"])
    time_place = f"slower than about {_about(r)}%" if r >= 0.5 else f"faster than about {_about(1 - r)}%"
    r2 = _rank(stats["first_try_share"], g["first_try_share"])
    green_place = f"above about {_about(r2)}%" if r2 >= 0.5 else f"below about {_about(1 - r2)}%"
    return {"group": _label(key, everyone), "repos": g["repos"], "built_at": bench.get("built_at"), "fit": fit(key, language, size),
            "metrics": [{"name": "Time from push to all checks done", "kind": "time", "you": stats["median_s"],
                         "typical": g["median_s"]["p50"], "place": time_place},
                        {"name": "Pushes green on the first try", "kind": "share", "you": stats["first_try_share"],
                         "typical": g["first_try_share"]["p50"], "place": green_place, **_pulled(stats, g)}]}


def badge(stats: dict | None) -> dict:
    """A shields.io endpoint: the share of pushes whose checks all passed on the first try."""
    if not stats:
        return {"schemaVersion": 1, "label": "CI first try", "message": "no data", "color": "lightgrey"}
    share = stats["first_try_share"]
    color = next(c for floor, c in ((0.9, "brightgreen"), (0.8, "green"), (0.7, "yellow"), (0.5, "orange"), (0, "red"))
                 if share >= floor)
    return {"schemaVersion": 1, "label": "CI first try", "message": f"{share:.0%}", "color": color}
