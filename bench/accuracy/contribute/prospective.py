"""The finder's prospective test (preregistration.md): freeze today's ranking of every open beginner issue, then, from
2027-03-20, score which ones outsiders' pull requests merged.

    python bench/accuracy/contribute/prospective.py freeze --snapshot ~/.mergescout/mergescout.sqlite
    python bench/accuracy/contribute/prospective.py score --crawl <crawl folder: prs/, repo_meta/>   # 2027-03-20 or later
"""
import argparse
import gzip
import hashlib
import json
import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
FROZEN, MANIFEST = HERE / "frozen.json.gz", HERE / "frozen-manifest.json"
NOT_BEFORE = date(2027, 3, 20)
WINDOW = ("2026-10-23T00:00:00Z", "2027-01-21T23:59:59Z")


def freeze(snapshot: Path) -> int:
    con = sqlite3.connect(snapshot)
    tag = dict(con.execute("SELECT key, value FROM meta").fetchall()) if con.execute(
        "SELECT name FROM sqlite_master WHERE name = 'meta'").fetchone() else {}
    rows = con.execute("""SELECT r.name, i.number, i.rank_score, i.p_merge, i.available, i.created_at
                          FROM issues i JOIN repos r USING (repo_id) WHERE i.beginner = 1 ORDER BY r.name, i.number""").fetchall()
    items = [{"repo": n, "issue": k, "rank_score": s, "p_merge": p, "available": bool(a), "created": c} for n, k, s, p, a, c in rows]
    data = gzip.compress(json.dumps(items, separators=(",", ":")).encode(), mtime=0)
    FROZEN.write_bytes(data)
    manifest = {"frozen_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "items": len(items),
                "repos": len({i["repo"] for i in items}), "snapshot": {k: tag.get(k) for k in ("built_at", "tag") if k in tag},
                "sha256": hashlib.sha256(data).hexdigest(),
                "preregistration_sha256": hashlib.sha256((HERE / "preregistration.md").read_bytes()).hexdigest()}
    MANIFEST.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=1))
    return 0


def attempts(items: list[dict], prs: list[dict], start: str, end: str) -> list[dict]:
    """Each frozen issue with its first outsider pull request naming it, opened in [start, end], and whether it merged
    within 30 days (preregistration.md, Outcome)."""
    mergers = {(p["repo"], p["merged_by"]) for p in prs if p.get("merged_by")}
    by_issue = {}
    for p in sorted(prs, key=lambda p: p["created"]):
        insider = p.get("association") in ("OWNER", "MEMBER", "COLLABORATOR") or (p["repo"], p["author"]) in mergers
        if not (start <= p["created"] <= end) or insider:
            continue
        for n in p.get("closes") or []:
            by_issue.setdefault((p["repo"], n), p)
    out = []
    for it in items:
        p = by_issue.get((it["repo"], it["issue"]))
        if p:
            merged = bool(p.get("merged")) and _days(p["created"], p["merged"]) <= 30
            out.append({**it, "merged": merged})
    return out


def _days(a: str, b: str) -> float:
    return (datetime.fromisoformat(b.replace("Z", "+00:00")) - datetime.fromisoformat(a.replace("Z", "+00:00"))).total_seconds() / 86400


def compare(items: list[dict], tried: list[dict], seed: int = 23, draws: int = 2000) -> dict:
    """The pre-registered comparisons: top third against all attempted, free against taken, and calibration."""
    import random
    cut = sorted((i["rank_score"] or 0 for i in items), reverse=True)[max(len(items) // 3 - 1, 0)] if items else 0
    top = lambda x: (x["rank_score"] or 0) >= cut  # noqa: E731
    share = lambda xs: sum(x["merged"] for x in xs) / len(xs) if xs else None  # noqa: E731
    by_repo = {}
    for x in tried:
        by_repo.setdefault(x["repo"], []).append(x)
    rng, diffs = random.Random(seed), []
    repos = sorted(by_repo)
    for _ in range(draws):
        sample = [x for r in (rng.choice(repos) for _ in repos) for x in by_repo[r]]
        a, b = share([x for x in sample if top(x)]), share(sample)
        if a is not None and b is not None:
            diffs.append(a - b)
    diffs.sort()
    tops = [x for x in tried if top(x)]
    bands = sorted(tried, key=lambda x: x["p_merge"] or 0)
    k = max(len(bands) // 5, 1)
    return {"attempted": len(tried), "repos": len(by_repo), "top_third_attempted": len(tops),
            "too_few": len(tops) < 100,
            "primary": {"top_third": share(tops), "all": share(tried),
                        "difference": (share(tops) - share(tried)) if tops and tried else None,
                        "range": [diffs[int(0.025 * len(diffs))], diffs[int(0.975 * len(diffs)) - 1]] if len(diffs) > 40 else None},
            "free": {"free": share([x for x in tried if x["available"]]), "taken": share([x for x in tried if not x["available"]])},
            "calibration": [{"predicted": sum((x["p_merge"] or 0) for x in band) / len(band), "observed": share(band), "n": len(band)}
                            for band in (bands[i * k:(i + 1) * k] if i < 4 else bands[4 * k:] for i in range(5)) if band]}


def _crawl_prs(crawl: Path) -> list[dict]:
    import duckdb
    rows = duckdb.connect().execute(f"""
        SELECT m.name, p.number, strftime(p.created_at AT TIME ZONE 'UTC', '%Y-%m-%dT%H:%M:%SZ'),
               strftime(p.merged_at AT TIME ZONE 'UTC', '%Y-%m-%dT%H:%M:%SZ'), lower(p.author_login),
               p.author_association, lower(p.merged_by), p.closing_issue_numbers
        FROM read_parquet('{(crawl / 'prs').as_posix()}/*.parquet', union_by_name = true) p
        JOIN (SELECT DISTINCT repo_id, name FROM read_parquet('{(crawl / 'repo_meta').as_posix()}/*.parquet',
                                                               union_by_name = true)) m USING (repo_id)
        QUALIFY row_number() OVER (PARTITION BY p.repo_id, p.number ORDER BY p.fetched_at DESC) = 1""").fetchall()
    return [{"repo": n, "number": k, "created": c, "merged": mg, "author": a, "association": s, "merged_by": by,
             "closes": list(cl or [])} for n, k, c, mg, a, s, by, cl in rows]


def score(crawl: Path) -> int:
    if date.today() < NOT_BEFORE:
        print(f"Too early: the pre-registered read is on or after {NOT_BEFORE}.", file=sys.stderr)
        return 2
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if hashlib.sha256(FROZEN.read_bytes()).hexdigest() != manifest["sha256"]:
        print("The frozen ranking changed since it was frozen; refusing to score.", file=sys.stderr)
        return 3
    items = json.loads(gzip.decompress(FROZEN.read_bytes()))
    prs = _crawl_prs(crawl)
    held = {p["repo"] for p in prs}
    tried = attempts([i for i in items if i["repo"] in held], prs, WINDOW[0], WINDOW[1])
    out = {"preregistration_sha256": hashlib.sha256((HERE / "preregistration.md").read_bytes()).hexdigest(),
           "frozen_sha256": manifest["sha256"], "repos_not_held": len({i["repo"] for i in items} - held),
           **compare(items, tried)}
    (HERE / "prospective-results.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=("freeze", "score"))
    ap.add_argument("--snapshot", type=Path)
    ap.add_argument("--crawl", type=Path)
    args = ap.parse_args(argv)
    return freeze(args.snapshot) if args.cmd == "freeze" else score(args.crawl)


if __name__ == "__main__":
    sys.exit(main())
