"""The stricter "known flaky" rule (pre-registered 2026-10-28, README) on a fresh read no rule was written on, and on
the data it was written from.

    python bench/accuracy/flaky/safe_rule.py pool --home <fresh work folder>
    GH_TOKEN=... python bench/accuracy/flaky/safe_rule.py fetch --home <fresh work folder> [--seed 7]
    python bench/accuracy/flaky/safe_rule.py score --home <fresh work folder> --final <final/fresh.jsonl> \
        --tune-home <held-out wide work folder> --tune-final <final/heldout.jsonl> --masking-home <flaky work folder>

pool: every pull-request failure the history rule (3+ flakes, one in the failing step) calls known flaky, judged with
the history before it only (heldout.pool). fetch: at most 3 per job (seeded), each with its log and the pull request's
files (sample.evidence); writes items.jsonl and a blind view.jsonl (no verdicts) for labellers. score: the rule against
the labels; writes safe-rule-results.json beside this script (counts only).
"""
import argparse
import ast
import csv
import json
import os
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from heldout import pool as heldout_pool  # noqa: E402
from sample import Pacer, evidence  # noqa: E402
from views import SHOWN, rerun  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fair import by_repo  # noqa: E402

from stackvitals.ci.feedback import SAFE_FLAKES, _sharpen  # noqa: E402
from stackvitals.ci.store import DataStore  # noqa: E402
from stackvitals.core.stats import wilson  # noqa: E402

HERE = Path(__file__).parent
PER_JOB = 3


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.exists() else []


def _files(item: dict) -> list[str]:
    files = item.get("files_changed") or []
    return ast.literal_eval(files) if isinstance(files, str) else files


def verdict(item: dict) -> str:
    """What StackVitals says now about a failure history calls known flaky: its log and the pull request's files decide."""
    return _sharpen("known flaky", item.get("log"), _files(item))[0]


def fetch(home: Path, seed: int) -> int:
    pool = [p for p in json.loads((home / "heldout-pool.json").read_text(encoding="utf-8")) if p["verdict"] == "known flaky"]
    by_job = defaultdict(list)
    for p in pool:
        by_job[(p["repo"], p["job"])].append(p)
    rng = random.Random(seed)
    picked = [p for job in sorted(by_job) for p in rng.sample(by_job[job], min(PER_JOB, len(by_job[job])))]
    client = httpx.Client(timeout=60, follow_redirects=True, headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}",
                                                                      "Accept": "application/vnd.github+json"})
    pacer = Pacer(client)
    done = {(r["repo"], r["job_id"]) for r in _jsonl(home / "items.jsonl")}
    with (home / "items.jsonl").open("a", encoding="utf-8") as f:
        for p in picked:
            if (p["repo"], p["job_id"]) in done:
                continue
            data = DataStore(home / "ci" / p["repo"].replace("/", "__")).load()
            pacer.before()
            item = evidence(client, p["repo"], {k: p[k] for k in ("workflow", "job", "run", "att", "job_id")}, data)
            pacer.after()
            f.write(json.dumps({**item, "flakes": p["flakes"], "rerun": rerun(item, data)}) + "\n")
            f.flush()
    rows = _jsonl(home / "items.jsonl")
    view = [json.dumps({"id": n, **{k: r.get(k) for k in SHOWN}, "rerun": r["rerun"]}) for n, r in enumerate(rows, 1)]
    (home / "view.jsonl").write_text("\n".join(view) + "\n", encoding="utf-8")
    print(f"{len(pool)} known-flaky calls by history in {len(by_job)} jobs, {len({p['repo'] for p in pool})} repos; "
          f"{len(rows)} items to label")
    return 0


def _caused(labels: list[str]) -> dict:
    yes, no = labels.count("yes"), labels.count("no")
    lo, hi = wilson(yes, yes + no)
    return {"n": len(labels), "caused": yes, "not_caused": no, "unclear": len(labels) - yes - no,
            "caused_low": round(lo, 4), "caused_high": round(hi, 4)}


def measure(rows: list[tuple[dict, dict]]) -> dict:
    """(item, label) pairs, every one a known-flaky call by history: what the rule makes of them, against the labels."""
    by = defaultdict(list)
    for item, lab in rows:
        by[verdict(item)].append((item, lab))
    kept = by["known flaky"]
    clustered = lambda pairs: by_repo([(i["repo"], lab["caused_by_change"] == "yes") for i, lab in pairs  # noqa: E731
                                       if lab["caused_by_change"] in ("yes", "no")])
    return {"calls_by_history": len(rows), "repos": len({i["repo"] for i, _l in rows}),
            "history_rule": _caused([lab["caused_by_change"] for _i, lab in rows]),
            "kept": {**_caused([lab["caused_by_change"] for _i, lab in kept]), "repos": len({i["repo"] for i, _l in kept}),
                     "jobs": len({(i["repo"], i["job"]) for i, _l in kept}), "by_repo": clustered(kept),
                     "coverage": round(len(kept) / len(rows), 4) if rows else None},
            "maybe_yours": _caused([lab["caused_by_change"] for _i, lab in by["maybe yours"]]),
            "flaked_before": _caused([lab["caused_by_change"] for _i, lab in by["flaked before"]]),
            "kept_by_repo_items": dict(Counter(i["repo"] for i, _l in kept))}


def _labels(path: Path) -> dict:
    if not path.exists():
        return {}
    if path.suffix == ".csv":
        return {int(r["id"]): r for r in csv.DictReader(path.open(encoding="utf-8"))}
    return {int(r["id"]): r for r in _jsonl(path)}


def tuning(wide: Path, wide_final: Path, masking_home: Path) -> dict:
    """The rule on the data it was written from: the first held-out read's calls and masking.py's failures."""
    rows = _jsonl(wide / "labelled-items.jsonl")
    labs = _labels(wide_final)
    out = {"heldout_read": measure([(r, labs[n]) for n, r in enumerate(rows, 1) if r["group"] == "safe" and n in labs])}
    items = [i for i in _jsonl(masking_home / "items.jsonl") if i.get("sample") != "none"]
    final = masking_home.parent / "final"
    first = _labels(final / "flaky.jsonl")
    by = {(i["repo"], i.get("run"), i.get("job")): (i, first.get(n)) for n, i in enumerate(items, 1)}
    asof = _labels(final / "masking.jsonl")
    by |= {(x["repo"], x["run"], x["job"]): (x, asof.get(1000 + n)) for n, x in enumerate(_jsonl(masking_home / "asof-items.jsonl"), 1)}
    pool = json.loads((masking_home / "masking-pool.json").read_text(encoding="utf-8"))
    strong = [by[(p["repo"], p["run"], p["job"])] for p in pool if p["flakes"] >= SAFE_FLAKES and p["step"] in p["flake_steps"]]
    any_flake = [by[(p["repo"], p["run"], p["job"])] for p in pool]
    out["masking_check"] = {"history_rule": measure(strong), "any_earlier_flake": measure(any_flake)}
    return out


def score(home: Path, final: Path, args) -> int:
    rows = _jsonl(home / "items.jsonl")
    sets = {"claude": _labels(home / "labels.jsonl"), "gemini": _labels(HERE / "labels-gemini-fresh.csv")}
    if final and final.exists():
        sets["adjudicated"] = _labels(final)
    out = {"prereg": "2026-10-28", "fresh": {name: measure([(r, labs[n]) for n, r in enumerate(rows, 1) if n in labs])
                                             for name, labs in sets.items() if labs}}
    if args.tune_home:
        out["tuning"] = tuning(args.tune_home, args.tune_final, args.masking_home)
    (HERE / "safe-rule-results.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=("pool", "fetch", "score"))
    ap.add_argument("--home", type=Path, required=True)
    ap.add_argument("--final", type=Path, help="the adjudicated labels, final/fresh.jsonl (score)")
    ap.add_argument("--tune-home", type=Path)
    ap.add_argument("--tune-final", type=Path)
    ap.add_argument("--masking-home", type=Path)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args(argv)
    if args.cmd == "pool":
        heldout_pool(args.home)
        return 0
    return fetch(args.home, args.seed) if args.cmd == "fetch" else score(args.home, args.final, args)


if __name__ == "__main__":
    sys.exit(main())
