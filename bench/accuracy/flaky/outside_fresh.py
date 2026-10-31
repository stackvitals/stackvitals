"""The outside-failure signatures on failed jobs they were never tuned on, judged without any labeller: what GitHub
recorded when the same job ran again on the same code (passed, or failed again).

From the flaky sample's 14-day CI reads (51 repos), every failed job that was neither labelled nor a gate failing only
because another job did: all with a re-run on the same code, and a seeded sample of those never re-run. Each job's
log is read once (one request) and only the failing step's part is kept, in memory.

    GH_TOKEN=... python bench/accuracy/flaky/outside_fresh.py --home <flaky work folder> [--unrun 150] [--seed 5]

Reported: matches, and among matches with a re-run, how many passed (consistent with an outside cause) or failed again
(an outage that lasted, or a real failure); and among failures a re-run passed, how many the signatures caught.
"""
import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from fair import compare_shares  # noqa: E402
from views import rerun  # noqa: E402

from stackvitals.ci.analyze import FAIL, _downstream  # noqa: E402
from stackvitals.ci.feedback import failing_section, outside_signature  # noqa: E402
from stackvitals.ci.store import DataStore  # noqa: E402
from stackvitals.core.stats import wilson  # noqa: E402

API = "https://api.github.com"
EVIDENCE = {"a re-run of the same run passed this job": "passed", "another run on the same code passed this job": "passed",
            "ran again on the same code and failed again": "failed again", "not run again": "not run"}


def candidates(home: Path) -> list[dict]:
    lab = {(json.loads(x)["repo"], json.loads(x).get("job_id")) for f in ("items.jsonl", "asof-items.jsonl")
           for x in (home / f).read_text(encoding="utf-8").splitlines() if x.strip()}
    out = []
    for d in sorted((home / "ci").iterdir()):
        data, repo = DataStore(d).load(), d.name.replace("__", "/", 1)
        for j in data["jobs"]:
            if j["c"] not in FAIL or (repo, j["id"]) in lab:
                continue
            if _downstream(j, [x for x in data["jobs"] if x["run"] == j["run"] and x["att"] == j["att"]]):
                continue
            out.append({"repo": repo, "job_id": j["id"], "job": j["n"],
                        "evidence": EVIDENCE[rerun({"run": j["run"], "att": j["att"], "job": j["n"]}, data)]})
    return out


def _share(k: int, n: int) -> dict:
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "share": round(k / n, 4) if n else None, "low": round(lo, 4), "high": round(hi, 4)}


def score(rows: list[dict]) -> dict:
    read = [r for r in rows if r.get("read")]
    matched = [r for r in read if r.get("signature")]
    known = [r for r in matched if r["evidence"] != "not run"]
    flakes = [r for r in read if r["evidence"] == "passed"]
    repeat = [r for r in read if r["evidence"] == "failed again"]
    caught_flakes, caught_repeat = sum(bool(r["signature"]) for r in flakes), sum(bool(r["signature"]) for r in repeat)
    return {"jobs_read": len(read), "matched": len(matched),
            "matched_with_rerun": {"passed": sum(r["evidence"] == "passed" for r in known),
                                   "failed_again": sum(r["evidence"] == "failed again" for r in known)},
            "passed_among_matched_with_rerun": _share(sum(r["evidence"] == "passed" for r in known), len(known)),
            "flakes_caught": _share(caught_flakes, len(flakes)),
            "repeats_caught": _share(caught_repeat, len(repeat)),
            "flakes_vs_repeats": compare_shares(caught_flakes, len(flakes), caught_repeat, len(repeat)),
            "match_rate_not_rerun": _share(sum(bool(r["signature"]) for r in read if r["evidence"] == "not run"),
                                           sum(r["evidence"] == "not run" for r in read)),
            "signatures": dict(sorted({s: sum(r.get("signature") == s for r in matched)
                                       for s in {r["signature"] for r in matched}}.items(), key=lambda kv: -kv[1]))}


def history(home: Path, rows: list[dict]) -> dict:
    """Every match judged by natural.py's history check (re-runs, other changes, the default branch), no labeller."""
    from natural import default_branches, flakes, verdict
    from stackvitals.ci.analyze import _failed_step
    counts, cache, branches = {"not caused": 0, "caused": 0, "undetermined": 0}, {}, default_branches(home)
    for r in rows:
        if not r.get("signature"):
            continue
        if r["repo"] not in cache:
            data = DataStore(home / "ci" / r["repo"].replace("/", "__")).load()
            cache = {r["repo"]: (data, flakes(data))}
        data, ev = cache[r["repo"]]
        j = next(x for x in data["jobs"] if x["id"] == r["job_id"])
        run = next(x for x in data["runs"] if x["id"] == j["run"] and x["att"] == j["att"])
        counts[verdict({"run": j["run"], "att": j["att"], "job_id": j["id"], "job": j["n"], "workflow": run.get("path"),
                        "failing_step": _failed_step(j)}, data, ev, branches.get(r["repo"]))["verdict"]] += 1
    decided = counts["not caused"] + counts["caused"]
    return {**counts, "not_caused_among_decided": _share(counts["not caused"], decided)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--home", type=Path, required=True)
    ap.add_argument("--unrun", type=int, default=150)
    ap.add_argument("--seed", type=int, default=5)
    args = ap.parse_args(argv)
    cache = args.home / "outside-fresh.jsonl"
    done = {(r["repo"], r["job_id"]): r for r in (json.loads(x) for x in cache.read_text(encoding="utf-8").splitlines()
                                                  if x.strip())} if cache.exists() else {}
    pool = candidates(args.home)
    unrun = [c for c in pool if c["evidence"] == "not run"]
    chosen = [c for c in pool if c["evidence"] != "not run"] + random.Random(args.seed).sample(unrun, min(args.unrun, len(unrun)))
    token = os.environ.get("GH_TOKEN")
    with httpx.Client(headers={"Authorization": f"Bearer {token}"}, timeout=60, follow_redirects=True) as client, \
            cache.open("a", encoding="utf-8") as out:
        for c in chosen:
            key = (c["repo"], c["job_id"])
            if key in done:
                continue
            resp = None
            for wait in (0, 10, 30, 90):
                time.sleep(wait)
                try:
                    resp = client.get(f"{API}/repos/{c['repo']}/actions/jobs/{c['job_id']}/logs")
                    break
                except httpx.TransportError:
                    continue  # a dropped connection: wait and ask again; the cache keeps what finished
            if resp is None:
                print("network down; run again later", file=sys.stderr)
                break
            if resp.status_code == 403 and resp.headers.get("x-ratelimit-remaining") == "0":
                print("rate limit reached; run again later", file=sys.stderr)
                break
            ok = resp.status_code == 200
            sig = outside_signature(resp.text) if ok else None
            row = {**c, "read": ok, "signature": sig, "status": resp.status_code}
            # Only the verdict is kept, never the log text.
            out.write(json.dumps(row) + "\n")
            done[key] = row
            time.sleep(1.5)
    rows = [done[(c["repo"], c["job_id"])] for c in chosen if (c["repo"], c["job_id"]) in done]
    result = {"candidates": len(pool), "chosen": len(chosen), **score(rows), "matched_by_history": history(args.home, rows)}
    (HERE / "outside-fresh-results.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
