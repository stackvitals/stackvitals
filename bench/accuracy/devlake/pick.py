"""The head-to-head's repos, by the pre-registered rule: the crawl's repos with 100+ stars, not archived and pushed in
the last 30 days, sorted by name and shuffled with seed 28; checked in that order, the first five with 10+ production
deployments and 30-300 merged pull requests in the last 90 days.

    GH_TOKEN=... python bench/accuracy/devlake/pick.py   # writes repos.json beside this file
"""
import json
import os
import random
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
SNAPSHOT = Path.home() / ".mergescout" / "mergescout.sqlite"
PROD = {"production", "prod", "live"}
WANT, MAX_CHECKED = 5, 1500


def gh(client: httpx.Client, path: str, params: dict | None = None):
    for _ in range(3):
        r = client.get(f"https://api.github.com{path}", params=params)
        if r.status_code in (403, 429) and "rate limit" in r.text.lower():
            time.sleep(60)
            continue
        return r.json() if r.status_code == 200 else None
    return None


def main() -> int:
    con = sqlite3.connect(SNAPSHOT)
    built = max(r[0] for r in con.execute("SELECT fetched_at FROM repos WHERE fetched_at IS NOT NULL LIMIT 1000"))
    cut = (datetime.fromisoformat(built.replace("Z", "+00:00")) - timedelta(days=30)).isoformat()[:19]
    pool = sorted(r[0] for r in con.execute("SELECT name FROM repos WHERE stars >= 100 AND NOT archived AND pushed_at >= ?", (cut,)))
    random.Random(28).shuffle(pool)
    since = datetime.now(timezone.utc) - timedelta(days=90)
    client = httpx.Client(timeout=30, headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}", "Accept": "application/vnd.github+json"})
    rows, drawn = [], []
    for repo in pool[:MAX_CHECKED]:
        deps = gh(client, f"/repos/{repo}/deployments", {"per_page": 100}) or []
        prod = [d for d in deps if (d.get("environment") or "").lower() in PROD and d.get("created_at", "") >= since.isoformat()[:19]]
        merged = None
        if len(prod) >= 10:
            found = gh(client, "/search/issues", {"q": f"repo:{repo} is:pr is:merged merged:>={since.date()}", "per_page": 1})
            merged = (found or {}).get("total_count")
            time.sleep(2.2)  # search allows 30 a minute
        ok = len(prod) >= 10 and merged is not None and 30 <= merged <= 300
        rows.append({"repo": repo, "production_deployments_90d": len(prod), "merged_prs_90d": merged, "eligible": ok})
        if ok:
            drawn.append(repo)
            print("eligible", repo, len(prod), merged, flush=True)
        if len(drawn) >= WANT + 3:  # three spares for repos DevLake can't collect
            break
    out = {"picked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "pool": len(pool), "checked": len(rows),
           "drawn": drawn[:WANT], "spares": drawn[WANT:], "rows": rows}
    (HERE / "repos.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print("pool", len(pool), "checked", len(rows), "drawn", drawn[:WANT], "spares", drawn[WANT:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
