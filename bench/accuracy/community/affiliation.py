"""How far public profiles go for the elephant factor: for crawled repos with 20+ merged PRs by people in 180 days, the
share of merged work whose author has a known organisation (profile company, or public membership of the owning org),
and the elephant factor where it can be claimed. Read with StackVitals' own affiliation code.

    GH_TOKEN=... python bench/accuracy/community/affiliation.py --crawl <crawl folder: prs/, repo_meta/> --repos 20
"""
import argparse
import json
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "src"))
from mergescout.github.graphql import GitHubGraphQL  # noqa: E402
from stackvitals.community import affiliation  # noqa: E402
from stackvitals.community.analyze import elephant  # noqa: E402

READ = datetime(2026, 10, 18, tzinfo=timezone.utc)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--crawl", type=Path, required=True)
    ap.add_argument("--repos", type=int, default=20)
    args = ap.parse_args(argv)
    con = duckdb.connect()
    rows = con.execute(f"""
        SELECT m.name, lower(p.author_login), p.author_type, p.merged_at, p.number
        FROM read_parquet('{(args.crawl / 'prs').as_posix()}/*.parquet', union_by_name = true) p
        JOIN (SELECT DISTINCT repo_id, name FROM read_parquet('{(args.crawl / 'repo_meta').as_posix()}/*.parquet',
                                                               union_by_name = true)) m USING (repo_id)
        WHERE p.merged_at >= TIMESTAMP '2026-04-21' AND p.author_type = 'User'
        QUALIFY row_number() OVER (PARTITION BY p.repo_id, p.number ORDER BY p.fetched_at DESC) = 1""").fetchall()
    by_repo = {}
    for name, login, typ, merged, number in rows:
        by_repo.setdefault(name, []).append({"n": number, "au": login, "at": typ, "mg": merged.strftime("%Y-%m-%dT%H:%M:%SZ")})
    eligible = sorted(n for n, prs in by_repo.items() if len(prs) >= 20)
    picked = random.Random(17).sample(eligible, min(args.repos, len(eligible)))
    gql, out = GitHubGraphQL(os.environ["GH_TOKEN"]), []
    for name in picked:
        prs = by_repo[name]
        logins = [a for a, _ in sorted({p["au"]: 0 for p in prs}.items())]
        aff = affiliation.collect(gql, logins)
        got = elephant(prs, aff, READ)
        if got is None:
            continue  # under 20 merged PRs by people in the window
        out.append({"repo": name, **{k: got[k] for k in ("merged", "people", "factor", "unknown_share")},
                    "top": got["orgs"][0]["org"] if got["orgs"] else None})
        print(out[-1], flush=True)
    known = [r for r in out if r["factor"] is not None]
    summary = {"repos": len(out), "factor_claimed": len(known),
               "median_unknown_share": sorted(r["unknown_share"] for r in out)[len(out) // 2] if out else None, "rows": out}
    (HERE / "affiliation-results.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
