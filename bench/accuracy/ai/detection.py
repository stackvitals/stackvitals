"""How often StackVitals' AI marking is right: of the PRs it marks as a coding agent's or as AI-assisted, how many say
so themselves (precision), and of the PRs that say so, how many it marks (recall). The truth is what a PR states in its
own text (author, branch, description, commits, labels), labelled blind with codebook-detection.md; AI help nobody
states can't be seen by anyone, so recall here is recall of stated AI help.

    python bench/accuracy/ai/detection.py sample --crawl <crawl folder: prs/, repo_meta/> --home <work folder>
    GH_TOKEN=... python bench/accuracy/ai/detection.py fetch --home <work folder>
    python bench/accuracy/ai/detection.py score --home <work folder> --final <adjudicated labels.jsonl>

sample draws non-bot PRs created since March 2026 in four strata (an agent's branch, an agent's account, an AI trailer in
the description, and none of these), one per repo per stratum, and counts each stratum's population so recall can be
weighted back; fetch reads each PR's author, branch, description, labels and commits (one GraphQL call each) into a
blind view (view.jsonl) and keeps what the product's rule needs apart (rule.jsonl); score writes detection-results.json.
"""
import argparse
import json
import os
import random
import re
import sys
import time
from pathlib import Path

import duckdb
import httpx

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[2] / "src"))
from fair import by_repo  # noqa: E402

from mergescout.signals.rules import AI_AGENT_BOT_NAMES, AI_AGENT_LOGINS  # noqa: E402
from stackvitals.core import ai_outcomes  # noqa: E402
from stackvitals.core.actors import kind_of  # noqa: E402
from stackvitals.core.stats import wilson  # noqa: E402
from stackvitals.flow.collect import ai_tools, body_tools  # noqa: E402

SEED, SINCE = 23, "2026-03-01"
STRATA = {"branch": 60, "account": 30, "trailer": 60, "none": 250}
AGENT_BRANCH = r"^(copilot|codex|cursor|devin|claude)[/-]"
QUERY = """query($owner: String!, $name: String!, $n: Int!) { repository(owner: $owner, name: $name) {
  pullRequest(number: $n) { url title body headRefName state author { __typename login }
    labels(first: 20) { nodes { name } }
    commits(first: 100) { totalCount nodes { commit { message } } }
    recent: commits(last: 5) { nodes { commit { message } } } } } }"""


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.exists() else []


def _stratum(row: dict) -> str | None:
    login, typ = row["author"] or "", row["author_type"]
    base = login.lower().removesuffix("[bot]")
    if base in AI_AGENT_LOGINS or base in AI_AGENT_BOT_NAMES:
        return "account"
    if kind_of(login, typ) == "bot":
        return None
    if re.match(AGENT_BRANCH, row["head"] or "", re.I):
        return "branch"
    return "trailer" if row["tag"] in ("claude", "codex", "copilot", "cursor", "devin") else "none"


def sample(crawl: Path, home: Path) -> int:
    rows = duckdb.connect().execute(f"""
        SELECT m.name, p.number, p.author_login, p.author_type, p.head_ref, p.ai_tag
        FROM read_parquet('{crawl.as_posix()}/prs/*.parquet', union_by_name = true) p
        JOIN (SELECT DISTINCT repo_id, name FROM read_parquet('{crawl.as_posix()}/repo_meta/*.parquet', union_by_name = true)) m
          USING (repo_id)
        WHERE p.created_at >= TIMESTAMP '{SINCE}'
        QUALIFY row_number() OVER (PARTITION BY p.repo_id, p.number ORDER BY p.fetched_at DESC) = 1
        ORDER BY m.name, p.number""").fetchall()
    pools = {s: [] for s in STRATA}
    for name, number, author, typ, head, tag in rows:
        s = _stratum({"author": author, "author_type": typ, "head": head, "tag": tag})
        if s:
            pools[s].append({"repo": name, "number": number})
    rng, picked = random.Random(SEED), []
    for s, want in STRATA.items():
        pool = pools[s]
        rng.shuffle(pool)
        seen = set()
        for it in pool:
            if it["repo"] not in seen and len(seen) < want:
                seen.add(it["repo"])
                picked.append({**it, "stratum": s})
    home.mkdir(parents=True, exist_ok=True)
    (home / "items.jsonl").write_text("".join(json.dumps(p) + "\n" for p in picked), encoding="utf-8")
    sizes = {s: len(v) for s, v in pools.items()}
    (home / "population.json").write_text(json.dumps(sizes, indent=1) + "\n", encoding="utf-8")
    print(f"{len(picked)} PRs; population by stratum {sizes}")
    return 0


def fetch(home: Path) -> int:
    items = _jsonl(home / "items.jsonl")
    headers = {"Authorization": f"Bearer {os.environ['GH_TOKEN']}"}
    view, rule = [], []
    with httpx.Client(headers=headers, timeout=30) as client:
        for k, it in enumerate(items, 1):
            owner, name = it["repo"].split("/", 1)
            pr = None
            for _ in range(3):
                try:
                    resp = client.post("https://api.github.com/graphql",
                                       json={"query": QUERY, "variables": {"owner": owner, "name": name, "n": it["number"]}})
                    pr = ((resp.json().get("data") or {}).get("repository") or {}).get("pullRequest")
                    break
                except (httpx.TransportError, ValueError):
                    time.sleep(5)
            time.sleep(2.5)  # under 1,500 requests an hour, shared with the crawler's token
            if not pr:
                continue
            author = pr.get("author") or {}
            commits = [(c.get("commit") or {}).get("message") or "" for c in (pr["commits"].get("nodes") or [])]
            recent = [(c.get("commit") or {}).get("message") or "" for c in (pr["recent"].get("nodes") or [])]
            labels = [x["name"] for x in pr["labels"]["nodes"] or [] if x]
            view.append({"id": k, "repo": it["repo"], "url": pr["url"], "author": author.get("login"),
                         "author_type": author.get("__typename"), "branch": pr["headRefName"], "title": pr["title"],
                         "description": (pr.get("body") or "")[:6000], "labels": labels,
                         "commits": [m[:600] for m in commits], "commit_count": pr["commits"]["totalCount"]})
            rule.append({"id": k, "repo": it["repo"], "stratum": it["stratum"], "au": author.get("login"),
                         "at": author.get("__typename"), "head": pr["headRefName"], "ai": ai_tools(recent), "lb": labels,
                         "body": pr.get("body") or "", "all_ai": ai_tools(commits)})
            if k % 25 == 0:
                print(f"{k} of {len(items)}", flush=True)
    rng = random.Random(SEED)
    rng.shuffle(view)  # labellers see no stratum order
    (home / "view.jsonl").write_text("".join(json.dumps(v) + "\n" for v in view), encoding="utf-8")
    (home / "rule.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rule), encoding="utf-8")
    print(f"{len(view)} PRs read")
    return 0


def verdict(r: dict, body: bool = True) -> str:
    """The product's marking of one fetched PR: agent, assisted or person (body=False: the rule before)."""
    p = {k: r[k] for k in ("au", "at", "head", "ai", "lb")}
    if body:
        p["ai"] = sorted(set(p["ai"]) | set(body_tools(r["body"])))
    else:
        # The rule before Phase 16: labels matched exactly, no description.
        p["lb"] = [x for x in p["lb"] if x.lower() in ai_outcomes.AI_LABELS]
    return ai_outcomes.mode(p)


def _share(k: int, n: int) -> dict:
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "share": round(k / n, 4) if n else None, "low": round(lo, 4), "high": round(hi, 4)}


def score(home: Path, final: Path) -> int:
    rules = {r["id"]: r for r in _jsonl(home / "rule.jsonl")}
    labels = {r["id"]: r for r in _jsonl(final)}
    pop = json.loads((home / "population.json").read_text(encoding="utf-8"))
    drawn = {s: sum(1 for r in rules.values() if r["stratum"] == s) for s in STRATA}
    out = {"labelled": len(labels), "population": pop}
    rows = [{"id": i, "repo": rules[i]["repo"], "stratum": rules[i]["stratum"], "truth": lab["involvement"],
             "fetched": rules[i]} for i, lab in sorted(labels.items()) if i in rules and lab.get("involvement") != "unclear"]
    out["decided"], out["unclear"] = len(rows), len(labels) - len(rows)
    for name, body in (("rule_before", False), ("rule", True)):
        for r in rows:
            r[name] = verdict(r["fetched"], body)
        res = {}
        for half in ("tune", "held_out", "all"):
            mine = [r for r in rows if half == "all" or (r["id"] % 2 == 1) == (half == "tune")]
            ai = lambda v: v in ("agent", "assisted")  # noqa: E731
            marked = [r for r in mine if ai(r[name])]
            prec = _share(sum(ai(r["truth"]) for r in marked), len(marked))
            prec["by_repo"] = by_repo([(r["repo"], ai(r["truth"])) for r in marked])
            # Recall weighted back to the population: each stratum's PRs count for its share of all PRs.
            w = {s: pop[s] / max(drawn[s], 1) for s in STRATA}
            stated = [r for r in mine if ai(r["truth"])]
            found = sum(w[r["stratum"]] for r in stated if ai(r[name]))
            total = sum(w[r["stratum"]] for r in stated)
            kind = [r for r in marked if ai(r["truth"])]
            res[half] = {"precision": prec, "recall_raw": _share(sum(ai(r[name]) for r in stated), len(stated)),
                         "recall_weighted": round(found / total, 4) if total else None,
                         "kind_agrees": _share(sum(r[name] == r["truth"] for r in kind), len(kind)),
                         "missed": sorted(r["id"] for r in stated if not ai(r[name])),
                         "false_marks": sorted(r["id"] for r in marked if not ai(r["truth"]))}
        out[name] = res
    # Where the misses' evidence sat, read from the fetched PR (not the labels).
    missed = [r for r in rows if r["truth"] in ("agent", "assisted") and r["rule_before"] == "person"]
    out["missed_evidence"] = {
        "description_marker": sum(bool(body_tools(r["fetched"]["body"])) for r in missed),
        "older_commit_trailer": sum(bool(r["fetched"]["all_ai"]) and not r["fetched"]["ai"] for r in missed),
        "n": len(missed)}
    by_stratum = {}
    for s in STRATA:
        mine = [r for r in rows if r["stratum"] == s]
        by_stratum[s] = {"n": len(mine), "agent": sum(r["truth"] == "agent" for r in mine),
                         "assisted": sum(r["truth"] == "assisted" for r in mine), "none": sum(r["truth"] == "none" for r in mine)}
    out["truth_by_stratum"] = by_stratum
    (HERE / "detection-results.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    with (HERE / "detection-labels.csv").open("w", encoding="utf-8", newline="") as f:
        f.write("id,repo,stratum,truth,rule_before,rule\n")
        for r in rows:
            f.write(f"{r['id']},{r['repo']},{r['stratum']},{r['truth']},{r['rule_before']},{r['rule']}\n")
    print(json.dumps({k: v for k, v in out.items() if k in ("rule_before", "rule", "missed_evidence")}, indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=("sample", "fetch", "score"))
    ap.add_argument("--home", type=Path, required=True)
    ap.add_argument("--crawl", type=Path)
    ap.add_argument("--final", type=Path)
    args = ap.parse_args(argv)
    if args.cmd == "sample":
        return sample(args.crawl, args.home)
    return fetch(args.home) if args.cmd == "fetch" else score(args.home, args.final)


if __name__ == "__main__":
    sys.exit(main())
