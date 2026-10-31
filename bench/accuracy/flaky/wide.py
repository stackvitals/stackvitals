"""A wider, cheaper read for the masking bar and the held-out checks: more repos, 30 days, and jobs only for the runs
that matter.

Repos come from the crawl's CI records, the flakiest first (re-run share times pushes), leaving out repos an earlier
sample read. Each repo is read a day at a time, newest first, for up to 30 days or until its budget runs out, so the
days it covers are complete. Jobs are read only for runs that were re-run, runs that failed (pull requests and the
default branch), and runs on a tree that both passed and failed that day: a run that passed first time on code that
never failed can't make a flake event or a failure to judge. The store has the same shape as the Action's, so the
product's own detector judges it.

    GH_TOKEN=... python bench/accuracy/flaky/wide.py --records <ci records> --home <work folder> --exclude <old home>
                                                     [--repos 40] [--budget 400]

Paced to at most 1,000 requests an hour and never below 2,000 left on the token; a repo already read is skipped, so it
resumes.
"""
import argparse
import gzip
import json
import os
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from sample import Pacer  # noqa: E402

from stackvitals.ci.api import ActionsAPI, APIError, OutOfBudget  # noqa: E402
from stackvitals.ci.collect import _fetch  # noqa: E402
from stackvitals.ci.store import DataStore  # noqa: E402
from stackvitals.ci.triggers import PR_EVENTS  # noqa: E402

DAYS = 30


def frame(records: Path, exclude: set[str], n: int) -> list[dict]:
    latest = {}
    for path in sorted(records.glob("ci-*.ndjson.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    latest[r["repo"].lower()] = r
    pool = [r for k, r in latest.items() if r["pushes"] >= 20 and r["rerun_share"] >= 0.05 and k not in exclude]
    return sorted(pool, key=lambda r: (-r["rerun_share"] * r["pushes"], r["repo"].lower()))[:n]


def wanted(runs: list[dict], default_branch: str | None) -> list[dict]:
    """The runs whose jobs a flake event or a failure to judge can come from."""
    results = defaultdict(set)
    for r in runs:
        results[(r.get("path"), r.get("event"), (r.get("head_commit") or {}).get("tree_id"))].add(r.get("conclusion"))
    mixed = {k for k, v in results.items() if k[2] and "success" in v and v & {"failure", "timed_out"}}
    keep = []
    for r in runs:
        key = (r.get("path"), r.get("event"), (r.get("head_commit") or {}).get("tree_id"))
        failed = r.get("conclusion") in ("failure", "timed_out")
        if ((r.get("run_attempt") or 1) > 1 or key in mixed or (failed and r.get("event") in PR_EVENTS)
                or (failed and r.get("event") == "push" and r.get("head_branch") == default_branch)):
            keep.append(r)
    return keep


def read(api: ActionsAPI, store: DataStore, now: datetime) -> dict:
    info = api._get(f"/repos/{api.repo}")
    branch = info.get("default_branch")
    listed = kept = stored = 0
    covered, stop = None, None
    with ThreadPoolExecutor(max_workers=5) as pool:
        for back in range(DAYS + 1):
            day = (now.date() - timedelta(days=back)).isoformat()
            try:
                runs = [r for r in api.runs_on_day(day)
                        if r.get("status") == "completed" and not (r.get("path") or "").startswith("dynamic/")]
            except OutOfBudget as exc:
                stop = str(exc)
                break
            keep = wanted(runs, branch)
            futures = [pool.submit(_fetch, api, r, n) for r in keep for n in range(1, (r.get("run_attempt") or 1) + 1)]
            for fut in futures:
                try:
                    store.add(fut.result(), day)
                    stored += 1
                except OutOfBudget as exc:
                    stop = stop or str(exc)
                except APIError:
                    continue
            if stop:
                break  # this day is incomplete, so it doesn't count as covered
            listed, kept, covered = listed + len(runs), kept + len(keep), day
    store.save_state({**store.state(), "default_branch": branch, "wide": "done", "covered_from": covered,
                      "language": info.get("language")})
    return {"listed": listed, "kept": kept, "stored": stored,
            "covered_from": covered, "stopped": stop, "default_branch": branch}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--records", type=Path, required=True)
    ap.add_argument("--home", type=Path, required=True)
    ap.add_argument("--exclude", type=Path, action="append", default=[], help="an earlier work folder whose repos to skip")
    ap.add_argument("--repos", type=int, default=40)
    ap.add_argument("--budget", type=int, default=400, help="requests per repo at most")
    args = ap.parse_args(argv)
    token = os.environ["GH_TOKEN"]
    exclude = {d.name.replace("__", "/", 1).lower() for home in args.exclude if (home / "ci").exists()
               for d in (home / "ci").iterdir()}
    chosen = frame(args.records, exclude, args.repos)
    args.home.mkdir(parents=True, exist_ok=True)
    (args.home / "frame.json").write_text(json.dumps(chosen, indent=1), encoding="utf-8")
    client = httpx.Client(timeout=60, follow_redirects=True, headers={"Authorization": f"Bearer {token}",
                                                                      "Accept": "application/vnd.github+json"})
    pacer, now = Pacer(client), datetime.now(timezone.utc)
    branches_path = args.home / "default-branches.json"
    branches = json.loads(branches_path.read_text(encoding="utf-8")) if branches_path.exists() else {}
    for r in chosen:
        repo = r["repo"]
        store = DataStore(args.home / "ci" / repo.replace("/", "__"))
        if store.state().get("wide") == "done":
            continue
        pacer.before()
        try:
            got = read(ActionsAPI(token, repo, max_requests=args.budget), store, now)
        except (APIError, OutOfBudget) as exc:
            got = {"skipped": type(exc).__name__}
        pacer.after()
        if got.get("default_branch"):
            branches[repo] = got["default_branch"]
            branches_path.write_text(json.dumps(branches, indent=1, sort_keys=True), encoding="utf-8")
        print(repo, json.dumps(got), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
