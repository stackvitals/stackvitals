"""Which deployments each rule counts, on public repos the rules were never tuned on: StackVitals' source choice,
DevLake's default deploy pattern and merge-as-deploy, scored against labels of what each repo really ships.

    GH_TOKEN=... python bench/accuracy/dora/sources.py collect <folder of the crawl's ci-*.ndjson.gz> --home <work folder>
    python bench/accuracy/dora/sources.py score --home <work folder>

collect draws repos from the crawl's CI records (seeded), reads each one's workflows and their files, its releases and
deployments (the app's own query) and 90 days of runs of every workflow a rule could count, then writes what each rule
counts (rules.json) and a blind labelling view (view.jsonl: workflow files, releases and deployments, no rule output).
score reads labels.jsonl and writes sources-results.json and sources-labels.csv (links and labels) beside this script.
Paced to at most 1,000 requests an hour; workflow files come from raw.githubusercontent.com, outside the API limit.
"""
import argparse
import csv
import gzip
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from stackvitals.ci.collect import run_record
from stackvitals.core.config import parse
from stackvitals.core.delivery import deploy_kind, find_deployments
from stackvitals.core.stats import wilson

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fair import mcnemar  # noqa: E402
from stackvitals.flow.collect import REPO_QUERY, _repo_fields

API = "https://api.github.com"
DEVLAKE = re.compile(r"(?i)(deploy|push-image)")  # DevLake's default deploymentPattern, matched on the run's name
DAYS, PAGES, YAML_CHARS, GAP = 90, 3, 6000, 3.6
# How the labels name a repo's shipments, and the source each StackVitals choice stands for.
SOURCES = ("deployments", "deploy_workflow", "releases", "release_workflow", "every_merge", "none")
OURS = {"deployments api": "deployments", "deploy workflows": "deploy_workflow", "releases": "releases",
        "release workflows": "release_workflow", None: "none"}
HERE = Path(__file__).parent


def _draw(records: Path, n: int, seed: int) -> list[str]:
    seen = {}
    for path in sorted(records.glob("ci-*.ndjson.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if int(r.get("pushes") or 0) >= 10:
                    seen[r["repo"]] = r
    names = sorted(seen)
    return random.Random(seed).sample(names, min(n, len(names)))


class Client:
    def __init__(self, token: str):
        self.http = httpx.Client(timeout=60, follow_redirects=True,
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})

    def get(self, url: str, **params):
        time.sleep(GAP)
        for wait in (0, 30, 120, 600):
            time.sleep(wait)
            try:
                return self.http.get(url if url.startswith("http") else f"{API}/{url}", params=params or None)
            except httpx.TransportError:
                continue
        raise RuntimeError(f"network down at {url}")

    def graphql(self, query: str, variables: dict) -> dict:
        time.sleep(GAP)
        for wait in (0, 30, 120, 600):
            time.sleep(wait)
            try:
                return self.http.post(f"{API}/graphql", json={"query": query, "variables": variables}).json()
            except httpx.TransportError:
                continue
        raise RuntimeError("network down at graphql")


def _yaml(repo: str, branch: str, path: str) -> str:
    try:
        resp = httpx.get(f"https://raw.githubusercontent.com/{repo}/{branch}/{path}", timeout=30)
        return resp.text[:YAML_CHARS] if resp.status_code == 200 else f"(file unavailable: HTTP {resp.status_code})"
    except httpx.HTTPError as exc:
        return f"(file unavailable: {type(exc).__name__})"


def collect_repo(gh: Client, repo: str, cfg: dict, now: datetime) -> tuple[dict, dict]:
    owner, name = repo.split("/")
    data = gh.graphql(REPO_QUERY, {"owner": owner, "name": name})
    info = _repo_fields((data.get("data") or {}).get("repository") or {})
    branch = info.get("default_branch") or "main"
    since = now - timedelta(days=DAYS)
    stamp = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    flows = [w for w in gh.get(f"repos/{repo}/actions/workflows", per_page=100).json().get("workflows", [])
             if w.get("path", "").startswith(".github/workflows/")]
    runs, counted_by = [], {}
    for w in flows:
        ours = deploy_kind(w["name"], w["path"], cfg["delivery"]["deploy_workflow"])
        devlake = bool(DEVLAKE.search(w["name"] or ""))
        counted_by[w["path"]] = {"ours": ours is not None, "devlake": devlake}
        if not (ours or devlake) or w.get("state") != "active":
            continue
        for page in range(1, PAGES + 1):
            body = gh.get(f"repos/{repo}/actions/workflows/{w['id']}/runs", per_page=100, page=page,
                          created=f">={since.strftime('%Y-%m-%d')}").json()
            got = body.get("workflow_runs") or []
            runs += [run_record(r, r.get("run_attempt") or 1) for r in got]
            if len(got) < 100:
                break
    # Every default-branch commit stands in for the push runs CI Health would hold (the side-service check reads them).
    commits = []
    for page in range(1, PAGES + 1):
        got = gh.get(f"repos/{repo}/commits", sha=branch, since=stamp, per_page=100, page=page).json()
        commits += got if isinstance(got, list) else []
        if not isinstance(got, list) or len(got) < 100:
            break
    pushes = [{"t": "run", "id": -k, "att": 1, "wfn": "CI", "path": ".github/workflows/ci.yml", "ev": "push", "br": branch,
               "sha": c["sha"], "c": "success", "up": c["commit"]["committer"]["date"]} for k, c in enumerate(commits, 1)]
    record = {"default_branch": branch, "deployments": [d for d in info.get("deployments") or [] if (d.get("at") or "") >= stamp],
              "releases": [x for x in info.get("releases") or [] if (x.get("at") or "") >= stamp]}
    found, source = find_deployments(record, {"runs": runs + pushes}, cfg)
    devlake_runs = [r for r in runs if DEVLAKE.search(r.get("wfn") or "") and r.get("c") == "success"]
    run_path = {f"run:{r['id']}": r["path"] for r in runs}
    rules = {"repo": repo, "stackvitals": {"source": source, "deployments": len(found),
                                           "workflows": sorted({run_path[d["id"]] for d in found if d.get("id") in run_path})},
             "devlake": {"deployments": len({r["id"] for r in devlake_runs}), "workflows": sorted({r["path"] for r in devlake_runs})},
             "merges": {"deployments": len(commits)}, "workflows": counted_by}
    envs = {}
    for d in record["deployments"]:
        envs[d.get("env")] = envs.get(d.get("env"), 0) + 1
    view = {"repo": repo, "default_branch": branch, "commits_to_default_90d": len(commits),
            "releases_90d": [{"tag": x["tag"], "prerelease": x["pre"], "at": x["at"]} for x in record["releases"]][:20],
            "releases_90d_total": len(record["releases"]), "deployments_90d_by_environment": envs,
            "workflows": [{"name": w["name"], "path": w["path"], "state": w.get("state"),
                           "file": _yaml(repo, branch, w["path"])} for w in flows]}
    return rules, view


def collect(args) -> int:
    token = os.environ.get("GH_TOKEN")
    if not token:
        print("GH_TOKEN is not set", file=sys.stderr)
        return 1
    gh, cfg, now = Client(token), parse("")[0], datetime.now(timezone.utc)
    args.home.mkdir(parents=True, exist_ok=True)
    rules_path, view_path = args.home / "rules.json", args.home / "view.jsonl"
    rules = json.loads(rules_path.read_text(encoding="utf-8")) if rules_path.exists() else {}
    # A later, larger sample leaves out the repos an earlier one already labelled, so the two stay independent.
    skip = set(json.loads(args.exclude.read_text(encoding="utf-8"))) if args.exclude else set()
    for repo in _draw(args.records, args.repos, args.seed):
        if repo in rules or repo in skip:
            continue
        try:
            got, view = collect_repo(gh, repo, cfg, now)
        except (RuntimeError, KeyError, ValueError) as exc:
            print(f"{repo}: skipped ({type(exc).__name__}: {exc})", flush=True)
            continue
        rules[repo] = got
        rules_path.write_text(json.dumps(rules, indent=1), encoding="utf-8")
        with view_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(view) + "\n")
        print(f"{repo}: {len(view['workflows'])} workflows, ours {got['stackvitals']['source']}", flush=True)
    return 0


def _share(k: int, n: int) -> dict:
    lo, hi = wilson(k, n)
    return {"n": n, "share": round(k / n, 4) if n else None, "low": round(lo, 4), "high": round(hi, 4)}


def _pr(rows: list[tuple[bool, bool]]) -> dict:
    """Precision and recall of a yes/no rule against labels: rows of (rule said yes, label says yes)."""
    tp = sum(r and t for r, t in rows)
    return {"precision": _share(tp, sum(r for r, _ in rows)), "recall": _share(tp, sum(t for _, t in rows))}


def score(args) -> int:
    rules = json.loads((args.home / "rules.json").read_text(encoding="utf-8"))
    read = lambda p: [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]  # noqa: E731
    labels = {r["repo"]: r for p in sorted(args.home.glob("labels-*.jsonl")) for r in read(p)}
    missing = sorted(set(rules) - set(labels))
    if missing:
        print(f"repos without a label: {missing}", file=sys.stderr)
        return 1
    # A workflow whose file can't be read (GitHub still lists some deleted ones) has no label to score against.
    unread = {(v["repo"], w["path"]) for v in read(args.home / "view.jsonl") for w in v["workflows"]
              if w["file"].startswith("(file unavailable")}
    flows, repos = [], []
    for repo, got in sorted(rules.items()):
        lab = labels[repo]
        ships = {p for p, v in lab["workflows"].items() if v == "yes"}
        for path, said in got["workflows"].items():
            # A workflow the labeller gave no answer for (null) is left out, never guessed.
            if (repo, path) not in unread and lab["workflows"].get(path, "no") is not None:
                flows.append((said["ours"], said["devlake"], path in ships))
        ok = set(lab["sources"])
        ours = OURS[got["stackvitals"]["source"]]
        # A workflow source is right only if every workflow it counted ships.
        ours_right = ours in ok and set(got["stackvitals"]["workflows"]) <= ships
        dl = got["devlake"]["workflows"]
        dl_right = (not dl and "none" in ok) or (bool(dl) and set(dl) <= ships and bool(ok & {"deploy_workflow", "release_workflow", "every_merge"}))
        repos.append({"repo": repo, "truth": sorted(ok), "stackvitals": ours, "stackvitals_right": ours_right,
                      "devlake_right": dl_right, "merges_right": "every_merge" in ok})
    out = {"repos": len(repos), "workflows": len(flows), "labeller": args.labeller,
           "workflow_rule": {"stackvitals": _pr([(o, t) for o, _d, t in flows]), "devlake": _pr([(d, t) for _o, d, t in flows])},
           "source_right": {k: _share(sum(r[f"{k}_right"] for r in repos), len(repos)) for k in ("stackvitals", "devlake", "merges")},
           # Same repos for every rule, so each comparison is paired: repos only ours got right against only theirs.
           "source_right_tests": {k: mcnemar(sum(r["stackvitals_right"] and not r[f"{k}_right"] for r in repos),
                                             sum(r[f"{k}_right"] and not r["stackvitals_right"] for r in repos))
                                  for k in ("devlake", "merges")},
           "truth_mix": {s: sum(s in r["truth"] for r in repos) for s in SOURCES},
           "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    second = args.home / "second.jsonl"
    if second.exists():
        two = [(labels[r["repo"]], r) for r in read(second) if r["repo"] in labels]
        same_flows = [a["workflows"].get(p) == v for a, b in two for p, v in b["workflows"].items()]
        out["agreement"] = {"repos": len(two), "same_sources": sum(set(a["sources"]) == set(b["sources"]) for a, b in two),
                            "workflows": len(same_flows), "same_workflow_labels": sum(same_flows)}
    (HERE / f"sources{args.suffix}-results.json").write_text(json.dumps(out, indent=1, sort_keys=True), encoding="utf-8")
    with (HERE / f"sources{args.suffix}-labels.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["repo", "url", "truth", "stackvitals_source", "stackvitals_right", "devlake_right", "merges_right"])
        for r in repos:
            w.writerow([r["repo"], f"https://github.com/{r['repo']}/actions", " ".join(r["truth"]), r["stackvitals"],
                        r["stackvitals_right"], r["devlake_right"], r["merges_right"]])
    print(json.dumps(out, indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("records", type=Path)
    c.add_argument("--home", type=Path, required=True)
    c.add_argument("--repos", type=int, default=25)
    c.add_argument("--seed", type=int, default=13)
    c.add_argument("--exclude", type=Path, help="rules.json of an earlier sample whose repos are left out")
    s = sub.add_parser("score")
    s.add_argument("--home", type=Path, required=True)
    s.add_argument("--labeller", default="model (Claude), audit pending")
    s.add_argument("--suffix", default="", help="writes sources<suffix>-results.json, for a second sample beside the first")
    args = ap.parse_args(argv)
    return collect(args) if args.cmd == "collect" else score(args)


if __name__ == "__main__":
    sys.exit(main())
