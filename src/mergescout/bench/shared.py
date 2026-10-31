"""Peer groups from opt-in shared figures: issues labelled "benchmark" on this repo, each carrying one repo's rounded CI
figures (filed from a CI run summary through the "benchmark" issue form); closing an issue withdraws it. Groups are published only with 10+ repos.

    GH_TOKEN=... python -m mergescout.bench.shared --repo owner/name --out out/shared-benchmarks.json
"""
import argparse
import json
import os
import re
import statistics
import sys
from datetime import datetime, timezone

import httpx

MIN_GROUP = 10
RANKS = (0.10, 0.25, 0.50, 0.75, 0.90)
BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.S)
SHARES = ("first_try_share", "fail_share", "rerun_share")
NUMBERS = ("pushes", "median_s", "p90_s")
KEYS = {"schema", "kind", "id", "month", "language", "tier", "pushes", "median_s", "p90_s", *SHARES}


def read_issue(issue: dict) -> dict | None:
    """The figures in one issue's body, or None when they're missing or don't look like ours."""
    found = BLOCK.search(issue.get("body") or "")
    try:
        doc = json.loads(found[1]) if found else None
    except ValueError:
        return None
    if not isinstance(doc, dict) or not KEYS <= set(doc) or set(doc) - KEYS - {"repo"}:
        return None
    ok = (doc["schema"] == 1 and doc["kind"] == "ci-benchmark" and re.fullmatch(r"[0-9a-f]{16}", str(doc["id"]))
          and re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", str(doc["month"])) and isinstance(doc["language"], str) and len(doc["language"]) < 40
          and doc["tier"] in ("100-1k", "1k-10k", "10k+")
          and all(isinstance(doc[k], (int, float)) and not isinstance(doc[k], bool) and 0 <= doc[k] <= 1 for k in SHARES)
          and all(isinstance(doc[k], int) and not isinstance(doc[k], bool) and 0 <= doc[k] < 10**7 for k in NUMBERS) and doc["pushes"] > 0)
    return doc if ok else None


def _q(values: list[float]) -> dict:
    s = sorted(values)
    cuts = statistics.quantiles(s, n=100, method="inclusive") if len(s) > 1 else s * 99
    return {f"p{int(r * 100)}": round(cuts[int(r * 100) - 1], 4) for r in RANKS}


def build(docs: list[dict], now: datetime | None = None) -> dict:
    latest = {}
    for d in docs:
        if d and (d["id"] not in latest or d["month"] > latest[d["id"]]["month"]):
            latest[d["id"]] = d
    groups = {}
    for d in latest.values():
        for key in (f"{d['language']}|{d['tier']}", f"{d['language']}|all", f"all|{d['tier']}", "all|all"):
            groups.setdefault(key, []).append(d)
    now = now or datetime.now(timezone.utc)
    return {"built_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "private": True, "repos": len(latest),
            "about": "Repos that chose to share rounded CI figures (public and private), latest month each.",
            "groups": {k: {"repos": len(g), "median_s": _q([d["median_s"] for d in g]),
                           "first_try_share": _q([d["first_try_share"] for d in g]),
                           "fail_share": _q([d["fail_share"] for d in g])}
                       for k, g in sorted(groups.items()) if len(g) >= MIN_GROUP}}


def one_per_account(issues: list[dict], now: datetime | None = None) -> list[dict]:
    """Each GitHub account's newest valid figures only: filed figures can't be verified, so one account can't fill a group.
    An id belongs to the first account that filed it, so nobody can replace another repo's figures; future months are dropped."""
    month = f"{now or datetime.now(timezone.utc):%Y-%m}"
    mine, owner = {}, {}
    for i in sorted(issues, key=lambda i: i.get("created_at") or ""):
        doc, who = read_issue(i), ((i.get("user") or {}).get("login") or "").lower()
        if not doc or not who or doc["month"] > month or owner.setdefault(doc["id"], who) != who:
            continue
        mine[who] = doc
    return list(mine.values())


def fetch(repo: str, token: str, client: httpx.Client | None = None) -> list[dict]:
    client = client or httpx.Client(timeout=60)
    out = []
    for page in range(1, 51):
        got = client.get(f"https://api.github.com/repos/{repo}/issues", headers={"Authorization": f"Bearer {token}"},
                         params={"labels": "benchmark", "state": "open", "per_page": 100, "page": page})
        got.raise_for_status()
        got = got.json()
        out += [i for i in got if "pull_request" not in i]
        if len(got) < 100:
            break
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", required=True, action="append", help="repeatable: every repo whose issues hold figures")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    issues = []
    for repo in args.repo:
        # A repo the token can't read yet (still private, or gone) is skipped; the others still count.
        try:
            issues += fetch(repo, os.environ["GH_TOKEN"])
        except httpx.HTTPError as exc:
            print(f"{repo}: skipped ({exc.__class__.__name__})")
    out = build(one_per_account(issues))
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    print(f"{len(issues)} issues, {out['repos']} repos, {len(out['groups'])} groups published")
    return 0


if __name__ == "__main__":
    sys.exit(main())
