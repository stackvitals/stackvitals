"""Blind labelling views of the flaky sample: each item with its evidence and what a re-run of the same job did, without
the stratum or the detector's verdict, split into parts for labellers, plus a seeded 20% for a second labelling.

    python bench/accuracy/flaky/views.py --home <work folder> [--parts 6] [--seed 13]

Writes <home>/view-NN.jsonl and <home>/view-second.jsonl; ids follow items.jsonl (score.py's order).
"""
import argparse
import json
import random
import sys
from pathlib import Path

from stackvitals.ci.analyze import FAIL, PASS
from stackvitals.ci.store import DataStore

SHOWN = ("repo", "workflow", "job", "event", "branch", "change", "failing_step", "runner", "files_changed", "log")


def rerun(item: dict, data: dict) -> str:
    """What else ran this job on the same code: a later attempt of the same run, or another run of the workflow on the
    same tree (a rebase or merge commit with identical files counts as the same code)."""
    runs = {(r["id"], r["att"]): r for r in data["runs"]}
    run = runs.get((item["run"], item["att"])) or {}
    code = lambda r: r.get("tree") or r.get("sha")  # noqa: E731
    later = [j["c"] for j in data["jobs"] if j["run"] == item["run"] and j["att"] > item["att"] and j["n"] == item["job"]]
    other = [j["c"] for j in data["jobs"] if j["run"] != item["run"] and j["n"] == item["job"] and code(run)
             and code(runs.get((j["run"], j["att"])) or {}) == code(run) and (runs.get((j["run"], j["att"])) or {}).get("path") == run.get("path")]
    if any(c in PASS for c in later):
        return "a re-run of the same run passed this job"
    if any(c in PASS for c in other):
        return "another run on the same code passed this job"
    return "ran again on the same code and failed again" if any(c in FAIL for c in later + other) else "not run again"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--home", type=Path, required=True)
    ap.add_argument("--parts", type=int, default=6)
    ap.add_argument("--seed", type=int, default=13)
    args = ap.parse_args(argv)
    items = [json.loads(x) for x in (args.home / "items.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    items = [i for i in items if i.get("sample") != "none"]
    stores = {}
    rows = []
    for n, item in enumerate(items, 1):
        repo = item["repo"]
        if repo not in stores:
            stores[repo] = DataStore(args.home / "ci" / repo.replace("/", "__")).load()
        rows.append(json.dumps({"id": n, **{k: item.get(k) for k in SHOWN}, "rerun": rerun(item, stores[repo])}))
    size = -(-len(rows) // args.parts)
    for k in range(args.parts):
        (args.home / f"view-{k:02d}.jsonl").write_text("\n".join(rows[k * size:(k + 1) * size]) + "\n", encoding="utf-8")
    pick = sorted(random.Random(args.seed).sample(range(len(rows)), round(len(rows) * 0.2)))
    (args.home / "view-second.jsonl").write_text("\n".join(rows[i] for i in pick) + "\n", encoding="utf-8")
    print(f"{len(rows)} items in {args.parts} parts; {len(pick)} for the second labelling")
    return 0


if __name__ == "__main__":
    sys.exit(main())
