"""How a package's source repo treats outside work, quarter by quarter, from the crawl's PR history (12 months): outside
PRs merged, first maintainer answer, how much merging rests on one person; compared with repos of similar size."""
from datetime import datetime

import duckdb

from mergescout.bench.ci import tier

MIN_DECIDED = 5
MIN_RESPONSES = 5
MIN_MERGES = 5
# Changes smaller than these are "steady": quarters of a few dozen PRs move around on their own.
RATE_STEP = 0.15
SPEED_RATIO = 1.5
# Automation that merges (Actions, merge queues, any login the crawl saw acting as a bot) is not one person merging.
BOT_MERGER = ("(lower({col}) LIKE '%[bot]' OR lower({col}) IN ('github-actions', 'github-merge-queue', 'mergify', 'kodiakhq', "
              "'bors', 'dependabot', 'renovate') OR lower({col}) IN (SELECT lower(login) FROM people WHERE kind = 'bot'))")


def _quarters(now: datetime, n: int = 4) -> list[tuple[int, int]]:
    # The last n complete quarters, oldest first (the running quarter is partial).
    year, q = now.year, (now.month - 1) // 3 + 1
    out = []
    for _ in range(n):
        q -= 1
        if q == 0:
            year, q = year - 1, 4
        out.append((year, q))
    return out[::-1]


def repo_trends(con: duckdb.DuckDBPyConnection, repos: list[str], now: datetime) -> dict[str, dict]:
    """Per repo ("owner/name"): quarterly lines, their direction and the latest quarter's place among similar repos."""
    quarters = _quarters(now)
    lo = datetime(quarters[0][0], 3 * quarters[0][1] - 2, 1, tzinfo=now.tzinfo)
    end_y, end_q = (now.year, (now.month - 1) // 3 + 1)
    hi = datetime(end_y, 3 * end_q - 2, 1, tzinfo=now.tzinfo)
    wanted = sorted({r.lower() for r in repos})
    if not wanted:
        return {}
    rows = con.execute(f"""
        WITH wanted AS (SELECT repo_id, lower(name) AS repo, stars FROM repo_meta WHERE lower(name) IN (SELECT unnest($repos))),
        w AS (SELECT p.*, wanted.repo, year(timezone('UTC', p.created_at)) AS y, quarter(timezone('UTC', p.created_at)) AS q
              FROM pr_class p JOIN wanted USING (repo_id) WHERE p.created_at >= $lo AND p.created_at < $hi)
        SELECT w.repo, w.y, w.q,
               count(*) FILTER (WHERE author_class = 'outsider') AS opened,
               count(*) FILTER (WHERE author_class = 'outsider' AND state IN ('MERGED', 'CLOSED')) AS decided,
               count(*) FILTER (WHERE author_class = 'outsider' AND merged_at IS NOT NULL) AS merged,
               median(epoch(first_human_review_at - created_at) / 3600) FILTER (
                   WHERE author_class = 'outsider' AND first_human_review_at >= created_at AND pe.kind = 'insider') AS response,
               count(*) FILTER (WHERE author_class = 'outsider' AND first_human_review_at >= created_at AND pe.kind = 'insider')
                   AS responses,
               count(*) FILTER (WHERE merged_at IS NOT NULL AND merged_by IS NOT NULL
                                AND NOT {BOT_MERGER.format(col='merged_by')}) AS merges
        FROM w LEFT JOIN people pe ON pe.repo_id = w.repo_id AND pe.login = w.first_human_review_by
        GROUP BY ALL""", {"repos": wanted, "lo": lo, "hi": hi}).fetchall()
    tops = {}
    for repo, y, q, n in con.execute(f"""
            SELECT lower(rm.name), year(timezone('UTC', p.created_at)), quarter(timezone('UTC', p.created_at)), count(*)
            FROM pr_class p JOIN repo_meta rm USING (repo_id)
            WHERE lower(rm.name) IN (SELECT unnest($repos)) AND p.merged_at IS NOT NULL AND p.merged_by IS NOT NULL
              AND NOT {BOT_MERGER.format(col='p.merged_by')} AND p.created_at >= $lo AND p.created_at < $hi
            GROUP BY 1, 2, 3, p.merged_by""", {"repos": wanted, "lo": lo, "hi": hi}).fetchall():
        tops[(repo, y, q)] = max(tops.get((repo, y, q), 0), n)
    stars = dict(con.execute("SELECT lower(name), stars FROM repo_meta WHERE lower(name) IN (SELECT unnest($repos))",
                             {"repos": wanted}).fetchall())
    cells = {(r[0], r[1], r[2]): r for r in rows}
    out = {}
    for repo in wanted:
        if repo not in stars:
            continue
        lines = []
        for y, q in quarters:
            r = cells.get((repo, y, q))
            opened, decided, merged, response, responses, merges = r[3:] if r else (0, 0, 0, None, 0, 0)
            lines.append({"quarter": f"{y}Q{q}", "outside_opened": opened, "outside_decided": decided,
                          "outside_merge_rate": round(merged / decided, 2) if decided >= MIN_DECIDED else None,
                          "first_response_hours": round(response, 1) if responses >= MIN_RESPONSES else None,
                          "merges": merges,
                          "top_merger_share": round(tops.get((repo, y, q), 0) / merges, 2) if merges >= MIN_MERGES else None})
        out[repo] = {"stars": stars[repo], "quarters": lines, "direction": _direction(lines)}
    _peers(out)
    return out


def _direction(lines: list[dict]) -> dict:
    """Earlier half against later half of the year, in plain words; None when either half has no value."""
    def halves(key):
        a = [x[key] for x in lines[:2] if x[key] is not None]
        b = [x[key] for x in lines[2:] if x[key] is not None]
        return (sum(a) / len(a), sum(b) / len(b)) if a and b else (None, None)
    out = {}
    a, b = halves("outside_merge_rate")
    out["outside_merge_rate"] = None if a is None else "falling" if b - a <= -RATE_STEP else "rising" if b - a >= RATE_STEP else "steady"
    a, b = halves("first_response_hours")
    out["first_response_hours"] = None if a is None else ("slower" if b >= a * SPEED_RATIO and b - a > 24 else
                                                          "faster" if a >= b * SPEED_RATIO and a - b > 24 else "steady")
    return out


def _peers(out: dict) -> None:
    # The latest quarter against mapped repos of the same stars tier (all of them when a tier has under 5).
    latest = {repo: t["quarters"][-1] for repo, t in out.items()}
    for repo, t in out.items():
        same = [r for r in out if r != repo and tier(out[r]["stars"]) == tier(t["stars"])]
        pool = same if len(same) >= 5 else [r for r in out if r != repo]
        t["peers"] = {}
        for key, better, words in (("outside_merge_rate", 1, ("merges outside PRs more than most similar repos",
                                                               "merges outside PRs less than most similar repos")),
                                   ("first_response_hours", -1, ("faster than most similar repos", "slower than most similar repos"))):
            mine = latest[repo][key]
            others = [latest[r][key] for r in pool if latest[r][key] is not None]
            if mine is None or not others:
                continue
            ahead = sum(1 for v in others if (v - mine) * better > 0) / len(others)
            place = words[1] if ahead >= 0.75 else words[0] if ahead <= 0.25 else "about typical for similar repos"
            t["peers"][key] = {"place": place, "peers": len(others)}
