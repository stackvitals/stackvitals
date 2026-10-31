"""Which release an incident blames: DORA tools (DevLake, and StackVitals by default) link a failure to the last
deployment before it was reported. Regression reports in public repos often say which release broke things, so they
can check that rule. For libraries a release is the deployment.

    python bench/accuracy/dora/incidents.py sample --crawl <crawl folder: issues/, repo_meta/> --home <work folder>
    GH_TOKEN=... python bench/accuracy/dora/incidents.py fetch --home <work folder>
    python bench/accuracy/dora/incidents.py score --home <work folder> --final <adjudicated labels.jsonl>

sample draws regression and incident issues that name a version (seeded, at most 2 a repo); fetch reads each issue in
full and the repo's releases, and writes a blind view for labellers (view.jsonl: the issue and the releases, no rule
output); score writes incidents-results.json and incidents-labels.csv (links and labels) beside this script.
"""
import argparse
import csv
import json
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import duckdb
import httpx

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[2] / "src"))
from fair import by_repo, mcnemar  # noqa: E402

from stackvitals.core.delivery import PRE_TAG  # noqa: E402
from stackvitals.core.stats import wilson  # noqa: E402

LABEL = r"regress|incident|outage"
VERSION = re.compile(r"(?<![\w.])v?(\d+\.\d+(?:\.\d+)?(?:[-.+][\w.]+)?)(?![\w])")
PER_REPO, SEED = 2, 16


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.exists() else []


def sample(crawl: Path, home: Path, n: int) -> int:
    con = duckdb.connect()
    rows = con.execute(f"""
        SELECT m.name, i.number, i.created_at FROM read_parquet('{crawl.as_posix()}/issues/*.parquet') i
        JOIN read_parquet('{crawl.as_posix()}/repo_meta/*.parquet') m USING (repo_id)
        WHERE len(list_filter(i.labels, lambda x: regexp_matches(lower(x), '{LABEL}'))) > 0
          AND regexp_matches(coalesce(i.body_excerpt, ''), '\\d+\\.\\d+')
        ORDER BY m.name, i.number""").fetchall()
    seen = {}
    for name, number, created in rows:
        seen[(name, number)] = created.isoformat()
    keys = sorted(seen)
    random.Random(SEED).shuffle(keys)
    picked, per = [], {}
    for name, number in keys:
        if per.get(name, 0) < PER_REPO and len(picked) < n:
            picked.append({"repo": name, "issue": number})
            per[name] = per.get(name, 0) + 1
    home.mkdir(parents=True, exist_ok=True)
    (home / "items.jsonl").write_text("".join(json.dumps(p) + "\n" for p in picked), encoding="utf-8")
    print(f"{len(picked)} issues in {len(per)} repos (of {len(keys)} candidates)")
    return 0


def _get(client: httpx.Client, path: str, **params):
    for _ in range(3):
        try:
            resp = client.get(f"https://api.github.com/{path}", params=params)
            time.sleep(1.2)  # about 1,000 requests an hour at most, shared with the crawler's token
            return resp.json() if resp.status_code == 200 else None
        except httpx.TransportError:
            time.sleep(5)
    return None


def fetch(home: Path) -> int:
    items = _jsonl(home / "items.jsonl")
    headers = {"Authorization": f"Bearer {os.environ['GH_TOKEN']}", "Accept": "application/vnd.github+json"}
    out, releases = [], {}
    with httpx.Client(headers=headers, timeout=30) as client:
        for k, it in enumerate(items, 1):
            issue = _get(client, f"repos/{it['repo']}/issues/{it['issue']}")
            if not issue:
                continue
            if it["repo"] not in releases:
                got = []
                for page in (1, 2):
                    batch = _get(client, f"repos/{it['repo']}/releases", per_page=100, page=page) or []
                    got += [{"tag": r["tag_name"], "at": r.get("published_at") or r.get("created_at"),
                             "pre": bool(r.get("prerelease"))} for r in batch if not r.get("draft")]
                    if len(batch) < 100:
                        break
                releases[it["repo"]] = sorted((r for r in got if r["at"]), key=lambda r: r["at"])
            rel = releases[it["repo"]]
            opened = issue["created_at"]
            before = [r for r in rel if r["at"] <= opened]
            after = [r for r in rel if r["at"] > opened]
            out.append({"id": k, "repo": it["repo"], "issue": it["issue"], "url": issue["html_url"], "opened": opened,
                        "title": issue["title"], "body": (issue.get("body") or "")[:4000],
                        "labels": [x["name"] for x in issue.get("labels") or []],
                        "releases_before": before[-30:], "releases_after": after[:3]})
    (home / "view.jsonl").write_text("".join(json.dumps(v) + "\n" for v in out), encoding="utf-8")
    print(f"{len(out)} issues read; {sum(1 for v in out if v['releases_before'])} with releases before them")
    return 0


def last_before(v: dict) -> str | None:
    """DORA's rule: the last release (not a prerelease) published before the incident was reported."""
    rel = [r for r in v["releases_before"] if not r["pre"] and not PRE_TAG.search(r["tag"])]
    return rel[-1]["tag"] if rel else None


def _norm(tag: str) -> str:
    # Tags compare by their version: "v1.2.0", "1.2.0" and "pkg@1.2.0" are one release.
    m = VERSION.search(tag or "")
    return m[1].lower() if m else (tag or "").lower()


def named(v: dict) -> str | None:
    """The version the report names: the newest released version mentioned in the issue that was out when it was
    opened (a regression report names the release it broke in)."""
    tags = {_norm(r["tag"]): r["tag"] for r in v["releases_before"]}
    order = [_norm(r["tag"]) for r in v["releases_before"]]
    said = [m[1].lower() for m in VERSION.finditer(f"{v['title']}\n{v['body']}")]
    hits = [x for x in said if x in tags]
    return tags[max(hits, key=order.index)] if hits else None


def score(home: Path, final: Path) -> int:
    view = {v["id"]: v for v in _jsonl(home / "view.jsonl")}
    labels = {r["id"]: r for r in _jsonl(final)}
    rows = []
    for i, lab in sorted(labels.items()):
        v = view.get(i)
        if not v or lab.get("culprit") in (None, "", "unclear"):
            continue
        truth = lab["culprit"]
        rows.append({"id": i, "repo": v["repo"], "url": v["url"], "truth": truth, "last_before": last_before(v),
                     "named": named(v), "half": "tune" if i % 2 else "held_out"})

    def right(rule, pick, truth):
        return truth != "none" and pick is not None and _norm(pick) == _norm(truth) if rule != "none" else truth == "none"

    out = {"labelled": len(labels), "decided": len(rows), "none": sum(r["truth"] == "none" for r in rows),
           "repos": len({r["repo"] for r in rows})}
    for half in ("tune", "held_out", "all"):
        mine = [r for r in rows if half == "all" or r["half"] == half]
        caused = [r for r in mine if r["truth"] != "none"]
        res = {"n": len(caused)}
        for rule in ("last_before", "named"):
            k = sum(right(rule, r[rule], r["truth"]) for r in caused)
            lo, hi = wilson(k, len(caused))
            res[rule] = {"right": k, "share": round(k / len(caused), 4) if caused else None, "low": round(lo, 4),
                         "high": round(hi, 4), "picked": sum(r[rule] is not None for r in caused),
                         "by_repo": by_repo([(r["repo"], right(rule, r[rule], r["truth"])) for r in caused])}
        # The rule StackVitals would use: the named version when there is one, else the last release before.
        both = [(r["named"] or r["last_before"]) for r in caused]
        k = sum(right("x", p, r["truth"]) for p, r in zip(both, caused))
        lo, hi = wilson(k, len(caused))
        res["named_else_last"] = {"right": k, "share": round(k / len(caused), 4) if caused else None,
                                  "low": round(lo, 4), "high": round(hi, 4)}
        res["named_else_last_vs_last_before"] = mcnemar(
            sum(right("x", p, r["truth"]) and not right("x", r["last_before"], r["truth"]) for p, r in zip(both, caused)),
            sum(right("x", r["last_before"], r["truth"]) and not right("x", p, r["truth"]) for p, r in zip(both, caused)))
        out[half] = res
    (HERE / "incidents-results.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    with (HERE / "incidents-labels.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "repo", "url", "culprit", "last_before", "named", "half"])
        for r in rows:
            w.writerow([r["id"], r["repo"], r["url"], r["truth"], r["last_before"], r["named"], r["half"]])
    print(json.dumps(out, indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=("sample", "fetch", "score"))
    ap.add_argument("--home", type=Path, required=True)
    ap.add_argument("--crawl", type=Path)
    ap.add_argument("--final", type=Path)
    ap.add_argument("--n", type=int, default=60)
    args = ap.parse_args(argv)
    if args.cmd == "sample":
        return sample(args.crawl, args.home, args.n)
    return fetch(args.home) if args.cmd == "fetch" else score(args.home, args.final)


if __name__ == "__main__":
    sys.exit(main())
