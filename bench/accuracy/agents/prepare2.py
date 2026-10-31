"""The bigger head-to-head (Phase 15 M4): 100 labelled pull-request failures from the flaky card's sample and the
held-out read, half the change's own failure and half flakes, at most 4 per repo, seeded. For each: the question (the
job attempt's URL), StackVitals' answer as the MCP tool gives it now (verdict, error lines, track record, what it
checked), computed from the history before that failure, and the label.

    python bench/accuracy/agents/prepare2.py --flaky-home <flaky work> --flaky-final <final labels folder>
                                             --wide <wide work> --wide-final <final/heldout.jsonl> --out <folder>

Writes questions-<n>.json and sv-<n>/ci_failure-<q>.json per repo group, truth.json, and gh-<arm>.py call-counting
wrappers into --out (local only).
"""
import argparse
import json
import random
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from stackvitals.ci.analyze import _failed_step, analyze
from stackvitals.ci.feedback import (TRACK_RECORD, classify_run, error_excerpt, failed_on_default, failing_section,
                                     failure_summary)
from stackvitals.ci.store import DataStore

GH = '''"""GET one GitHub API path and print the body; every call is logged and the budget enforced.
    python gh-{arm}.py <api path>"""
import subprocess, sys
from pathlib import Path
import httpx
LOG, BUDGET = Path(__file__).with_name("calls-{arm}.log"), {budget}
used = len(LOG.read_text(encoding="utf-8").splitlines()) if LOG.exists() else 0
if used >= BUDGET:
    sys.exit(f"budget spent: {{BUDGET}} calls")
token = subprocess.run(["gh", "auth", "token", "--user", "kaushik-yadav"], capture_output=True, text=True).stdout.strip()
path = sys.argv[1].lstrip("/")
resp = httpx.get(f"https://api.github.com/{{path}}", headers={{"Authorization": f"Bearer {{token}}",
                 "Accept": "application/vnd.github+json"}}, follow_redirects=True, timeout=60)
with LOG.open("a", encoding="utf-8") as f:
    f.write(path + "\\n")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
text = resp.text
print(f"HTTP {{resp.status_code}}; calls used {{used + 1}} of {{BUDGET}}")
if len(text) > 200000:
    # A job log's failure is at its end, so a long body keeps its last part.
    print(f"(first {{len(text) - 200000}} characters cut; the end follows)")
    text = text[-200000:]
print(text)
'''
ARMS = ("a-sonnet", "b-sonnet", "a-haiku", "b-haiku")


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _when(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def pool(args) -> list[dict]:
    out = []
    items = [i for i in _jsonl(args.flaky_home / "items.jsonl") if i.get("sample") != "none"]
    labels = {r["id"]: r for r in _jsonl(args.flaky_final / "labels.jsonl")}
    out += [{**i, "home": str(args.flaky_home), "label": labels[n]} for n, i in enumerate(items, 1) if n in labels]
    wide = _jsonl(args.wide / "labelled-items.jsonl")
    wl = {r["id"]: r for r in _jsonl(args.wide_final)}
    out += [{**i, "home": str(args.wide), "label": wl[n]} for n, i in enumerate(wide, 1) if n in wl]
    return [p for p in out if p["label"]["caused_by_change"] in ("yes", "no") and p["label"]["own_failure"] == "yes"
            and p["label"].get("confidence") in ("high", "medium") and p.get("event") in ("pull_request", "pull_request_target")
            and "(log unavailable" not in (p.get("log") or "")[:40]]


def answer(p: dict, pr_metadata: dict | None = None, pr_edits: set | None = None) -> dict:
    """StackVitals' ci_failure answer for this failure, from the history before it only; pr_metadata and pr_edits are
    the repo's PR-reading jobs and PR-edit workflows (bench/accuracy/flaky/pr_details.py)."""
    store = DataStore(Path(p["home"]) / "ci" / p["repo"].replace("/", "__"))
    data, branch = store.load(), store.state().get("default_branch")
    run = next(r for r in data["runs"] if r["id"] == int(p["run"]) and r["att"] == int(p["att"]))
    now = _when(run["cr"])
    keep = {(r["id"], r["att"]) for r in data["runs"] if _when(r["cr"]) < now or (r["id"] == run["id"] and r["att"] <= run["att"])}
    before = {"runs": [r for r in data["runs"] if (r["id"], r["att"]) in keep],
              "jobs": [j for j in data["jobs"] if (j["run"], j["att"]) in keep], "tests": []}
    history = {"runs": [r for r in before["runs"] if r["id"] != run["id"]], "jobs": before["jobs"]}
    result = analyze(history, now, window_days=30, default_branch=branch, pr_metadata=pr_metadata,
                      pr_edits=pr_edits)
    logs = {int(p["job_id"]): p.get("log") or ""}
    job = next((j for j in data["jobs"] if j["id"] == int(p["job_id"])), None)
    main = failed_on_default(before, run, job, _failed_step(job), branch) if job and p.get("main_log") else None
    if main:
        logs[main["job"]] = p["main_log"]  # the default branch's log the held-out read kept, as classify() would read it
    items = [i for i in classify_run(before, result, run["id"], logs=logs) if i["kind"] == "job"]
    for i in items:
        i["url"] = f"https://github.com/{p['repo']}/actions/runs/{run['id']}/job/{i['job_id']}"
        i["errors"] = error_excerpt(failing_section(logs.get(i["job_id"])))
        i["right_so_far"] = TRACK_RECORD.get(i["verdict"])
    return {"failures": items, "summary": failure_summary(items), "checked": [f"this run's failed jobs and the failing step's log",
                                           f"30 days of this repo's CI history before the failure"]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    for name in ("--flaky-home", "--flaky-final", "--wide", "--wide-final", "--out"):
        ap.add_argument(name, type=Path, required=True)
    ap.add_argument("--seed", type=int, default=29)
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--pr-checks", type=Path, help="cache of the repos' workflow files (flaky/pr_details.py)")
    args = ap.parse_args(argv)
    rng = random.Random(args.seed)
    candidates = pool(args)
    rng.shuffle(candidates)
    picked, per_repo = [], defaultdict(int)
    meta, edits = {}, {}
    for side in ("yes", "no"):
        for p in candidates:
            if p["label"]["caused_by_change"] == side and per_repo[p["repo"]] < 4 and \
                    sum(x["label"]["caused_by_change"] == side for x in picked) < args.n // 2:
                picked.append(p)
                per_repo[p["repo"]] += 1
    groups = defaultdict(list)
    for p in picked:
        groups[p["repo"]].append(p)
    if args.pr_checks:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "flaky"))
        from pr_details import pr_checks
        meta, edits = pr_checks(picked, args.pr_checks)
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    truth = []
    for k, repo in enumerate(sorted(groups)):
        (out / f"sv-{k}").mkdir(exist_ok=True)
        questions = []
        for q, p in enumerate(groups[repo], 1):
            questions.append({"q": q, "url": p["url"], "job": p["job"], "attempt": int(p["att"]),
                              "ask": "Did this job attempt fail because of the change under review, or was it a flake "
                                     "(it would have passed on the same code)?"})
            (out / f"sv-{k}" / f"ci_failure-{q}.json").write_text(json.dumps(answer(p, meta.get(repo), edits.get(repo)), indent=1), encoding="utf-8")
            truth.append({"k": k, "q": q, "repo": repo, "caused_by_change": p["label"]["caused_by_change"], "url": p["url"]})
        (out / f"questions-{k}.json").write_text(json.dumps({"repo": repo, "items": questions}, indent=1), encoding="utf-8")
    (out / "truth.json").write_text(json.dumps(truth, indent=1), encoding="utf-8")
    for arm in ARMS:
        (out / f"gh-{arm}.py").write_text(GH.format(arm=arm, budget=20 * len(picked)), encoding="utf-8")
    print(f"{len(picked)} items in {len(groups)} repos; caused {sum(p['label']['caused_by_change'] == 'yes' for p in picked)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
