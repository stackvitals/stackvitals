"""DevLake with a pattern a user would write after looking at their workflow names, not just its default: the same 25
labelled repos, a deployment is a successful run of a workflow whose name matches the pattern (no production filter,
the most generous reading), scored with the card's own rule against the final labels.

    GH_TOKEN=... python bench/accuracy/dora/devlake_configured.py --home <final work folder> \
        [--pattern "(?i)(deploy|release|publish|push-image)"]

Writes devlake-configured-results.json beside this script. Runs are read as of today (the card was read on 2026-10-21).
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from fair import mcnemar  # noqa: E402

from stackvitals.core.stats import wilson  # noqa: E402

API = "https://api.github.com"
DAYS = 90
WORKFLOW_SOURCES = {"deploy_workflow", "release_workflow", "every_merge"}


def right(dl: set, ok: set, ships: set) -> bool:
    """The card's rule for DevLake: nothing counted is right only for a repo that ships nothing; otherwise every
    workflow it counted must ship and a workflow-based source must fit the repo."""
    return ("none" in ok) if not dl else (dl <= ships and bool(ok & WORKFLOW_SOURCES))


def counted(client: httpx.Client, repo: str, pattern: re.Pattern, since: str) -> set:
    flows = client.get(f"{API}/repos/{repo}/actions/workflows", params={"per_page": 100}).json().get("workflows") or []
    out = set()
    for w in flows:
        if w.get("state") != "active" or not pattern.search(w.get("name") or ""):
            continue
        runs = client.get(f"{API}/repos/{repo}/actions/workflows/{w['id']}/runs",
                          params={"per_page": 100, "status": "success", "created": f">={since}"}).json()
        if runs.get("total_count"):
            out.add(w["path"])
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--home", type=Path, required=True)
    ap.add_argument("--pattern", default=r"(?i)(deploy|release|publish|push-image)")
    ap.add_argument("--suffix", default="", help="reads sources<suffix>-labels.csv, writes devlake-configured<suffix>-results.json")
    args = ap.parse_args(argv)
    token = os.environ.get("GH_TOKEN")
    labels = {r["repo"]: r for p in sorted(args.home.glob("labels-*.jsonl"))
              for r in (json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip())}
    card = {r["repo"]: r for r in __import__("csv").DictReader((HERE / f"sources{args.suffix}-labels.csv").open(encoding="utf-8"))}
    pattern = re.compile(args.pattern)
    since = (datetime.now(timezone.utc) - timedelta(days=DAYS)).strftime("%Y-%m-%d")
    rows = []
    with httpx.Client(headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                      timeout=30) as client:
        for repo, lab in sorted(labels.items()):
            dl = counted(client, repo, pattern, since)
            ships = {p for p, v in lab["workflows"].items() if v == "yes"}
            ok = right(dl, set(lab["sources"]), ships)
            rows.append({"repo": repo, "devlake_configured_right": ok, "stackvitals_right": card[repo]["stackvitals_right"] == "True",
                         "counted": sorted(dl)})
            print(repo, ok, sorted(dl), flush=True)
    n, k = len(rows), sum(r["devlake_configured_right"] for r in rows)
    lo, hi = wilson(k, n)
    out = {"pattern": args.pattern, "repos": n, "read": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
           "devlake_configured": {"right": k, "share": round(k / n, 4), "low": round(lo, 4), "high": round(hi, 4)},
           "against_stackvitals": mcnemar(sum(r["stackvitals_right"] and not r["devlake_configured_right"] for r in rows),
                                          sum(r["devlake_configured_right"] and not r["stackvitals_right"] for r in rows)),
           "repos_detail": [{k: v for k, v in r.items()} for r in rows]}
    (HERE / f"devlake-configured{args.suffix}-results.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "repos_detail"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
