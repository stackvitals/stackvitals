"""Find public repos whose PR runs upload readable test reports: a seeded sample of active crawl repos, one artifact
list call each; the newest test-named artifact from a non-default branch is opened and parsed."""
import json
import os
import random
import re
import sqlite3
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "features"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
import reports  # noqa: E402

OUT = Path(__file__).with_name("work") / "report-repos.jsonl"
db = sqlite3.connect(Path.home() / ".mergescout" / "mergescout.sqlite")
cols = {r[1] for r in db.execute("pragma table_info(repos)")}
where = "stars >= 100 and not archived" + (" and pushed_at >= '2026-09-29'" if "pushed_at" in cols else "")
pool = sorted(r[0] for r in db.execute(f"select name from repos where {where}"))
picked = random.Random(20261029).sample(pool, min(int(sys.argv[1]) if len(sys.argv) > 1 else 400, len(pool)))
done = {json.loads(x)["repo"] for x in OUT.read_text(encoding="utf-8").splitlines() if x.strip()} if OUT.exists() else set()
c = httpx.Client(timeout=120, follow_redirects=True, headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}",
                                                             "Accept": "application/vnd.github+json"})
with OUT.open("a", encoding="utf-8") as f:
    for repo in picked:
        if repo in done:
            continue
        try:
            r = c.get(f"https://api.github.com/repos/{repo}/actions/artifacts", params={"per_page": 100})
            if r.status_code != 200:
                row = {"repo": repo, "error": r.status_code}
            else:
                arts = [a for a in r.json().get("artifacts") or [] if not a.get("expired")]
                tests = [a for a in arts if re.search(reports.TEST_REPORTS, a.get("name") or "", re.I)]
                branches = {(a.get("workflow_run") or {}).get("head_branch") for a in tests}
                row = {"repo": repo, "test_artifacts": len(tests), "branches": len(branches)}
                if len(tests) >= 3 and len(branches) >= 2:
                    row.update(reports.look(c, repo))
        except httpx.HTTPError as exc:
            row = {"repo": repo, "error": type(exc).__name__}
        f.write(json.dumps(row) + "\n")
        f.flush()
        if row.get("parsed"):
            print("FOUND", repo, row.get("test_artifacts"), row.get("kinds"), flush=True)
print("done")
