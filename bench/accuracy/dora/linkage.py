"""How often DevLake's time-order rule blames a different deployment than the one that shipped the change a revert undid.

For each repo's merged pull requests and deployments (GitHub releases, deploy workflows or the Deployments API, as the
Delivery page finds them), every merged revert in the last year is linked two ways: time order (the last deployment
finished before the revert was opened, DevLake's rule) and fix chain (the deployment that shipped the PR it undoes, or
"never shipped" when the revert landed before any deployment ran the change).
Reported: how many reverts have a fix chain, how often the two disagree, how many deployments lay between, and how
often the 90-day change failure rate's tier differs between the two. With --check (GH_TOKEN set), GitHub's compare API
confirms each link: the fix-chain deployment contains the undone PR's merge commit, and for "never shipped" the last
deployment before the revert merged does not.

    python bench/accuracy/dora/linkage.py <folder of repo workspaces> [--check]
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from stackvitals.core.config import parse
from stackvitals.core.ai_outcomes import revert_target
from stackvitals.core.delivery import dora, find_incidents, shipped
from stackvitals.core.stats import wilson
from stackvitals.core.time import iso
from stackvitals.core.time import parse as when
from stackvitals.flow.store import FlowStore


def _ref(dep: dict | None) -> str | None:
    # A deployment's commit, or its release tag (several packages from one commit read "tag +N").
    if not dep:
        return None
    return dep.get("sha") or (dep.get("name") or "").split(" +")[0] or None


def run(folder: Path) -> dict:
    cfg = parse("")[0]
    totals = {"repos": 0, "reverts": 0, "fix_chain_found": 0, "disagree": 0, "never_shipped": 0, "deployments_between": [],
              "tier_changed": 0,
              "repos_with_reverts": 0, "per_repo": {}, "links": []}
    for root in sorted(p for p in folder.iterdir() if (p / "flow" / "closed").is_dir()):
        store = FlowStore(root)
        flow, repo = store.load(), store.repo()
        prs = (flow.get("closed") or []) + (flow.get("open") or [])
        try:
            deps, source, _rows = shipped(flow, repo, {"runs": [], "jobs": []}, cfg, ("person", "agent"))
        except Exception as exc:  # noqa: BLE001 - one workspace's trouble is reported, not fatal
            totals["per_repo"][root.name] = {"error": type(exc).__name__}
            continue
        if not deps:
            continue
        merged_at = [when(p["mg"]) for p in prs if p.get("mg")]
        if not merged_at:
            continue
        now = max(merged_at)
        incidents = find_incidents(prs, [], deps, cfg)
        year = iso(now - timedelta(days=365))
        reverts = [i for i in incidents if i["source"] == "revert" and i["created"] >= year]
        finished = {d["id"]: d["finished"] for d in deps}
        between = [sum(1 for d in deps if finished[i["fix_chain_deployment"]] < d["finished"] <= finished[i["deployment"]])
                   for i in reverts if i.get("fix_chain_deployment") and i.get("deployment")
                   and i["fix_chain_deployment"] != i["deployment"]]
        d = dora(deps, [], incidents, now - timedelta(days=90), now)
        tier = lambda v: None if v is None else "elite" if v <= 0.05 else "high" if v <= 0.10 else "medium" if v <= 0.15 else "low"  # noqa: E731
        changed = d["change_failure_rate"] is not None and tier(d["change_failure_rate"]) != tier(d["cfr_fix_chain"])
        totals["repos"] += 1
        totals["repos_with_reverts"] += bool(reverts)
        totals["reverts"] += len(reverts)
        totals["fix_chain_found"] += sum(1 for i in reverts if i.get("fix_chain_deployment"))
        totals["disagree"] += len(between)
        totals["never_shipped"] += sum(1 for i in reverts if i.get("never_shipped"))
        totals["deployments_between"] += between
        totals["tier_changed"] += changed
        by_number, by_id = {p["n"]: p for p in prs if p.get("mg")}, {x["id"]: x for x in deps}
        for i in reverts:
            if not (i.get("fix_chain_deployment") or i.get("never_shipped")):
                continue
            target = by_number.get(revert_target(by_number[i["number"]], by_number))
            before = [x for x in deps if x["finished"] < i["resolved"]]
            last = max(before, key=lambda x: x["finished"]) if before else None
            totals["links"].append({"repo": root.name.replace("__", "/", 1), "revert": i["number"], "undid": target and target["n"],
                                    "undid_commit": target and target.get("mc"), "never_shipped": i["never_shipped"],
                                    "fix_chain": _ref(by_id.get(i.get("fix_chain_deployment"))), "last_before_revert": _ref(last),
                                    "time_order": _ref(by_id.get(i.get("deployment")))})
        totals["per_repo"][root.name] = {"deployments_from": source, "deployments": len(deps), "reverts": len(reverts),
                                         "disagree": len(between), "cfr_time_order": d["change_failure_rate"],
                                         "cfr_fix_chain": d["cfr_fix_chain"]}
    found = totals["fix_chain_found"]
    lo, hi = wilson(totals["disagree"], found)
    b = sorted(totals["deployments_between"])
    return {**{k: v for k, v in totals.items() if k != "deployments_between"},
            "disagree_share": {"share": round(totals["disagree"] / found, 4) if found else None, "low": round(lo, 4),
                               "high": round(hi, 4)},
            "deployments_between_median": b[len(b) // 2] if b else None,
            "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def _get(client: httpx.Client, url: str) -> httpx.Response:
    # Paced, and patient with a dropped connection.
    for wait in (2, 30, 120, 600):
        time.sleep(wait)
        try:
            return client.get(url)
        except httpx.TransportError:
            continue
    raise RuntimeError(f"network down at {url}")


def _contains(client: httpx.Client, repo: str, commit: str, release: str) -> bool | None:
    # The release's commit is the commit itself or comes after it: compare says "identical" or "ahead".
    resp = _get(client, f"https://api.github.com/repos/{repo}/compare/{commit}...{release}")
    return resp.json().get("status") in ("identical", "ahead") if resp.status_code == 200 else None


def check(links: list[dict], token: str) -> dict:
    """Each link against the commit graph: right, wrong, or unknown when a commit is missing."""
    client = httpx.Client(timeout=60, headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    out = {k: {"right": 0, "wrong": 0, "unknown": 0} for k in ("fix_chain", "never_shipped", "time_order")}
    for x in links:
        kind = "never_shipped" if x["never_shipped"] else "fix_chain"
        release = x["last_before_revert"] if x["never_shipped"] else x["fix_chain"]
        if not x["undid_commit"] and x["undid"]:
            resp = _get(client, f"https://api.github.com/repos/{x['repo']}/pulls/{x['undid']}")
            x["undid_commit"] = resp.json().get("merge_commit_sha") if resp.status_code == 200 else None
        if not (x["undid_commit"] and release):
            out[kind]["unknown"] += 1
            out["time_order"]["unknown"] += 1
            x["check"] = x["time_order_check"] = "unknown"
            continue
        inside = _contains(client, x["repo"], x["undid_commit"], release)
        right = None if inside is None else (not inside if x["never_shipped"] else inside)
        x["check"] = "unknown" if right is None else "right" if right else "wrong"
        out[kind][x["check"]] += 1
        # Time order blames the last deployment before the revert opened: right only if it ran the undone change.
        blamed = x["time_order"] if x["time_order"] != release else inside
        if isinstance(blamed, str):
            blamed = _contains(client, x["repo"], x["undid_commit"], blamed)
        x["time_order_check"] = "unknown" if blamed is None else "right" if blamed else "wrong"
        out["time_order"][x["time_order_check"]] += 1
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("folder", type=Path)
    ap.add_argument("--out", type=Path, default=Path(__file__).with_name("linkage-results.json"))
    ap.add_argument("--check", action="store_true", help="confirm each link with GitHub's compare API (GH_TOKEN)")
    args = ap.parse_args(argv)
    out = run(args.folder)
    if args.check and os.environ.get("GH_TOKEN"):
        out["containment"] = check(out["links"], os.environ["GH_TOKEN"])
    args.out.write_text(json.dumps(out, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "per_repo"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
