"""A plausibility check of "began around" (`ci/analyze._began`): for the flaky jobs whose start is called clear on the
wide read, how often one of the commits named (reaching the default branch the day before) touched the job's workflow
file or a test file, against as many other default-branch commits of the same repos picked at random.

    GH_TOKEN=... python bench/accuracy/flaky/began.py --home <wide work folder> [--seed 3]

One request per commit looked at (cached in the work folder). It shows whether named commits stand out; it can't show
they caused the flake. Writes began-results.json beside this script (counts only).
"""
import argparse
import json
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

from stackvitals.ci.analyze import analyze
from stackvitals.ci.burnin import TEST_FILE
from stackvitals.ci.store import DataStore
from stackvitals.core.stats import fisher, wilson

API = "https://api.github.com"


def _files(client: httpx.Client, cache: dict, repo: str, sha: str) -> list[str] | None:
    key = f"{repo}@{sha}"
    if key not in cache:
        resp = client.get(f"{API}/repos/{repo}/commits/{sha}")
        cache[key] = [f["filename"] for f in resp.json().get("files") or []] if resp.status_code == 200 else None
    return cache[key]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--home", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=3)
    args = ap.parse_args(argv)
    rng = random.Random(args.seed)
    cache_path = args.home / "began-cache.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    client = httpx.Client(timeout=60, follow_redirects=True, headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}"})
    named, other, starts, jobs = [0, 0], [0, 0], 0, []
    now = datetime.now(timezone.utc)
    for folder in sorted((args.home / "ci").iterdir()):
        store = DataStore(folder)
        data, branch = store.load(), store.state().get("default_branch")
        repo = folder.name.replace("__", "/", 1)
        result = analyze(data, now, window_days=40, default_branch=branch)
        pushes = sorted({r["sha"] for r in data["runs"] if r.get("ev") == "push" and r.get("br") == branch and r.get("sha")})
        for j in result["jobs"]:
            b = j.get("began")
            if not (b and b["clear"] and b["landed"]):
                continue
            starts += 1
            jobs.append(f"{repo} / {j['job']}")
            touches = lambda files: any(f == j["workflow"] or TEST_FILE.search(f) for f in files)  # noqa: E731
            for group, shas in ((named, b["landed"]), (other, rng.sample([s for s in pushes if s not in b["landed"]],
                                                                            min(len(b["landed"]), len(pushes) - len(b["landed"]))))):
                for sha in shas:
                    files = _files(client, cache, repo, sha)
                    if files is not None:
                        group[0] += touches(files)
                        group[1] += 1
            cache_path.write_text(json.dumps(cache), encoding="utf-8")
    lo, hi = wilson(*named)
    out = {"clear_starts": starts, "jobs": jobs,
           "named_commits": {"touched_workflow_or_tests": named[0], "n": named[1], "low": round(lo, 4), "high": round(hi, 4)},
           "random_commits": {"touched_workflow_or_tests": other[0], "n": other[1]},
           "fisher_p": round(fisher(named[0], named[1], other[0], other[1]), 4)}
    (Path(__file__).with_name("began-results.json")).write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
