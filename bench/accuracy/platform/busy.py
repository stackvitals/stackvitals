"""Does the built-in token keep up with a busy repo? The workflow token allows 1,000 REST requests an hour per repo
(15,000 on Enterprise Cloud). This reads one day of a repo's CI with StackVitals' own collector from nothing, counting
requests per run read, then uses each busy repo's completed runs per day (one search request each) to say how many
requests an hour CI Health needs there.

    GH_TOKEN=... python bench/accuracy/platform/busy.py --sample astral-sh/uv --busy microsoft/vscode home-assistant/core
"""
import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "src"))
from stackvitals.core import services  # noqa: E402
from stackvitals.ci.api import ActionsAPI  # noqa: E402

LIMIT = 1000


def cost(repo: str, token: str, now: datetime) -> dict:
    made = []

    def counting(tok, name, **kw):
        api = ActionsAPI(tok, name, **kw)
        made.append(api)
        return api
    with tempfile.TemporaryDirectory() as home:
        result, _ = services.ci_result(repo, 1, token, Path(home), make_api=counting, now=now, budget=3000, tests=True,
                                       window=1, owners=False)
    runs = (result.get("summary") or {}).get("runs") or len(result.get("runs") or [])
    requests = sum(a.requests for a in made)
    return {"repo": repo, "runs": runs, "requests": requests, "per_run": round(requests / max(runs, 1), 2)}


def runs_per_day(repo: str, token: str, now: datetime, days: int = 7) -> float:
    api = ActionsAPI(token, repo, max_requests=days + 2)
    counts = []
    for d in range(1, days + 1):
        day = (now - timedelta(days=d)).strftime("%Y-%m-%d")
        counts.append(api._get(f"/repos/{repo}/actions/runs", {"created": day, "status": "completed", "per_page": 1})["total_count"])
    return sum(counts) / len(counts)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sample", required=True)
    ap.add_argument("--busy", nargs="+", required=True)
    ap.add_argument("--measured", help="repo:runs:requests from an earlier read, instead of reading the sample again")
    args = ap.parse_args(argv)
    token, now = os.environ["GH_TOKEN"], datetime.now(timezone.utc)
    if args.measured:
        repo, runs, requests = args.measured.split(":")
        sample = {"repo": repo, "runs": int(runs), "requests": int(requests), "per_run": round(int(requests) / int(runs), 2)}
    else:
        sample = cost(args.sample, token, now)
    print(sample, flush=True)
    out = {"read": now.strftime("%Y-%m-%d"), "sample": sample, "busy": []}
    for repo in args.busy:
        per_day = runs_per_day(repo, token, now)
        need = per_day / 24 * sample["per_run"]
        out["busy"].append({"repo": repo, "runs_per_day": round(per_day), "requests_per_hour": round(need),
                            "share_of_limit": round(need / LIMIT, 3)})
        print(out["busy"][-1], flush=True)
    (HERE / "busy-results.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
