"""The "already failing" rule measured on labelled failures: a pull request's job that failed in a step the default
branch failed in during the 3 days before, alone and with the same error in both logs. How often each fires, and how
often each labeller called those failures caused by the change (the masking risk: the history check can't judge this,
since it uses the same signal).

    python bench/accuracy/flaky/already.py --home <flaky work folder> --final <final work folder> [--fetch]

Reads the CI history the sample collected; --fetch reads the default-branch failures' logs it lacks (one request each,
GITHUB_TOKEN) into <home>/already-logs, failing step only. Writes already-results.json beside this script.
"""
import argparse
import csv
import json
import os
import sys
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from natural import _default_branch, _labels_jsonl, default_branches  # noqa: E402

from stackvitals.ci.analyze import FAIL, _downstream  # noqa: E402
from stackvitals.ci.feedback import SAFE_FLAKES, failed_on_default, failing_section, same_error  # noqa: E402
from stackvitals.ci.store import DataStore  # noqa: E402
from stackvitals.core.stats import wilson  # noqa: E402


def _items(home: Path) -> dict:
    sample = [json.loads(x) for x in (home / "items.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    sample = [i for i in sample if i.get("sample") not in (None, "none")]
    asof = [json.loads(x) for x in (home / "asof-items.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    return {n: i for n, i in enumerate(sample, 1)} | {1000 + n: i for n, i in enumerate(asof, 1)}


def _share(labels: dict, ids: list) -> dict:
    got = [labels[i]["caused_by_change"] for i in ids if i in labels]
    yes, no = got.count("yes"), got.count("no")
    lo, hi = wilson(yes, yes + no)
    return {"labelled": len(got), "caused": yes, "not_caused": no, "unclear": len(got) - yes - no,
            "caused_low": round(lo, 4), "caused_high": round(hi, 4)}


def _main_log(home: Path, repo: str, job_id: int, fetch: bool) -> str | None:
    path = home / "already-logs" / f"{job_id}.txt"
    if not path.exists() and fetch:
        resp = httpx.get(f"https://api.github.com/repos/{repo}/actions/jobs/{job_id}/logs", follow_redirects=True, timeout=60,
                         headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"})
        path.parent.mkdir(exist_ok=True)
        path.write_text(failing_section(resp.text) if resp.status_code == 200 else "", encoding="utf-8")
    return path.read_text(encoding="utf-8") if path.exists() else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--home", type=Path, required=True)
    ap.add_argument("--final", type=Path, required=True)
    ap.add_argument("--fetch", action="store_true")
    args = ap.parse_args(argv)
    items, cache, fired, checked, branches = _items(args.home), {}, {}, 0, default_branches(args.home)
    for n, it in items.items():
        if it["repo"] not in cache:
            data = DataStore(args.home / "ci" / it["repo"].replace("/", "__")).load()
            cache[it["repo"]] = (data, branches.get(it["repo"]) or _default_branch(data))
        data, main = cache[it["repo"]]
        run = next((r for r in data["runs"] if r["id"] == int(it["run"]) and r["att"] == int(it["att"])), None)
        job = next((j for j in data["jobs"] if j["id"] == int(it["job_id"])), None)
        if not run or not job or run.get("ev") == "push" and run.get("br") == main or run.get("ev") in ("schedule", "workflow_dispatch"):
            continue
        # A gatekeeper that failed because another job had is never shown on its own, so it isn't scored.
        if _downstream(job, [j for j in data["jobs"] if j["run"] == run["id"] and j["att"] == run["att"]]):
            continue
        checked += 1
        found = failed_on_default(data, run, job, it["failing_step"], main)
        if found:
            last = max(j["att"] for j in data["jobs"] if j["run"] == found["run"] and j["n"] == job["n"])
            final = [j for j in data["jobs"] if j["run"] == found["run"] and j["att"] == last and j["n"] == job["n"]]
            main_log = _main_log(args.home, it["repo"], found["job"], args.fetch)
            fired[n] = {"repo": it["repo"], "sample": it["sample"], "event": run.get("ev"), "ago": found["ago"],
                        "main_final_failed": any(j["c"] in FAIL for j in final), "main_log": main_log is not None,
                        "same_error": same_error(failing_section(it.get("log")), main_log)}
    claude = _labels_jsonl(args.home / "labels.jsonl") | _labels_jsonl(args.home / "asof-labels.jsonl")
    gemini = {int(r["id"]): r for f in ("labels-gemini-flaky.csv", "labels-gemini-masking.csv")
              for r in csv.DictReader((HERE / f).open(encoding="utf-8"))}
    final = _labels_jsonl(args.final / "labels.jsonl") | _labels_jsonl(args.final / "asof-labels.jsonl")
    labellers = {"claude": claude, "gemini": gemini, "adjudicated": final}
    ids = sorted(fired)
    same = [i for i in ids if fired[i]["same_error"]]
    pool = json.loads((args.home / "masking-pool.json").read_text(encoding="utf-8"))
    by_key = {(i["repo"], int(i["job_id"])): n for n, i in items.items()}
    pool_ids = {by_key[(p["repo"], int(p["job_id"]))]: p for p in pool if (p["repo"], int(p["job_id"])) in by_key}
    blocked = [n for n, p in pool_ids.items() if not (int(p["flakes"]) >= SAFE_FLAKES and p["step"] in p["flake_steps"])]
    out = {"rule": "a pull request's job failed in a step the default branch failed in during the 3 days before",
           "checked": checked, "fires": len(ids), "repos": len({fired[i]["repo"] for i in ids}),
           "main_still_failing": sum(fired[i]["main_final_failed"] for i in ids),
           "by_labeller": {k: _share(v, ids) for k, v in labellers.items()},
           "same_error": {"fires": len(same), "repos": len({fired[i]["repo"] for i in same}),
                          "by_labeller": {k: _share(v, same) for k, v in labellers.items()}},
           "masking_pool": {"failures": len(pool_ids), "blocked": len(blocked), "step_fires": sum(n in fired for n in blocked),
                            "same_error_fires": sum(n in same for n in blocked)},
           "fired": {str(i): {**fired[i], "labels": {k: v[i]["caused_by_change"] for k, v in labellers.items() if i in v}}
                     for i in ids}}
    (HERE / "already-results.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "fired"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
