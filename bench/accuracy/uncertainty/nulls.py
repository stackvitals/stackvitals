"""How often the weekly digest would flag a change that is only week-to-week noise.

For each repo's real merged pull requests and deployments, the digest's Delivery checks (pickup, review, opened to merged,
deployments, change failure rate) are run at weekly scan points. Each scan is then repeated with the five weeks it looks
at shuffled (a permuted-week null; six weeks, as far back as the 14-day checks look): whichever week lands last plays
"this week", so any flag is ordinary variation.
Reported per rule: the share of null scans that flag anything. Pass bar: at most 10% with false-alarm control.
Power: the same scans with this week's review times (pickup, review, opened to merged) made 2 to 10 times longer, and
the share of those the digest catches.

    python bench/accuracy/uncertainty/nulls.py <folder of repo workspaces> [--points 12] [--shuffles 20] [--seed 13]
        [--slow-weeks 2]
"""
import argparse
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

from stackvitals.core import changes
from stackvitals.core.actors import kind_of
from stackvitals.core.config import parse
from stackvitals.core.delivery import _changes, incidents_for, shipped
from stackvitals.core.time import iso
from stackvitals.core.time import parse as when
from stackvitals.flow.store import FlowStore

SPAN = changes.BASE_WEEKS + 2  # the 14-day checks see six weeks


def _load(root: Path):
    store = FlowStore(root)
    flow, repo = store.load(), store.repo()
    cfg = parse("")[0]
    deps, _source, merged = shipped(flow, repo, {"runs": [], "jobs": []}, cfg, ("person",))
    rows = [r for r in merged if kind_of(r[0].get("au"), r[0].get("at")) == "person"]
    incidents = incidents_for((flow.get("closed") or []) + (flow.get("open") or []), [], deps, cfg, None)[0]
    return rows, deps, incidents


def _shuffled(rows, deps, now: datetime, order: list[int]):
    # Week j of the five (0 = oldest) moves to week order[j]; times outside the five weeks stay put.
    start = now - changes.WEEK * SPAN

    def move(stamp: str) -> str:
        t = when(stamp)
        if not start <= t < now:
            return stamp
        j = int((t - start) / changes.WEEK)
        return iso(t + changes.WEEK * (order[j] - j))
    return ([({**p, "mg": move(p["mg"])}, ph, dep) for p, ph, dep in rows],
            [{**d, "finished": move(d["finished"])} for d in deps])


TIMES = ("pickup", "review", "cycle_to_merge")


def _slower(rows, now: datetime, factor: float, weeks: int = 1):
    # A real shift: the last `weeks` weeks' PRs took `factor` times as long in every review phase.
    week = iso(now - changes.WEEK * weeks)
    return [(p, {**ph, **{k: ph[k] * factor for k in TIMES if ph.get(k) is not None}} if week <= p["mg"] < iso(now) else ph, dep)
            for p, ph, dep in rows]


def _band(merged: int) -> str:
    return next(name for top, name in ((5, "under 5"), (10, "5-9"), (20, "10-19"), (40, "20-39"), (10**9, "40+")) if merged < top)


def _rules(found: list[dict]) -> dict[str, bool]:
    # What each rule would have told the team: anything at all, an unchecked p below 0.05 or 0.1 (the digest's own
    # level), or false-alarm control.
    moved = [c for c in found if c["direction"] in ("up", "down")]
    return {"any_difference": bool(moved), "p_below_0.05": any(c["p"] < 0.05 for c in moved),
            "p_below_0.1": any(c["p"] < 0.1 for c in moved),
            "false_alarm_control": any(c["changed"] for c in changes.flag(found))}


def _caught(found: list[dict], flagged: list[dict]) -> dict[str, bool]:
    """Whether each rule caught an injected slowdown: a review-time metric going up (flagged = after false-alarm control)."""
    base = lambda c: c["metric"].split(".")[1].removesuffix("_14d")  # noqa: E731
    up = [c for c in found if base(c) in TIMES and c["direction"] == "up"]
    return {"any_difference": bool(up), "p_below_0.05": any(c["p"] < 0.05 for c in up),
            "p_below_0.1": any(c["p"] < 0.1 for c in up),
            "false_alarm_control": any(c["changed"] and base(c) in TIMES and c["direction"] == "up" for c in flagged)}


def run(folder: Path, points: int, shuffles: int, seed: int, weeks: int = 1) -> dict:
    rng = random.Random(seed)
    per_repo, null_totals, real_totals, scans = {}, {}, {}, 0
    caught = {2.0: 0, 3.0: 0, 5.0: 0, 10.0: 0}
    caught_by_rule = {f: {} for f in caught}
    by_volume = {}
    for root in sorted(p for p in folder.iterdir() if (p / "flow" / "closed").is_dir()):
        try:
            rows, deps, incidents = _load(root)
        except Exception as exc:  # a workspace that can't be read is reported, not fatal
            per_repo[root.name] = {"error": type(exc).__name__}
            continue
        if len(rows) < 50:
            continue
        last = max(when(r[0]["mg"]) for r in rows)
        first = min(when(r[0]["mg"]) for r in rows)
        flags, nulls = {}, {}
        for k in range(points):
            now = last - changes.WEEK * k
            if now - changes.WEEK * SPAN < first:
                break
            real = _changes(rows, deps, incidents, now)
            if sum(c["n_now"] for c in real[:3]) < changes.MIN_EACH:
                continue  # a quiet week: nothing to scan
            scans += 1
            for rule, hit in _rules(real).items():
                flags[rule] = flags.get(rule, 0) + hit
            merged = next(c["n_now"] for c in real if c["metric"] == "delivery.cycle_to_merge")
            band = by_volume.setdefault(_band(merged), {"scans": 0, **{f"{f:g}x": 0 for f in caught}})
            band["scans"] += 1
            for factor in caught:
                raw = _changes(_slower(rows, now, factor, weeks), deps, incidents, now)
                per_rule = _caught(raw, changes.flag(raw))
                hit = per_rule["false_alarm_control"]
                caught[factor] += hit
                band[f"{factor:g}x"] += hit
                for rule, got in per_rule.items():
                    caught_by_rule[factor][rule] = caught_by_rule[factor].get(rule, 0) + got
            for _ in range(shuffles):
                order = list(range(SPAN))
                rng.shuffle(order)
                r2, d2 = _shuffled(rows, deps, now, order)
                for rule, hit in _rules(_changes(r2, d2, incidents, now)).items():
                    nulls[rule] = nulls.get(rule, 0) + hit
        if not flags:
            continue
        per_repo[root.name] = {"prs": len(rows), "deployments": len(deps), "real_flags": flags, "null_flags": nulls}
        for rule, hit in nulls.items():
            null_totals[rule] = null_totals.get(rule, 0) + hit
        for rule, hit in flags.items():
            real_totals[rule] = real_totals.get(rule, 0) + hit
    null_scans = scans * shuffles
    return {"scans": scans, "null_scans": null_scans, "seed": seed, "slow_weeks": weeks,
            "null_flag_rate": {rule: round(hit / null_scans, 4) for rule, hit in null_totals.items()} if null_scans else {},
            "real_flag_rate": {rule: round(hit / scans, 4) for rule, hit in real_totals.items()} if scans else {},
            "caught_when_slower": {f"{f:g}x": round(hit / scans, 4) for f, hit in caught.items()} if scans else {},
            "caught_when_slower_by_rule": {f"{f:g}x": {r: round(h / scans, 4) for r, h in hits.items()}
                                           for f, hits in caught_by_rule.items()} if scans else {},
            "caught_by_prs_merged": {k: {"scans": v["scans"], **{f: round(v[f] / v["scans"], 4) for f in v if f != "scans"}}
                                     for k, v in by_volume.items()},
            "repos": per_repo}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("folder", type=Path)
    ap.add_argument("--points", type=int, default=12)
    ap.add_argument("--shuffles", type=int, default=20)
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--slow-weeks", type=int, default=1, help="weeks of PRs the injected slowdown covers")
    ap.add_argument("--out", type=Path, default=Path(__file__).with_name("nulls-results.json"))
    args = ap.parse_args(argv)
    out = run(args.folder, args.points, args.shuffles, args.seed, args.slow_weeks)
    out["generated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    args.out.write_text(json.dumps(out, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("scans", "null_scans", "null_flag_rate", "real_flag_rate", "caught_when_slower",
                                          "caught_by_prs_merged")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
