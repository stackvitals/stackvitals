"""The "PR details" verdict on labelled pull-request failures: a job that reads the PR's title, description or labels
(triggers.metadata_jobs on the workflow file) failing with an error about the PR. Run on every labelled failure of the
flaky card and the held-out read; each repo's workflow files are read once from its default branch, as the product does,
and kept in <work>/pr-checks.json.

    python bench/accuracy/flaky/pr_details.py --flaky-home ... --flaky-final ... --wide ... --wide-final ... --cache FILE

Writes pr-details-results.json beside this script (counts and the matched items' repo and job, no log text).
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "agents"))
sys.path.insert(0, str(HERE.parent))
from prepare2 import answer, pool  # noqa: E402
from fair import by_repo  # noqa: E402

from stackvitals.ci.store import DataStore  # noqa: E402
from stackvitals.ci.triggers import PR_EVENTS, metadata_jobs, pr_metadata_triggered  # noqa: E402
from stackvitals.core.stats import wilson  # noqa: E402


def _get(client: httpx.Client, url: str) -> httpx.Response:
    for _ in range(3):
        try:
            return client.get(url)
        except httpx.TransportError:
            continue
    raise SystemExit(f"could not read {url}")


def pr_checks(items: list[dict], cache_path: Path) -> tuple[dict, dict]:
    """Per repo, as the product reads them: {workflow path: jobs that read the PR} (kept out of flake counting) and the
    workflows that also run on PR edits (where an error about the PR reads "PR details")."""
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    token = subprocess.run(["gh", "auth", "token", "--user", "kaushik-yadav"], capture_output=True, text=True).stdout.strip()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.raw"}
    with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as client:
        for repo in sorted({p["repo"] for p in items}):
            home = next(p["home"] for p in items if p["repo"] == repo)
            data = DataStore(Path(home) / "ci" / repo.replace("/", "__")).load()
            paths = sorted({r["path"] for r in data["runs"] if r.get("ev") in PR_EVENTS
                            and (r.get("path") or "").startswith(".github/workflows/")})
            for path in paths:
                if isinstance(cache.get(repo, {}).get(path), dict):
                    continue
                resp = _get(client, f"https://api.github.com/repos/{repo}/contents/{path}")
                ok = resp.status_code == 200
                cache.setdefault(repo, {})[path] = {"jobs": sorted(metadata_jobs(resp.text)) if ok else [],
                                                    "edits": ok and pr_metadata_triggered(resp.text)}
            cache_path.write_text(json.dumps(cache, indent=1, sort_keys=True), encoding="utf-8")
    meta = {repo: {p: set(v["jobs"]) for p, v in found.items() if v["jobs"]} for repo, found in cache.items()}
    edits = {repo: {p for p, v in found.items() if v["edits"] or v["jobs"]} for repo, found in cache.items()}
    return meta, edits


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    for name in ("--flaky-home", "--flaky-final", "--wide", "--wide-final", "--cache"):
        ap.add_argument(name, type=Path, required=True)
    args = ap.parse_args(argv)
    items = pool(args)
    meta, edits = pr_checks(items, args.cache)
    fired, before = [], {}
    for p in items:
        mine = [f for f in answer(p, meta.get(p["repo"]), edits.get(p["repo"]))["failures"] if f["name"].endswith(p["job"])]
        if any(f["verdict"] == "PR details" for f in mine):
            old = [f["verdict"] for f in answer(p)["failures"] if f["name"].endswith(p["job"])]
            fired.append({"repo": p["repo"], "job": p["job"], "caused": p["label"]["caused_by_change"], "was": old[:1]})
    caused = sum(f["caused"] == "yes" for f in fired)
    lo, hi = wilson(caused, len(fired)) if fired else (0.0, 0.0)
    for f in fired:
        was = f["was"][0] if f["was"] else "none"
        before[was] = before.get(was, 0) + 1
    result = {"labelled_items": len(items), "repos": len({p["repo"] for p in items}),
              "repos_with_edit_workflows": sum(1 for r in edits.values() if r),
              "fired": len(fired), "fired_repos": len({f["repo"] for f in fired}), "caused_by_change": caused,
              "caused_low": round(lo, 4), "caused_high": round(hi, 4), "verdict_before": before,
              "by_repo": by_repo([(f["repo"], f["caused"] == "yes") for f in fired if f["caused"] in ("yes", "no")]),
              "matched": fired}
    (HERE / "pr-details-results.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "matched"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
