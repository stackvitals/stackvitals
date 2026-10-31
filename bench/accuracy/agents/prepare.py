"""The agent head-to-head: questions about public repos' CI, answered by a general agent with live GitHub access and by
the same agent with StackVitals' answers too, scored against the flaky card's labels.

    python bench/accuracy/agents/prepare.py --flaky-home <flaky work folder> --out <folder> --ci-records <crawl ci folder>
    (run the arms with the prompts in prompts.md)
    python bench/accuracy/agents/score.py --out <folder>

prepare writes, per repo: questions-<n>.json (no labels), StackVitals' answers in sv-<n>/ (CI health as of the window's
end; each asked failure's verdict from the history before it), truth-<n>.json (kept from the agents), and gh.py, a
GitHub GET wrapper that counts calls and stops at the budget.
"""
import argparse
import gzip
import json
import random
import statistics
import sys
from datetime import datetime
from pathlib import Path

from mergescout.bench.ci import tier
from stackvitals.ci.analyze import analyze
from stackvitals.ci.feedback import classify_run
from stackvitals.ci.store import DataStore

REPOS = ["gmickel/gno", "paritytech/revive", "AikidoSec/firewall-dotnet", "munich-quantum-toolkit/core", "GAM-team/GAM"]
PER_SIDE, BUDGET, WINDOW = 2, 100, 14
HERE = Path(__file__).parent
GH = '''"""GET one GitHub API path and print the body; every call is logged, and the budget is enforced.
    python gh.py <api path, e.g. repos/o/r/actions/runs?per_page=50>"""
import json, subprocess, sys
from pathlib import Path
import httpx
LOG, BUDGET = Path(__file__).with_name("calls-{arm}.log"), {budget}
used = len(LOG.read_text(encoding="utf-8").splitlines()) if LOG.exists() else 0
if used >= BUDGET:
    sys.exit(f"budget spent: {{BUDGET}} calls")
token = subprocess.run(["gh", "auth", "token", "--user", "kaushik-yadav"], capture_output=True, text=True).stdout.strip()
path = sys.argv[1].lstrip("/")
resp = httpx.get(f"https://api.github.com/{{path}}", headers={{"Authorization": f"Bearer {{token}}", "Accept": "application/vnd.github+json"}},
                 follow_redirects=True, timeout=60)
with LOG.open("a", encoding="utf-8") as f:
    f.write(path + "\\n")
print(f"HTTP {{resp.status_code}}; calls used {{used + 1}} of {{BUDGET}}")
print(resp.text[:200000])
'''


def _when(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def peers(records: Path, out: Path) -> None:
    """The cross-repo question: each repo's first-try share against public repos of its language and star band, from
    the crawl's CI records; StackVitals' answer goes in sv-<n>/peers.json, the crawl's numbers in peer-truth.json."""
    recs = {}
    for path in sorted(records.glob("ci-*.ndjson.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                recs[r["repo"]] = r
    truth = {}
    for k, repo in enumerate(REPOS):
        r = recs[repo]
        group = [float(x["first_try_share"]) for x in recs.values() if x.get("language") == r["language"]
                 and tier(int(x["stars"])) == tier(int(r["stars"])) and int(x["pushes"]) >= 20 and x.get("first_try_share")]
        own = float(r["first_try_share"])
        answer = {"repo": repo, "day": r["day"], "pushes": int(r["pushes"]), "first_try_share": own, "language": r["language"],
                  "stars_band": tier(int(r["stars"])), "peer_repos": len(group), "peer_median": round(statistics.median(group), 4),
                  "percentile": round(sum(g < own for g in group) / len(group) * 100)}
        truth[repo] = answer
        (out / f"sv-{k}" / "peers.json").write_text(json.dumps(answer, indent=1), encoding="utf-8")
    (out / "peer-questions.json").write_text(json.dumps([{"k": k, "repo": repo, "ask": (
        f"In the 14 days before {truth[repo]['day']}, what share of pushes to {repo}'s default branch passed CI on the first "
        f"try (no failed job, no re-run)? How does that compare with public {truth[repo]['language']} repos with "
        f"{truth[repo]['stars_band']} stars: what share is typical for them, and roughly what percentile is this repo?")}
        for k, repo in enumerate(REPOS)], indent=1), encoding="utf-8")
    (out / "peer-truth.json").write_text(json.dumps(truth, indent=1), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--flaky-home", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--ci-records", type=Path, default=None, help="the crawl's ci-*.ndjson.gz folder, for the cross-repo question")
    args = ap.parse_args(argv)
    home, out, rng = args.flaky_home, args.out, random.Random(args.seed)
    out.mkdir(parents=True, exist_ok=True)
    items = [i for i in (json.loads(x) for x in (home / "items.jsonl").read_text(encoding="utf-8").splitlines() if x.strip())
             if i.get("sample") != "none"]
    labels = {json.loads(x)["id"]: json.loads(x) for x in (home / "labels.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()}
    for arm in ("a", "b"):
        (out / f"gh-{arm}.py").write_text(GH.format(arm=arm, budget=BUDGET * len(REPOS)), encoding="utf-8")
    for k, repo in enumerate(REPOS):
        data = DataStore(home / "ci" / repo.replace("/", "__")).load()
        end = max(_when(r["up"] or r["cr"]) for r in data["runs"])
        start = min(_when(r["cr"]) for r in data["runs"])
        sure = [(n, i, labels[n]) for n, i in enumerate(items, 1) if i["repo"] == repo and labels[n]["caused_by_change"] != "unclear"
                and labels[n]["own_failure"] == "yes" and labels[n]["confidence"] in ("high", "medium")]
        picked = []
        for side in ("no", "yes"):
            pool = [x for x in sure if x[2]["caused_by_change"] == side]
            rng.shuffle(pool)
            picked += pool[:PER_SIDE]
        rng.shuffle(picked)
        questions, truth, sv = [], [], out / f"sv-{k}"
        sv.mkdir(exist_ok=True)
        for q, (n, i, lab) in enumerate(picked, 1):
            questions.append({"q": q, "url": i["url"], "job": i["job"], "attempt": int(i["att"]),
                              "ask": "Did this job attempt fail because of the change under review, or was it a flake (it would "
                                     "have passed on the same code)?"})
            truth.append({"q": q, "item": n, "sample": i["sample"], "caused_by_change": lab["caused_by_change"]})
            # StackVitals' verdict as it would have read then: the history before this run only.
            run = next(r for r in data["runs"] if r["id"] == int(i["run"]) and r["att"] == int(i["att"]))
            before = {"runs": [r for r in data["runs"] if _when(r["cr"]) < _when(run["cr"]) or r["id"] == run["id"]],
                      "jobs": data["jobs"], "tests": data.get("tests") or []}
            before["runs"] = [r for r in before["runs"] if not (r["id"] == run["id"] and r["att"] > run["att"])]
            result = analyze({**before, "runs": [r for r in before["runs"] if r["id"] != run["id"]]}, _when(run["cr"]), window_days=30)
            # The failed job's log, as the action reads it when it comments (the sample keeps the part around the error).
            verdicts = [v for v in classify_run(before, result, run["id"], logs={int(i["job_id"]): i.get("log") or ""})
                        if v["kind"] == "job"]
            (sv / f"ci_failure-{q}.json").write_text(json.dumps({"question": q, "failures": verdicts}, indent=1), encoding="utf-8")
        flaked = sorted({i["job"] for n, i, lab in sure if i["sample"] == "flagged" and lab["caused_by_change"] == "no"})
        health = analyze(data, end, window_days=WINDOW)
        (sv / "ci_health.json").write_text(json.dumps({"repo": repo, "window": [start.isoformat(), end.isoformat()], "jobs": [
            {k2: j.get(k2) for k2 in ("workflow", "job", "state", "runs", "failures", "flake_events", "flake_steps", "last_flake")}
            for j in health["jobs"] if j.get("flake_events") or j.get("state") not in ("ok", None)]}, indent=1), encoding="utf-8")
        (out / f"questions-{k}.json").write_text(json.dumps({
            "repo": repo, "items": questions,
            "history": {"ask": f"Which jobs (workflow file and job name) flaked, meaning they failed and then passed on the same "
                               f"code, in runs created between {start:%Y-%m-%d %H:%M} and {end:%Y-%m-%d %H:%M} UTC?"}}, indent=1),
            encoding="utf-8")
        (out / f"truth-{k}.json").write_text(json.dumps({"repo": repo, "items": truth, "flaked_jobs_labelled": flaked}, indent=1),
                                             encoding="utf-8")
        print(repo, len(questions), "items;", len(flaked), "labelled flaky jobs")
    if args.ci_records:
        peers(args.ci_records, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
