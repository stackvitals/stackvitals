"""How much of a project's support happens outside GitHub: for public projects with a Discourse forum, the forum's new
topics in 30 days (its own about.json) against the repo's new issues (GitHub search), and how fast forum staff first
answered, read with StackVitals' own Discourse connector (staff only, no team list).

    GH_TOKEN=... python bench/accuracy/community/channels.py --home <work folder>
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "src"))
from stackvitals.connectors import discourse  # noqa: E402
from stackvitals.connectors.store import ConnectorStore  # noqa: E402
from stackvitals.core.config import parse  # noqa: E402

PROJECTS = [("python/cpython", "https://discuss.python.org"), ("rust-lang/rust", "https://users.rust-lang.org"),
            ("pytorch/pytorch", "https://discuss.pytorch.org"), ("JuliaLang/julia", "https://discourse.julialang.org"),
            ("huggingface/transformers", "https://discuss.huggingface.co")]


class Paced(httpx.Client):
    """Half a second between forum requests: public forums, read politely."""

    def get(self, *a, **k):
        time.sleep(0.5)
        return super().get(*a, **k)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--home", type=Path, required=True)
    args = ap.parse_args(argv)
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    out = {"read": now.strftime("%Y-%m-%d"), "projects": []}
    gh = httpx.Client(headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}"}, timeout=30)
    for repo, forum in PROJECTS:
        cfg = parse(f'[connectors.discourse]\nurl = "{forum}"\n')[0]
        with Paced(base_url=forum, timeout=30, headers={"User-Agent": "stackvitals-bench"}) as client:
            about = (client.get("/about.json").json().get("about") or {}).get("stats") or {}
            store = ConnectorStore(args.home / repo.replace("/", "_"), "discourse")
            pulled = discourse.pull(store, {}, cfg, now, client=client)
        stats = discourse.answers(store.load().get("topic") or [], now, days=30)
        q = f"repo:{repo} is:issue created:>={since}"
        issues = gh.get("https://api.github.com/search/issues", params={"q": q, "per_page": 1}).json().get("total_count")
        time.sleep(2)
        topics = about.get("topics_30_days")
        out["projects"].append({"repo": repo, "forum": forum, "forum_topics_30d": topics, "github_issues_30d": issues,
                                "forum_share": round(topics / (topics + issues), 4) if topics and issues is not None else None,
                                "topics_read": pulled["read"], "complete": pulled["complete"], "answers": stats})
        print(repo, topics, issues, json.dumps(stats)[:200], flush=True)
    (HERE / "channels-results.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
