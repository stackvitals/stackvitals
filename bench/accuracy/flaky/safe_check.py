"""Does "same error as its past flakes" separate safe re-runs from failures the change caused? For every held-out "safe to
re-run" call (heldout.py), the job's two newest flakes before it are found with the history up to that failure, their
failing steps' logs are read (cached), and this failure's error lines are compared with theirs (`feedback.same_error`).

    GH_TOKEN=... python bench/accuracy/flaky/safe_check.py --home <wide work folder> --final <final/heldout.jsonl>

Writes safe-check-results.json beside this script (counts only).
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

from stackvitals.ci.analyze import analyze
from stackvitals.ci.feedback import failing_section, same_error
from stackvitals.ci.store import DataStore
from stackvitals.core.stats import wilson

API = "https://api.github.com"


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _share(labels: list[str]) -> dict:
    yes, no = labels.count("yes"), labels.count("no")
    lo, hi = wilson(yes, yes + no)
    return {"n": len(labels), "caused": yes, "not_caused": no, "unclear": len(labels) - yes - no,
            "caused_low": round(lo, 4), "caused_high": round(hi, 4)}


def past_flakes(data: dict, run_id: int, att: int, workflow: str, job: str, branch: str | None) -> list[int]:
    """Job ids of the job's two newest flake events before this run, from the history up to it."""
    runs = {(r["id"], r["att"]): r for r in data["runs"]}
    now = datetime.fromisoformat(runs[(run_id, att)]["cr"].replace("Z", "+00:00"))
    earlier = {k for k, r in runs.items() if datetime.fromisoformat(r["cr"].replace("Z", "+00:00")) < now}
    before = {"runs": [runs[k] for k in earlier], "jobs": [j for j in data["jobs"] if (j["run"], j["att"]) in earlier]}
    entry = next((j for j in analyze(before, now, window_days=30, default_branch=branch)["jobs"]
                  if j["workflow"] == workflow and j["job"] == job), None)
    return [e["job"] for e in (entry or {}).get("evidence") or [] if e.get("job")][-2:]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--home", type=Path, required=True)
    ap.add_argument("--final", type=Path, required=True)
    args = ap.parse_args(argv)
    rows = _jsonl(args.home / "labelled-items.jsonl")
    labels = {r["id"]: r for r in _jsonl(args.final)}
    cache_path = args.home / "flake-logs.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    client = httpx.Client(timeout=60, follow_redirects=True, headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}"})
    same, different, nolog = [], [], []
    for n, r in enumerate(rows, 1):
        if r["group"] != "safe" or n not in labels:
            continue
        store = DataStore(args.home / "ci" / r["repo"].replace("/", "__"))
        past = past_flakes(store.load(), r["run"], r["att"], r["workflow"], r["job"], store.state().get("default_branch"))
        logs = []
        for jid in past:
            key = f"{r['repo']}#{jid}"
            if key not in cache:
                resp = None
                for wait in (0, 10, 30, 90):
                    time.sleep(wait)
                    try:
                        resp = client.get(f"{API}/repos/{r['repo']}/actions/jobs/{jid}/logs")
                        break
                    except httpx.TransportError:
                        continue  # a dropped connection: the cache keeps what finished
                if resp is None:
                    print("network down; run again to resume", file=sys.stderr)
                    return 1
                cache[key] = failing_section(resp.text) if resp.status_code == 200 else None
                cache_path.write_text(json.dumps(cache), encoding="utf-8")
            if cache[key]:
                logs.append(cache[key])
        mine = failing_section(r.get("log"))
        group = nolog if not logs or "(log unavailable" in (r.get("log") or "")[:40] else \
            same if any(same_error(mine, other) for other in logs) else different
        group.append(labels[n]["caused_by_change"])
    out = {"same_error_as_past_flakes": _share(same), "different_error": _share(different), "no_log_to_compare": _share(nolog)}
    (Path(__file__).with_name("safe-check-results.json")).write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
