"""How many GitHub API requests StackVitals' CI reader spends on a repo: a cold read of the last day or days (what the
Action's first run and the local report do), counted by the same client, with how many runs and jobs it read.
The Action's later runs read only what finished since the last one, so requests per run read is the steady cost.

    GH_TOKEN=... python bench/accuracy/features/api_use.py owner/repo [owner/repo ...] --out <folder> [--days 1]
        [--budget 900]

A read that hits the budget stops and says so; the per-run cost is still measured on what it read.
"""
import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from stackvitals.ci.api import ActionsAPI  # noqa: E402
from stackvitals.ci.store import DataStore  # noqa: E402
from stackvitals.core.services import ci_result  # noqa: E402


def measure(repo: str, token: str, days: int, budget: int) -> dict:
    made = []

    def make_api(tok, name, max_requests):
        api = ActionsAPI(tok, name, max_requests=max_requests)
        made.append(api)
        return api
    began = time.time()
    with tempfile.TemporaryDirectory() as home:
        result, source = ci_result(repo, days, token, Path(home), make_api=make_api, budget=budget,
                                   now=datetime.now(timezone.utc))
        data = DataStore(Path(home) / "ci" / repo.replace("/", "__")).load()
    runs, jobs = len(data.get("runs") or []), len(data.get("jobs") or [])
    used = sum(a.requests for a in made)
    collect = result.get("collect") or {}
    return {"repo": repo, "days": days, "source": source, "requests": used, "runs_read": runs, "jobs_read": jobs,
            "requests_per_run": round(used / runs, 2) if runs else None, "complete": collect.get("complete"),
            "stopped": collect.get("stopped"), "seconds": round(time.time() - began)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("repos", nargs="+")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--budget", type=int, default=900)
    args = ap.parse_args(argv)
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    rows = []
    for repo in args.repos:
        rows.append(measure(repo, token, args.days, args.budget))
        print(json.dumps(rows[-1]), flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / "api-use-results.json"
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    path.write_text(json.dumps(old + rows, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
