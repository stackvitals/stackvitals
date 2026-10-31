"""What changes in a repo after it starts taking coding agents' pull requests: a staggered difference-in-differences
(Callaway and Sant'Anna) over the crawl, exactly as preregistration.md says; its SHA-256 goes into the results.

    python bench/accuracy/ai/adoption.py <crawl folder: prs/> [--draws 400] [--seed 23]

Writes adoption-results.json beside this script: group sizes, event-time effects with 95% ranges from a repo bootstrap,
the overall effect, the pre-trend and negative-control checks, and the reading each outcome gets.
"""
import argparse
import hashlib
import json
import math
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "src"))
from stackvitals.core.actors import kind_of  # noqa: E402

MONTHS = [f"{y}-{m:02d}" for y, m in [(2025, 11), (2025, 12)] + [(2026, k) for k in range(1, 10)]]
YOUNG = "2026-09"  # outcomes 3 and 4 skip it
CAP, MIN_N = 290, 3
EVENTS = range(-4, 4)
AGENT_BRANCH = ("codex/", "copilot/", "cursor/", "devin/", "claude/", "codex-", "copilot-", "cursor-", "devin-", "claude-")
OUTCOMES = ("merged", "people_merged", "review_wait", "merge_rate")


def load(folder: Path) -> list[tuple]:
    return duckdb.connect().execute(f"""
        SELECT repo_id, strftime(created_at AT TIME ZONE 'UTC', '%Y-%m') AS month, merged_at IS NOT NULL AS merged,
               state IN ('MERGED', 'CLOSED') AS closed, author_login, author_type, lower(coalesce(head_ref, '')) AS head,
               date_diff('second', created_at, first_human_review_at) / 3600.0 AS wait
        FROM read_parquet('{(folder / '*.parquet').as_posix()}', union_by_name = true)
        QUALIFY row_number() OVER (PARTITION BY repo_id, number ORDER BY fetched_at DESC) = 1
        ORDER BY repo_id, number""").fetchall()


def _median(xs: list[float]) -> float:
    xs = sorted(xs)
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


def panel(rows: list[tuple]) -> dict:
    """Per repo: covered month indexes, agent PR counts by month, and the four outcomes by month."""
    by_repo = defaultdict(list)
    for r in rows:
        by_repo[r[0]].append(r)
    out = {}
    for repo, prs in by_repo.items():
        start = 0
        if len(prs) >= CAP:
            oldest = min(p[1] for p in prs)
            start = MONTHS.index(oldest) + 1 if oldest in MONTHS else 0
        cells = defaultdict(lambda: {"n": 0, "merged": 0, "pm": 0, "pc": 0, "waits": [], "agent": 0})
        for _, month, merged, closed, login, typ, head, wait in prs:
            if month not in MONTHS or MONTHS.index(month) < start:
                continue
            kind = kind_of(login, typ)
            if kind == "bot":
                continue
            c = cells[MONTHS.index(month)]
            agent = kind == "agent" or head.startswith(AGENT_BRANCH)
            c["n"] += 1
            c["merged"] += merged
            if agent:
                c["agent"] += 1
                continue
            c["pm"] += merged
            c["pc"] += closed
            if wait is not None and wait >= 0:
                c["waits"].append(wait)
        months = list(range(start, len(MONTHS)))
        if len(months) < 4:
            continue
        y = {o: {} for o in OUTCOMES}
        for m in months:
            c = cells.get(m) or {"n": 0, "merged": 0, "pm": 0, "pc": 0, "waits": [], "agent": 0}
            y["merged"][m] = math.log1p(c["merged"])
            y["people_merged"][m] = math.log1p(c["pm"])
            if MONTHS[m] != YOUNG and len(c["waits"]) >= MIN_N:
                y["review_wait"][m] = math.log(max(_median(c["waits"]), 0.01))
            if MONTHS[m] != YOUNG and c["pc"] >= MIN_N:
                y["merge_rate"][m] = c["pm"] / c["pc"]
        agents = {m: (cells.get(m) or {}).get("agent", 0) for m in months}
        first3 = [(cells.get(m) or {}).get("n", 0) for m in months[:3]]
        out[repo] = {"months": months, "agents": agents, "y": y, "activity": sum(first3) / 3}
    return out


def groups(pan: dict) -> dict:
    """Each repo's adoption month (None for never) or its exclusion reason, and its activity band."""
    info = {}
    for repo, p in pan.items():
        used = [m for m in p["months"] if p["agents"][m]]
        if not used:
            info[repo] = {"g": None}
            continue
        g = used[0]
        sustained = sum(p["agents"].get(m, 0) for m in (g, g + 1, g + 2)) >= 2
        pre = sum(1 for m in p["months"] if m < g)
        post = sum(1 for m in p["months"] if m > g)
        info[repo] = {"g": g} if sustained and pre >= 3 and post >= 1 else {"g": "out"}
    acts = sorted(p["activity"] for r, p in pan.items() if info[r]["g"] != "out")
    cuts = (acts[len(acts) // 3], acts[2 * len(acts) // 3])
    for repo, p in pan.items():
        info[repo]["band"] = 0 if p["activity"] <= cuts[0] else 1 if p["activity"] <= cuts[1] else 2
    return info


def contributions(pan: dict, info: dict, outcome: str, placebo: bool = False) -> dict:
    """Per repo, its (cell, side, difference) entries: cell = (g, t, band), side 1 adopter, 0 comparison."""
    contrib = defaultdict(list)
    gs = sorted({i["g"] for i in info.values() if isinstance(i["g"], int)})
    for repo, p in pan.items():
        i = info[repo]
        if i["g"] == "out":
            continue
        y = p["y"][outcome]
        real = i["g"]
        if isinstance(real, int):
            g = real - 3 if placebo else real
            for e in EVENTS:
                t = g + e
                if placebo and (e > 2 or t >= real):
                    continue
                if t in y and (g - 1) in y and t != g - 1:
                    contrib[repo].append(((g, t, i["band"]), 1, y[t] - y[g - 1]))
        for g in ([x - 3 for x in gs] if placebo else gs):
            for e in EVENTS:
                t = g + e
                # Comparison repos haven't started by t (nor by the base month) and aren't in the cohort itself.
                if t == g - 1 or (real is not None and (real <= max(t, g - 1) or (real - 3 if placebo else real) == g)):
                    continue
                if t in y and (g - 1) in y:
                    contrib[repo].append(((g, t, i["band"]), 0, y[t] - y[g - 1]))
    return contrib


def estimate(contrib: dict, weights: dict) -> dict:
    """Event-time effects and the overall effect for one set of repo weights."""
    sums = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])  # adopter sum, adopter weight, comparison sum, comparison weight
    for repo, w in weights.items():
        for cell, side, d in contrib.get(repo, ()):
            s = sums[cell]
            if side:
                s[0] += w * d
                s[1] += w
            else:
                s[2] += w * d
                s[3] += w
    by_e = defaultdict(lambda: [0.0, 0.0])
    for (g, t, _), (ts, tw, cs, cw) in sums.items():
        if tw and cw:
            by_e[t - g][0] += tw * (ts / tw - cs / cw)
            by_e[t - g][1] += tw
    att = {e: v[0] / v[1] for e, v in by_e.items() if v[1]}
    post = [att[e] for e in range(0, 4) if e in att]
    return {"att": att, "overall": sum(post) / len(post) if post else None,
            "n": {e: v[1] for e, v in by_e.items()}}


def _range(xs: list[float]) -> list[float] | None:
    xs = sorted(x for x in xs if x is not None)
    if len(xs) < 20:
        return None
    return [round(xs[int(0.025 * len(xs))], 4), round(xs[int(0.975 * len(xs)) - 1], 4)]


def run(contrib: dict, repos: list, draws: int, seed: int) -> dict:
    point = estimate(contrib, {r: 1 for r in repos})
    rng, boots = random.Random(seed), []
    for _ in range(draws):
        boots.append(estimate(contrib, Counter(rng.choices(repos, k=len(repos)))))
    events = {}
    for e in sorted(point["att"]):
        events[e] = {"effect": round(point["att"][e], 4), "range": _range([b["att"].get(e) for b in boots]),
                     "adopters": int(point["n"][e])}
    return {"events": events, "overall": round(point["overall"], 4) if point["overall"] is not None else None,
            "overall_range": _range([b["overall"] for b in boots])}


def _excludes_zero(r) -> bool:
    return bool(r) and (r[0] > 0 or r[1] < 0)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("crawl", type=Path)
    ap.add_argument("--draws", type=int, default=400)
    ap.add_argument("--seed", type=int, default=23)
    args = ap.parse_args(argv)
    prereg = hashlib.sha256((HERE / "preregistration.md").read_bytes()).hexdigest()
    pan = panel(load(args.crawl))
    info = groups(pan)
    kinds = Counter("out" if i["g"] == "out" else "never" if i["g"] is None else "adopter" for i in info.values())
    cohorts = Counter(MONTHS[i["g"]] for i in info.values() if isinstance(i["g"], int))
    repos = sorted(r for r in pan if info[r]["g"] != "out")
    out = {"preregistration_sha256": prereg, "repos": len(pan), "groups": dict(kinds), "cohorts": dict(sorted(cohorts.items())),
           "draws": args.draws, "seed": args.seed, "outcomes": {}}
    for o in OUTCOMES:
        res = run(contributions(pan, info, o), repos, args.draws, args.seed)
        neg = run(contributions(pan, info, o, placebo=True), repos, args.draws, args.seed)
        leads_ok = all(not _excludes_zero(res["events"][e]["range"]) for e in (-4, -3, -2) if e in res["events"])
        neg_ok = not _excludes_zero(neg["overall_range"])
        if not leads_ok:
            reading = "not credible: adopters were already changing"
        elif _excludes_zero(res["overall_range"]) and neg_ok:
            reading = "effect"
        elif not neg_ok:
            reading = "not credible: the negative control moved"
        else:
            reading = "no measurable change"
        bands = {}
        for b in range(3):
            sub = {r: c for r, c in contributions(pan, info, o).items() if info[r]["band"] == b}
            got = run(sub, [r for r in repos if info[r]["band"] == b], args.draws // 4, args.seed)
            bands[b] = {"overall": got["overall"], "overall_range": got["overall_range"]}
        out["outcomes"][o] = {**res, "negative_control": {"overall": neg["overall"], "overall_range": neg["overall_range"]},
                              "leads_include_zero": leads_ok, "reading": reading, "by_band": bands}
        print(o, reading, res["overall"], res["overall_range"], flush=True)
    (HERE / "adoption-results.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
