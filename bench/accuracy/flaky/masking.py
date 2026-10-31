"""Masking without hindsight: pull-request failures of jobs that had flaked before, each judged with the history up to
that failure only, and how often the change caused the ones a rule calls safe to re-run.

    python bench/accuracy/flaky/masking.py pool --home <work folder>
    GH_TOKEN=... python bench/accuracy/flaky/masking.py fetch --home <work folder>
    python bench/accuracy/flaky/masking.py score --home <work folder>

pool reads the sample's cached CI data; fetch keeps evidence for the failures the main sample didn't label and writes
view-asof.jsonl for blind labelling (labels go in asof-labels.jsonl); score writes masking-results.json and
masking-labels.csv (links and labels) beside this script. Old rule: any flake makes a failure known flaky. New rule:
3 or more flakes in the step that failed now (`ci/feedback.py`, SAFE_FLAKES).
"""
import argparse
import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import httpx

from stackvitals.ci.analyze import FAIL, _downstream, _failed_step, analyze
from stackvitals.ci.feedback import SAFE_FLAKES, _verdict
from stackvitals.ci.store import DataStore
from stackvitals.core.stats import wilson

sys.path.insert(0, str(Path(__file__).parent))
from sample import evidence  # noqa: E402
from views import SHOWN, rerun  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fair import by_repo  # noqa: E402

HERE = Path(__file__).parent


def _when(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.exists() else []


def pool(home: Path) -> list[dict]:
    sampled = {(i["repo"], i.get("run"), i.get("job")) for i in _jsonl(home / "items.jsonl")}
    out = []
    for folder in sorted((home / "ci").iterdir()):
        data = DataStore(folder).load()
        runs = {(r["id"], r["att"]): r for r in data.get("runs") or []}
        final = {}
        for rid, att in runs:
            final[rid] = max(att, final.get(rid, 0))
        for rid, att in sorted(final.items()):
            run = runs[(rid, att)]
            jobs = [j for j in data["jobs"] if j["run"] == rid and j["att"] == att]
            failed = [j for j in jobs if j["c"] in FAIL and not _downstream(j, jobs)]
            if not run.get("pr") or not failed:
                continue
            now = _when(run["cr"])
            before = {"runs": [r for r in data["runs"] if _when(r["cr"]) < now],
                      "jobs": [j for j in data["jobs"] if (j["run"], j["att"]) in runs and _when(runs[(j["run"], j["att"])]["cr"]) < now]}
            if not before["runs"]:
                continue
            state = {(j["workflow"], j["job"]): j for j in analyze(before, now, window_days=14)["jobs"]}
            for j in failed:
                e = state.get((run.get("path"), j["n"]))
                if e and e.get("flake_events"):
                    out.append({"repo": folder.name.replace("__", "/", 1), "run": rid, "att": att, "job": j["n"], "job_id": j["id"],
                                "workflow": run.get("path"), "step": _failed_step(j), "flakes": e["flake_events"],
                                "state": e["state"], "flake_steps": e.get("flake_steps") or [],
                                "labelled": (folder.name.replace("__", "/", 1), rid, j["n"]) in sampled})
    (home / "masking-pool.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"{len(out)} failures, {sum(p['labelled'] for p in out)} already labelled")
    return out


def fetch(home: Path) -> int:
    client = httpx.Client(timeout=60, follow_redirects=True, headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}",
                                                                      "Accept": "application/vnd.github+json"})
    todo = [p for p in json.loads((home / "masking-pool.json").read_text(encoding="utf-8")) if not p["labelled"]]
    rows, view = [], []
    for n, p in enumerate(todo, 1):
        data = DataStore(home / "ci" / p["repo"].replace("/", "__")).load()
        item = {"sample": "asof_known", "workflow": p["workflow"], "job": p["job"], "run": p["run"], "att": p["att"], "job_id": p["job_id"]}
        full = evidence(client, p["repo"], item, data)
        rows.append(full)
        view.append(json.dumps({"id": 1000 + n, **{k: full.get(k) for k in SHOWN}, "rerun": rerun(full, data)}))
    (home / "asof-items.jsonl").write_text("".join(json.dumps(x) + "\n" for x in rows), encoding="utf-8")
    (home / "view-asof.jsonl").write_text("\n".join(view) + "\n", encoding="utf-8")
    print(f"{len(rows)} items for labelling")
    return 0


def _share(causes: list[str]) -> dict:
    sure = [c for c in causes if c != "unclear"]
    k = sum(c == "yes" for c in sure)
    lo, hi = wilson(k, len(sure))
    return {"n": len(sure), "caused_by_change": k, "share": round(k / len(sure), 4) if sure else None,
            "low": round(lo, 4), "high": round(hi, 4), "unclear": len(causes) - len(sure)}


def _recall(rows: list[dict], key: str) -> dict:
    """Of the failures the change didn't cause, the share a rule calls safe to re-run: what its caution costs."""
    harmless = [r for r in rows if r["caused_by_change"] == "no"]
    k = sum(bool(r[key]) for r in harmless)
    lo, hi = wilson(k, len(harmless))
    return {"n": len(harmless), "called_safe": k, "share": round(k / len(harmless), 4) if harmless else None,
            "low": round(lo, 4), "high": round(hi, 4)}


def summarise(rows: list[dict]) -> dict:
    return {"failures": len(rows), "repos": len({r["repo"] for r in rows}), "safe_flakes": SAFE_FLAKES,
            "old_rule": _share([r["caused_by_change"] for r in rows if r["old_safe"]]),
            "new_rule": _share([r["caused_by_change"] for r in rows if r["new_safe"]]),
            "new_rule_demoted": _share([r["caused_by_change"] for r in rows if r["old_safe"] and not r["new_safe"]]),
            "harmless_called_safe": {"old_rule": _recall(rows, "old_safe"), "new_rule": _recall(rows, "new_safe")},
            "by_repo": by_repo([(r["repo"], r["caused_by_change"] == "yes") for r in rows
                               if r["new_safe"] and r["caused_by_change"] in ("yes", "no")])}


def score(home: Path) -> int:
    items = [i for i in _jsonl(home / "items.jsonl") if i.get("sample") != "none"]
    labels = {r["id"]: r for r in _jsonl(home / "labels.jsonl")}
    by_key = {(i["repo"], i.get("run"), i.get("job")): labels[n] for n, i in enumerate(items, 1)}
    asof = _jsonl(home / "asof-items.jsonl")
    asof_labels = {r["id"]: r for r in _jsonl(home / "asof-labels.jsonl")}
    by_key |= {(x["repo"], x["run"], x["job"]): asof_labels[1000 + n] for n, x in enumerate(asof, 1)}
    rows = []
    for p in json.loads((home / "masking-pool.json").read_text(encoding="utf-8")):
        lab = by_key[(p["repo"], p["run"], p["job"])]
        old = _verdict({"state": p["state"], "flake_events": p["flakes"]}) == "known flaky"
        new = old and p["flakes"] >= SAFE_FLAKES and p["step"] in p["flake_steps"]
        rows.append({**p, "old_safe": old, "new_safe": new, "caused_by_change": lab["caused_by_change"]})
    out = summarise(rows)
    (HERE / "masking-results.json").write_text(json.dumps(out, indent=1, sort_keys=True), encoding="utf-8")
    with (HERE / "masking-labels.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["repo", "run", "job", "url", "flakes_before", "step_matches", "old_rule", "new_rule", "caused_by_change"])
        for r in rows:
            w.writerow([r["repo"], r["run"], r["job"], f"https://github.com/{r['repo']}/actions/runs/{r['run']}/job/{r['job_id']}",
                        r["flakes"], r["step"] in r["flake_steps"], "safe" if r["old_safe"] else "look",
                        "safe" if r["new_safe"] else "look", r["caused_by_change"]])
    print(json.dumps(out, indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=("pool", "fetch", "score"))
    ap.add_argument("--home", type=Path, required=True)
    args = ap.parse_args(argv)
    if args.cmd == "pool":
        pool(args.home)
        return 0
    return fetch(args.home) if args.cmd == "fetch" else score(args.home)


if __name__ == "__main__":
    sys.exit(main())
