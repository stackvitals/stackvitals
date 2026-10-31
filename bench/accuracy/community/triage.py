"""Does knowing who triages find more of the project's answers? On GitHub only people with triage rights (or more) can
label, close, assign or mark as duplicate someone else's issue, so whoever did any of those in a repo acts for it,
whatever role GitHub shows on their comments. This script reads those actions for the labelled repos and scores the
regular-responder rule with and without them on the same labelled comments (the main set chose rules, the validation
set is held out).

    GH_TOKEN=... python bench/accuracy/community/triage.py fetch --crawl <crawl folder> --home <work folder>
    python bench/accuracy/community/triage.py score --crawl <crawl folder> --home <work folder>
"""
import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import httpx

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from responses import load  # noqa: E402
from score_labels import _bot, _rule  # noqa: E402

READ = datetime(2026, 10, 18)  # the crawl the labelled comments came from was read 2026-10-16 to 18
WINDOW = 360
QUERY = """query($owner: String!, $name: String!, $cursor: String, $since: DateTime!) { repository(owner: $owner, name: $name) {
  issues(first: 50, after: $cursor, orderBy: {field: UPDATED_AT, direction: DESC}, filterBy: {since: $since}) {
    pageInfo { hasNextPage endCursor }
    nodes { author { login } timelineItems(first: 5, itemTypes: [LABELED_EVENT, CLOSED_EVENT, ASSIGNED_EVENT,
                                                                   MARKED_AS_DUPLICATE_EVENT]) {
      nodes { __typename ... on LabeledEvent { createdAt actor { __typename login } }
              ... on ClosedEvent { createdAt actor { __typename login } }
              ... on AssignedEvent { createdAt actor { __typename login } }
              ... on MarkedAsDuplicateEvent { createdAt actor { __typename login } } } } } } } }"""


def _repos(crawl: Path) -> dict[int, str]:
    ids = {int(r["repo_id"]) for name in ("main", "validation")
           for r in csv.DictReader((HERE / f"labels-{name}.csv").open(encoding="utf-8"))}
    rows = duckdb.connect().execute(f"""SELECT DISTINCT repo_id, name FROM read_parquet(
        '{(crawl / 'repo_meta' / '*.parquet').as_posix()}', union_by_name = true)""").fetchall()
    return {r: n for r, n in rows if r in ids}


def fetch(crawl: Path, home: Path, pages: int = 4) -> int:
    home.mkdir(parents=True, exist_ok=True)
    out_path = home / "triage-actors.json"
    done = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    since = (READ - timedelta(days=WINDOW)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with httpx.Client(headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}"}, timeout=60) as client:
        for k, (repo_id, name) in enumerate(sorted(_repos(crawl).items()), 1):
            if str(repo_id) in done:
                continue
            owner, repo = name.split("/", 1)
            actors, cursor = {}, None
            for _ in range(pages):
                resp = client.post("https://api.github.com/graphql", json={"query": QUERY, "variables": {
                    "owner": owner, "name": repo, "cursor": cursor, "since": since}})
                time.sleep(2.5)  # under 1,500 requests an hour, shared with the crawler's token
                issues = ((resp.json().get("data") or {}).get("repository") or {}).get("issues")
                if not issues:
                    break
                for node in issues["nodes"] or []:
                    author = ((node or {}).get("author") or {}).get("login", "").lower()
                    for e in ((node.get("timelineItems") or {}).get("nodes") or []):
                        who = (e or {}).get("actor") or {}
                        login = (who.get("login") or "").lower()
                        when = (e or {}).get("createdAt") or ""
                        # Only acts on someone else's issue, by a person, before the crawl was read.
                        if login and login != author and who.get("__typename") != "Bot" and when < READ.strftime("%Y-%m-%d"):
                            actors.setdefault(login, []).append(e["__typename"])
                if not issues["pageInfo"]["hasNextPage"]:
                    break
                cursor = issues["pageInfo"]["endCursor"]
            done[str(repo_id)] = {"name": name, "actors": {a: sorted(set(v)) for a, v in actors.items()}}
            out_path.write_text(json.dumps(done, indent=1, sort_keys=True), encoding="utf-8")
            if k % 20 == 0:
                print(f"{k} repos", flush=True)
    print(f"{len(done)} repos read")
    return 0


def _flags(rows: list[dict], crawl: Path, triagers: dict[int, set[str]], use_regulars: bool, use_triage: bool) -> list[bool]:
    """Whether each item's first non-author comment came from someone the rule counts."""
    issues, comments, _mergers, regulars = load(crawl)
    authors = {(r, n): (a, c) for r, n, a, _as, c, _cl, _f, _t in issues}
    flags = []
    for row in rows:
        repo, number = int(row["repo_id"]), int(row["issue"])
        author, created = authors[(repo, number)]
        first = next((c for c in sorted((c for c in comments[(repo, number)] if c["at"] and c["at"] >= created),
                                        key=lambda c: c["at"]) if c["login"] != author and not _bot(c)), None)
        who = first["login"] if first else None
        flags.append(bool(who) and ((use_regulars and who in regulars.get(repo, set()))
                                    or (use_triage and who in triagers.get(repo, set()))))
    return flags


def score(crawl: Path, home: Path) -> int:
    got = json.loads((home / "triage-actors.json").read_text(encoding="utf-8"))
    triagers = {int(k): set(v["actors"]) for k, v in got.items()}
    out = {"repos_read": len(got), "repos_with_triagers": sum(1 for v in triagers.values() if v)}
    for name in ("main", "validation"):
        rows = list(csv.DictReader((HERE / f"labels-{name}.csv").open(encoding="utf-8")))
        results = HERE / f"responses-{name}-results.json"
        pool = json.loads(results.read_text(encoding="utf-8")).get("pool") if results.exists() else None
        weights = None
        if pool and all(r["stratum"] for r in rows):
            drawn = {s: sum(1 for r in rows if r["stratum"] == s) for s in {r["stratum"] for r in rows}}
            weights = {s: pool[s] / drawn[s] for s in drawn}
        flags = {rule: _flags(rows, crawl, triagers, reg, tri)
                 for rule, reg, tri in (("regulars", True, False), ("triage", False, True), ("both", True, True))}
        out[name] = {rule: _rule(rows, f, weights) for rule, f in flags.items()}
        # The same on each labeller's own labels (the card shows both, not only the adjudicated ones).
        for who in ("claude_kind", "gemini_kind"):
            mine = [{**r, "kind": r[who] or r["kind"]} for r in rows]
            out[name][f"by_{who.split('_')[0]}"] = {rule: _rule(mine, flags[rule], weights) for rule in ("regulars", "both")}
        added = [r for r, a, b in zip(rows, flags["regulars"], flags["both"]) if b and not a]
        out[name]["added"] = {"items": len(added), "kinds": {k: sum(r["kind"] == k for r in added)
                                                            for k in ("project_answer", "peer_help", "drive_by", "unclear")}}
    (HERE / "triage-results.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    for name in ("main", "validation"):
        for rule in ("regulars", "triage", "both"):
            r = out[name][rule]
            print(name, rule, r["counted"], r["project_answers_caught"], r["drive_by_among_counted"])
        for who in ("by_claude", "by_gemini"):
            print(name, who, {k: v["project_answers_caught"]["share"] for k, v in out[name][who].items()},
                  {k: v["drive_by_among_counted"]["share"] for k, v in out[name][who].items()})
        print(name, "added", out[name]["added"])
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=("fetch", "score"))
    ap.add_argument("--crawl", type=Path, required=True)
    ap.add_argument("--home", type=Path, required=True)
    args = ap.parse_args(argv)
    return fetch(args.crawl, args.home) if args.cmd == "fetch" else score(args.crawl, args.home)


if __name__ == "__main__":
    sys.exit(main())
