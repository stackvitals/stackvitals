"""Suggested reviewers (Team Flow) before Phase 16 turns them into review requests: for each repo's recent reviewed pull
requests, using only what was known before each opened, was a maintainer who really reviewed it among the top 3? Scored
beside the plain rule of the 3 maintainers who reviewed most in the repo before it.

    python bench/accuracy/team/reviewers.py --flow <folder of flow stores, one per repo>

Writes reviewers-results.json beside this script (counts only).
"""
import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[2] / "src"))
from fair import by_repo, mcnemar  # noqa: E402

from stackvitals.core.stats import wilson  # noqa: E402
from stackvitals.flow.knowledge import People, _human_reviews, _merged_humans, expertise, suggest_reviewers  # noqa: E402
from stackvitals.flow.store import FlowStore  # noqa: E402

LAST = 50


def score_repo(prs: list[dict], now: datetime) -> list[tuple[bool, bool]]:
    """(ours hit, busiest-reviewers hit) for each of the repo's last LAST reviewed, merged human PRs."""
    people = People(prs)
    reviewed = lambda p: {e[2] for e in _human_reviews(p) if people.is_insider(e[2])}  # noqa: E731
    merged = sorted(_merged_humans(prs, now), key=lambda p: p["mg"])
    out = []
    for p in [p for p in merged if p.get("paths") and reviewed(p)][-LAST:]:
        ex = expertise(prs, now, before=p["cr"], people=people)
        ours = {s["login"] for s in suggest_reviewers(p, ex, load={}, owners={})}
        counts = Counter(r for q in merged if q["mg"] < p["cr"] for r in reviewed(q) if r != p.get("au"))
        busiest = {r for r, _n in counts.most_common(3)}
        truth = reviewed(p)
        out.append((bool(ours & truth), bool(busiest & truth)))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--flow", type=Path, required=True)
    args = ap.parse_args(argv)
    rows, halves = [], {}
    for i, folder in enumerate(sorted(p for p in args.flow.iterdir() if p.is_dir())):
        # Author pairing was chosen on the even-numbered folders ("tune"); the odd ones are its held-out check.
        halves[folder.name.replace("__", "/", 1)] = "tune" if i % 2 == 0 else "held_out"
        data = FlowStore(folder).load()
        prs = (data.get("closed") or []) + (data.get("open") or [])
        if not any(p.get("mg") for p in prs):
            continue  # nothing merged in the stored window
        now = max(datetime.fromisoformat(p["mg"].replace("Z", "+00:00")) for p in prs if p.get("mg"))
        rows += [(folder.name.replace("__", "/", 1), ours, busy) for ours, busy in score_repo(prs, now)]
    n = len(rows)
    out = {"repos": len({r for r, _o, _b in rows}), "prs": n, "last_per_repo": LAST}
    for i, name in ((1, "suggested"), (2, "busiest_reviewers")):
        k = sum(r[i] for r in rows)
        lo, hi = wilson(k, n)
        out[name] = {"hits": k, "share": round(k / n, 4) if n else None, "low": round(lo, 4), "high": round(hi, 4),
                     "by_repo": by_repo([(r[0], r[i]) for r in rows])}
    out["suggested_vs_busiest"] = mcnemar(sum(o and not b for _r, o, b in rows), sum(b and not o for _r, o, b in rows))
    for half in ("tune", "held_out"):
        mine = [r for r in rows if halves.get(r[0]) == half]
        out[half] = {"prs": len(mine), "suggested": sum(r[1] for r in mine), "busiest_reviewers": sum(r[2] for r in mine)}
    (HERE / "reviewers-results.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: (v if k not in ("suggested", "busiest_reviewers") else {x: v[x] for x in ("hits", "share", "low", "high")})
                      for k, v in out.items()}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
