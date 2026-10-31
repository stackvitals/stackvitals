"""Held-out checks of the CI rules on a wider read (`wide.py`) that none of them was written on, and the masking bar.

    python bench/accuracy/flaky/heldout.py pool --home <wide work folder>
    GH_TOKEN=... python bench/accuracy/flaky/heldout.py fetch --home <wide work folder> [--never 150] [--seed 7]
    python bench/accuracy/flaky/heldout.py score --home <wide work folder> --final <labels folder>

pool: every pull-request failure (final attempt, gatekeepers left out) on a day the read covers, with what StackVitals
would have said then (the history before it only, the repo's real default branch, a 30-day window):
- safe: called known flaky, safe to re-run (the masking bar);
- already: the default branch failed in that step in the 3 days before (the "already failing" cut);
- never: the job had never flaked (where "maybe flaky" can apply);
- flip: a pull-request flip the detector counts, with its workflow (the PR-edit rule).
fetch: the labelling evidence (log excerpt, files changed) for every safe, already and flip item and a seeded sample of
never-flaked failures, the default branch's log for each already item, and each flip's workflow file; writes
items.jsonl and view.jsonl (blind: no verdicts) for labellers. score: each rule against labels.jsonl; writes
heldout-results.json beside this script (counts only).
"""
import argparse
import base64
import csv
import json
import os
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from natural import flakes  # noqa: E402
from sample import Pacer, evidence  # noqa: E402
from views import SHOWN, rerun  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fair import by_repo  # noqa: E402

from stackvitals.ci.analyze import FAIL, _downstream, _failed_step, analyze  # noqa: E402
from stackvitals.ci.feedback import (_job_verdict, failed_on_default, failing_section, flake_kind,  # noqa: E402
                                     flaky_signature, outside_signature, same_error)
from stackvitals.ci.store import DataStore  # noqa: E402
from stackvitals.ci.triggers import PR_EVENTS, metadata_jobs, pr_metadata_triggered  # noqa: E402
from stackvitals.core.stats import wilson  # noqa: E402

API = "https://api.github.com"
CAPS = {"already": 60, "flip": 40}
HERE = Path(__file__).parent


def _when(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.exists() else []


def _group(p: dict) -> str:
    if p["verdict"] == "known flaky":
        return "safe"
    if p["main_job"]:
        return "already"
    if p["verdict"] == "flip":
        return "flip"
    return "never" if p["verdict"] == "new" and not p["flakes"] else "other"


def pool(home: Path) -> list[dict]:
    out = []
    for folder in sorted((home / "ci").iterdir()):
        store = DataStore(folder)
        data, state = store.load(), store.state()
        repo, branch, start = folder.name.replace("__", "/", 1), state.get("default_branch"), state.get("covered_from")
        if not start:
            continue
        runs = {(r["id"], r["att"]): r for r in data["runs"]}
        final = {}
        for rid, att in runs:
            final[rid] = max(att, final.get(rid, 0))
        for rid, att in sorted(final.items()):
            run = runs[(rid, att)]
            if run.get("ev") not in PR_EVENTS or (run.get("cr") or "") < start:
                continue
            jobs = [j for j in data["jobs"] if j["run"] == rid and j["att"] == att]
            failed = [j for j in jobs if j["c"] in FAIL and not _downstream(j, jobs)]
            if not failed:
                continue
            now = _when(run["cr"])
            earlier = {(r["id"], r["att"]) for r in data["runs"] if _when(r["cr"]) < now}
            before = {"runs": [runs[k] for k in earlier], "jobs": [j for j in data["jobs"] if (j["run"], j["att"]) in earlier]}
            states = {(j["workflow"], j["job"]): j for j in analyze(before, now, window_days=30, default_branch=branch)["jobs"]}
            for j in failed:
                entry, step = states.get((run.get("path"), j["n"])), _failed_step(j)
                verdict = _job_verdict(entry, step)
                main = failed_on_default(data, run, j, step, branch) if verdict in ("new", "flaked before") else None
                out.append({"repo": repo, "run": rid, "att": att, "job": j["n"], "job_id": j["id"], "workflow": run.get("path"),
                            "step": step, "verdict": verdict, "flakes": (entry or {}).get("flake_events", 0),
                            "main_job": main["job"] if main else None, "main_ago": main["ago"] if main else None})
        # Flips the detector counts on pull requests (it never needs as-of history: the flip is its own evidence).
        for (path, name), events in flakes(data).items():
            for e in events:
                run = runs.get((e["run"], final.get(e["run"], 0))) or {}
                if e["kind"] == "flip" and run.get("ev") in PR_EVENTS and (run.get("cr") or "") >= start:
                    j = next((x for x in data["jobs"] if x["run"] == e["run"] and x["n"] == name and x["c"] in FAIL), None)
                    if j:
                        out.append({"repo": repo, "run": e["run"], "att": j["att"], "job": name, "job_id": j["id"],
                                    "workflow": path, "step": e["step"], "verdict": "flip", "flakes": None,
                                    "main_job": None, "main_ago": None})
    (home / "heldout-pool.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    groups = Counter(_group(p) for p in out)
    print(f"{len(out)} failures in {len({p['repo'] for p in out})} repos: {dict(groups)}; "
          f"safe calls from {len({(p['repo'], p['job']) for p in out if p['verdict'] == 'known flaky'})} jobs")
    return out


def fetch(home: Path, never: int, seed: int) -> int:
    token = os.environ["GH_TOKEN"]
    client = httpx.Client(timeout=60, follow_redirects=True, headers={"Authorization": f"Bearer {token}",
                                                                      "Accept": "application/vnd.github+json"})
    pacer = Pacer(client)
    pool_ = json.loads((home / "heldout-pool.json").read_text(encoding="utf-8"))
    for p in pool_:
        p["group"] = _group(p)
    rng = random.Random(seed)
    # At most 3 safe calls per job, so the bar isn't one job's record; seeded samples of the other groups.
    safe, by_job = [p for p in pool_ if p["group"] == "safe"], defaultdict(list)
    for p in safe:
        by_job[(p["repo"], p["job"])].append(p)
    picked = [p for job in sorted(by_job) for p in rng.sample(by_job[job], min(3, len(by_job[job])))]
    for group, cap in (("already", CAPS["already"]), ("flip", CAPS["flip"]), ("never", never)):
        rest = [p for p in pool_ if p["group"] == group]
        picked += rng.sample(rest, min(cap, len(rest)))
    done = {(r["repo"], r["job_id"]) for r in _jsonl(home / "items.jsonl")}
    triggers_path = home / "workflow-triggers.json"
    triggers = json.loads(triggers_path.read_text(encoding="utf-8")) if triggers_path.exists() else {}
    with (home / "items.jsonl").open("a", encoding="utf-8") as f:
        for p in picked:
            if (p["repo"], p["job_id"]) in done:
                continue
            data = DataStore(home / "ci" / p["repo"].replace("/", "__")).load()
            pacer.before()
            item = evidence(client, p["repo"], {k: p[k] for k in ("workflow", "job", "run", "att", "job_id")}, data)
            row = {**item, "group": p["group"], "verdict": p["verdict"], "flakes": p["flakes"], "rerun": rerun(item, data)}
            if p["main_job"]:
                resp = client.get(f"{API}/repos/{p['repo']}/actions/jobs/{p['main_job']}/logs")
                row["main_log"] = failing_section(resp.text) if resp.status_code == 200 else None
            key = f"{p['repo']}|{p['workflow']}"
            if p["group"] == "flip" and key not in triggers:
                resp = client.get(f"{API}/repos/{p['repo']}/contents/{p['workflow']}")
                text = base64.b64decode(resp.json()["content"]).decode("utf-8", "replace") if resp.status_code == 200 else ""
                triggers[key] = {"edits": pr_metadata_triggered(text), "jobs": sorted(metadata_jobs(text)), "read": bool(text)}
                triggers_path.write_text(json.dumps(triggers, indent=1, sort_keys=True), encoding="utf-8")
            pacer.after()
            f.write(json.dumps(row) + "\n")
            f.flush()
    rows = _jsonl(home / "items.jsonl")
    # Never-flaked failures are labelled only where the signs match; the others aren't needed for any rule.
    keep = [r for r in rows if r["group"] != "never" or (flaky_signature(r.get("log")) and not outside_signature(r.get("log")))]
    view = [json.dumps({"id": n, **{k: r.get(k) for k in SHOWN}, "rerun": r["rerun"]}) for n, r in enumerate(keep, 1)]
    (home / "view.jsonl").write_text("\n".join(view) + "\n", encoding="utf-8")
    (home / "labelled-items.jsonl").write_text("".join(json.dumps(r) + "\n" for r in keep), encoding="utf-8")
    print(f"{len(rows)} items read; {len(keep)} to label: {dict(Counter(r['group'] for r in keep))}")
    return 0


def _caused(labels: list[str]) -> dict:
    yes, no = labels.count("yes"), labels.count("no")
    lo, hi = wilson(yes, yes + no)
    return {"n": len(labels), "caused": yes, "not_caused": no, "unclear": len(labels) - yes - no,
            "caused_low": round(lo, 4), "caused_high": round(hi, 4)}


def measure(rows: list[dict], labels: dict, triggers: dict) -> dict:
    """Each rule against one set of labels (keyed by item number)."""
    by = defaultdict(list)
    for n, r in enumerate(rows, 1):
        if n in labels:
            by[r["group"]].append((r, labels[n]))
    safe = by["safe"]
    per_job = Counter((r["repo"], r["job"]) for r, _l in safe)
    already = by["already"]
    same_rows = [(r, lab) for r, lab in already if same_error(failing_section(r.get("log")), r.get("main_log"))]
    same = [lab["caused_by_change"] for _r, lab in same_rows]
    right = lambda lab: lab["caused_by_change"] == "no" and lab["own_failure"] == "yes"  # noqa: E731
    edits = lambda r: bool((triggers.get(f"{r['repo']}|{r['workflow']}") or {}).get("edits"))  # noqa: E731
    flips = by["flip"]
    every = [(r, labels[n]) for n, r in enumerate(rows, 1) if n in labels]
    outside_rows = [(r, lab) for r, lab in every if outside_signature(r.get("log"))]
    outside = [lab["caused_by_change"] for _r, lab in outside_rows]
    # Items cluster by repo, so each headline also gets ranges over repos (fair.by_repo).
    clustered = lambda pairs: by_repo([(r["repo"], lab["caused_by_change"] == "yes") for r, lab in pairs  # noqa: E731
                                       if lab["caused_by_change"] in ("yes", "no")])
    kinds = defaultdict(Counter)
    for r, lab in every:
        if lab["caused_by_change"] == "no" and (k := flake_kind(r.get("log"))):
            kinds[k][lab["cause"]] += 1
    return {"repos": len({r["repo"] for r, _l in every}),
            "masking": {**_caused([lab["caused_by_change"] for _r, lab in safe]), "jobs": len(per_job),
                        "repos": len({k[0] for k in per_job})},
            "already_failing": {"same_step": _caused([lab["caused_by_change"] for _r, lab in already]),
                                "same_error": _caused(same)},
            "maybe_flaky": _caused([lab["caused_by_change"] for _r, lab in by["never"]]),
            "flips": {"in_pr_edit_workflows": {"n": sum(edits(r) for r, _l in flips),
                                               "real": sum(edits(r) and right(lab) for r, lab in flips)},
                      "elsewhere": {"n": sum(not edits(r) for r, _l in flips),
                                    "real": sum(not edits(r) and right(lab) for r, lab in flips)}},
            "outside": _caused(outside),
            "by_repo": {"masking": clustered(safe), "outside": clustered(outside_rows),
                        "already_same_error": clustered(same_rows), "maybe_flaky": clustered(by["never"])},
            "kinds": {k: dict(v) for k, v in kinds.items()}}


def score(home: Path, final: Path | None) -> int:
    rows = _jsonl(home / "labelled-items.jsonl")
    path = home / "workflow-triggers.json"
    triggers = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    sets = {"claude": {r["id"]: r for r in _jsonl(home / "labels.jsonl")},
            "gemini": {int(r["id"]): r for r in csv.DictReader((HERE / "labels-gemini-heldout.csv").open(encoding="utf-8"))}}
    if final and final.exists():
        sets["adjudicated"] = {int(r["id"]): r for r in _jsonl(final)}
    out = {name: measure(rows, labels, triggers) for name, labels in sets.items()}
    (HERE / "heldout-results.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=("pool", "fetch", "score"))
    ap.add_argument("--home", type=Path, required=True)
    ap.add_argument("--final", type=Path, help="the adjudicated labels file, final/heldout.jsonl (score)")
    ap.add_argument("--never", type=int, default=150)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args(argv)
    if args.cmd == "pool":
        pool(args.home)
        return 0
    return fetch(args.home, args.never, args.seed) if args.cmd == "fetch" else score(args.home, args.final)


if __name__ == "__main__":
    sys.exit(main())
