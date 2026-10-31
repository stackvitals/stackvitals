"""How often a repo's DORA deployment-frequency tier depends on what counts as a deployment.

For each crawled repo with at least 10 days with a merge in the 13 weeks before it was read, the tier is computed two
ways: every merged PR as a deployment (DevLake's merge-as-deploy option: the median number of days with a deployment per
week and per month), and GitHub releases as deployments, from the crawl's release count (the newest 20 releases, or
100 from 2026-10-22, so a repo at that cap is "that tier or better"). Reported: the tiers under each definition and the share of repos whose
tier certainly changes.

    python bench/accuracy/dora/spread.py <crawl folder with prs/ and repo_meta/>
"""
import argparse
import json
import statistics
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb

ORDER = ["elite", "high", "medium", "low"]
CAPS = (20, 100)  # the crawl reads the newest 20 releases (100 from 2026-10-22)


def _merge_tier(days: set, now: datetime) -> str:
    # DevLake's 2023 rule: elite with a median of 5+ deployment days a week, high with 1+, medium with 1+ a month.
    weeks = [sum(1 for k in range(7) if (now - timedelta(days=7 * w + k)).date() in days) for w in range(13)]
    months = [sum(1 for k in range(30) if (now - timedelta(days=30 * m + k)).date() in days) for m in range(3)]
    per_week, per_month = statistics.median(weeks), statistics.median(months)
    return "elite" if per_week >= 5 else "high" if per_week >= 1 else "medium" if per_month >= 1 else "low"


def _release_tiers(releases: int | None, last: datetime | None, now: datetime) -> list[str]:
    """The tiers releases allow, spread evenly over the year: exact under the crawl's cap (the newest 20 releases until
    2026-10-22, 100 after), and that tier or better at the cap."""
    if not releases or not last or (now - last).days > 365:
        return ["low"]
    implied = "elite" if releases >= 260 else "high" if releases >= 52 else "medium" if releases >= 12 else "low"
    return ORDER[: ORDER.index(implied) + 1] if releases in CAPS else [implied]


def run(folder: Path) -> dict:
    con = duckdb.connect()
    meta = con.execute(f"""
        SELECT repo_id, releases_12m, last_release_at, fetched_at
        FROM read_parquet('{(folder / 'repo_meta' / '*.parquet').as_posix()}', union_by_name = true)
        QUALIFY row_number() OVER (PARTITION BY repo_id ORDER BY fetched_at DESC) = 1""").fetchall()
    merges = con.execute(f"""
        SELECT repo_id, list(DISTINCT CAST(merged_at AS DATE)), count(*)
        FROM read_parquet('{(folder / 'prs' / '*.parquet').as_posix()}', union_by_name = true)
        WHERE merged_at IS NOT NULL AND coalesce(author_type, 'User') <> 'Bot' AND NOT lower(coalesce(author_login, '')) LIKE '%[bot]'
        GROUP BY repo_id""").fetchall()
    days_by = {r: (set(days), n) for r, days, n in merges}
    tiers, changed, maybe, total = Counter(), 0, 0, 0
    for repo, releases, last, fetched in meta:
        if repo not in days_by or not fetched:
            continue
        now = fetched if fetched.tzinfo else fetched.replace(tzinfo=timezone.utc)
        recent = {d for d in days_by[repo][0] if (now.date() - d).days < 91}
        if sum(1 for _ in recent) < 10:
            continue
        total += 1
        by_merge = _merge_tier(recent, now)
        last = last.replace(tzinfo=timezone.utc) if last and not last.tzinfo else last
        allowed = _release_tiers(releases, last, now)
        tiers[(by_merge, "/".join(allowed))] += 1
        if by_merge not in allowed:
            changed += 1
        elif len(allowed) > 1:
            maybe += 1
    return {"repos": total, "tier_changes": changed, "tier_changes_share": round(changed / total, 4) if total else None,
            "undecided_capped": maybe, "by_merges_then_releases": {f"{a} -> {b}": n for (a, b), n in tiers.most_common()},
            "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("folder", type=Path)
    ap.add_argument("--out", type=Path, default=Path(__file__).with_name("spread-results.json"))
    args = ap.parse_args(argv)
    out = run(args.folder)
    args.out.write_text(json.dumps(out, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
