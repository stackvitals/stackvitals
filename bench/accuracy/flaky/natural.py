"""Whether a failure was caused by the change, judged without any labeller from what GitHub already recorded: the same
job re-run on identical code, and the same job flaking on other changes (other pull requests or branches).

- not caused: a run on the identical code passed, and the same job flaked in the same step on other changes too, so
  the flakiness doesn't need this change (strongest when one of those came before this failure);
- caused: it failed again on identical code, while the same job passed on other changes in the days around it and
  failed on none of them;
- anything else stays undetermined.

    python bench/accuracy/flaky/natural.py --home <flaky work folder> [--final <final labels folder>] [--fetch-branches]

Reads only the CI history the sample already collected, and each repo's real default branch from
<home>/default-branches.json (--fetch-branches writes it: one request per repo, GITHUB_TOKEN). Writes
natural-results.json beside this script: the verdicts' counts and how often each labeller's "caused by the change"
agrees with them.
"""
import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from views import rerun  # noqa: E402

from stackvitals.ci.analyze import FAIL, PASS, SAME_CODE_EVENTS, _downstream, _failed_step  # noqa: E402
from stackvitals.ci.store import DataStore  # noqa: E402
from stackvitals.core.stats import wilson  # noqa: E402

AROUND = timedelta(days=3)


def _t(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def flakes(data: dict) -> dict:
    """Flake events per (workflow path, job): a later attempt passed, or identical code both failed and passed."""
    runs = {(r["id"], r["att"]): r for r in data["runs"]}
    last = {}
    for rid, att in runs:
        last[rid] = max(att, last.get(rid, 0))
    by_att = defaultdict(list)
    for j in data["jobs"]:
        by_att[(j["run"], j["att"])].append(j)
    out = defaultdict(list)

    def add(run, job, kind):
        out[(run.get("path"), job["n"])].append({"run": run["id"], "tree": run.get("tree") or run.get("sha"),
                                                 "br": run.get("br"), "pr": run.get("pr") or [], "step": _failed_step(job),
                                                 "at": _t(job.get("en")) or _t(run.get("cr")), "kind": kind})
    for rid, top in last.items():
        seq = defaultdict(list)
        for att in range(1, top + 1):
            for j in by_att.get((rid, att), []):
                seq[j["n"]].append((att, j))
        for name, items in seq.items():
            fails = [(a, j) for a, j in items if j["c"] in FAIL and not _downstream(j, by_att[(rid, a)])]
            if fails and any(j["c"] in PASS and a > min(fails, key=lambda x: x[0])[0] for a, j in items):
                a, j = min(fails, key=lambda x: x[0])
                add(runs[(rid, a)], j, "retry")
    finals = defaultdict(list)
    for rid, top in last.items():
        run = runs[(rid, top)]
        if run.get("ev") in SAME_CODE_EVENTS:
            for j in by_att.get((rid, top), []):
                finals[(run.get("path"), j["n"], run.get("tree"), run.get("ev"))].append((run, j))
    for (_p, _n, tree, _ev), items in finals.items():
        failed = [(r, j) for r, j in items if j["c"] in FAIL and not _downstream(j, by_att[(r["id"], r["att"])])]
        if tree and failed and any(j["c"] in PASS for _r, j in items):
            r, j = max(failed, key=lambda x: x[0]["cr"])
            add(r, j, "flip")
    return out


def _default_branch(data: dict) -> str | None:
    # The branch most pushes went to: only a fallback, since it picked a busy feature branch in 5 of 56 sampled repos.
    pushes = [r.get("br") for r in data["runs"] if r.get("ev") == "push"]
    return max(sorted(set(pushes)), key=pushes.count) if pushes else None


def default_branches(home: Path, fetch: bool = False) -> dict:
    """Repo -> its default branch as GitHub reports it, kept in <home>/default-branches.json."""
    path = home / "default-branches.json"
    known = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if fetch:
        import httpx
        for d in sorted((home / "ci").iterdir()):
            repo = d.name.replace("__", "/", 1)
            if repo not in known:
                resp = httpx.get(f"https://api.github.com/repos/{repo}", timeout=30,
                                 headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"})
                known[repo] = resp.json().get("default_branch") if resp.status_code == 200 else None
        path.write_text(json.dumps(known, indent=1, sort_keys=True), encoding="utf-8")
    return known


def verdict(item: dict, data: dict, events: dict, main: str | None = None) -> dict:
    runs = {(r["id"], r["att"]): r for r in data["runs"]}
    run = runs.get((item["run"], item["att"])) or {}
    job = next((j for j in data["jobs"] if j["id"] == item["job_id"]), {})
    when = _t(job.get("en")) or _t(run.get("cr"))
    here_tree, here_pr = run.get("tree") or run.get("sha"), set(run.get("pr") or [])
    other = [e for e in events.get((item["workflow"], item["job"]), [])
             if e["tree"] != here_tree and not (set(e["pr"]) & here_pr) and e["br"] != run.get("br")]
    step = item.get("failing_step")
    same_step = [e for e in other if e["step"] == step]
    again = rerun(item, data)
    if again in ("a re-run of the same run passed this job", "another run on the same code passed this job") and same_step:
        before = any(e["at"] and when and e["at"] < when for e in same_step)
        return {"verdict": "not caused", "why": "flaked on other changes before this" if before else "flaked on other changes"}
    # The default branch doesn't hold this change; other pull requests fail for their own reasons, so they don't count.
    main = main or _default_branch(data)
    # Only runs before this failure: once the change merges, the default branch holds it too.
    near = [(r, j) for j in data["jobs"] for r in [runs.get((j["run"], j["att"]))]
            if r and j["run"] != item["run"] and j["n"] == item["job"] and r.get("path") == item["workflow"] and r.get("ev") == "push"
            and r.get("br") == main and when and (t := _t(j.get("en"))) and timedelta(0) <= when - t <= AROUND]
    # "The default branch failed in this step just before" is not counted: 2 of the 28 failures it decided were caused
    # by the change, with a different error in that step (already.py measures the rule that compares the errors).
    if again == "ran again on the same code and failed again" and near and all(j["c"] in PASS for _r, j in near):
        return {"verdict": "caused", "why": f"failed again here; passed on the default branch {len(near)} times just before it"}
    return {"verdict": "undetermined", "why": again}


def _labels_jsonl(path: Path) -> dict:
    return {int(r["id"]): r for r in (json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip())}


def agreement(verdicts: dict, labels: dict) -> dict:
    """How often a labeller's caused_by_change matches the model-free verdicts it can be checked against."""
    want = {"not caused": "no", "caused": "yes"}
    pairs = [(want[v["verdict"]], labels[i]["caused_by_change"]) for i, v in verdicts.items()
             if v["verdict"] in want and i in labels]
    k = sum(a == b for a, b in pairs)
    lo, hi = wilson(k, len(pairs))
    return {"n": len(pairs), "agree": k, "share": round(k / len(pairs), 4) if pairs else None,
            "low": round(lo, 4), "high": round(hi, 4), "unclear": sum(b == "unclear" for _a, b in pairs)}


def masking(home: Path, items: list[dict], gemini: dict, final: Path | None) -> dict:
    """The masking check's failures (jobs that had flaked before) judged from history, and each labeller against it,
    with the rule's own "safe to re-run" calls apart."""
    from masking import SAFE_FLAKES
    asof = [json.loads(x) for x in (home / "asof-items.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    ids = {(i["repo"], int(i["job_id"])): n for n, i in enumerate(items, 1)}
    ids |= {(i["repo"], int(i["job_id"])): 1000 + n for n, i in enumerate(asof, 1)}
    claude = _labels_jsonl(home / "labels.jsonl") | _labels_jsonl(home / "asof-labels.jsonl")
    gem = gemini | {int(r["id"]): r for r in csv.DictReader((HERE / "labels-gemini-masking.csv").open(encoding="utf-8"))}
    fin = (_labels_jsonl(final / "labels.jsonl") | _labels_jsonl(final / "asof-labels.jsonl")) if final else {}
    verdicts, safe, branches = {}, set(), default_branches(home)
    for p in json.loads((home / "masking-pool.json").read_text(encoding="utf-8")):
        data = DataStore(home / "ci" / p["repo"].replace("/", "__")).load()
        it = {"run": int(p["run"]), "att": int(p["att"]), "job_id": int(p["job_id"]), "job": p["job"],
              "workflow": p["workflow"], "failing_step": p["step"]}
        key = ids.get((p["repo"], int(p["job_id"])))
        if key is None:
            continue
        verdicts[key] = verdict(it, data, flakes(data), branches.get(p["repo"]))
        if int(p["flakes"]) >= SAFE_FLAKES and p["step"] in p["flake_steps"]:
            safe.add(key)
    pick = lambda labels, keys: {k: labels[k] for k in keys if k in labels}  # noqa: E731
    out = {"failures": len(verdicts), "by_verdict": dict(defaultdict(int, {v: sum(x["verdict"] == v for x in verdicts.values())
                                                                          for v in ("not caused", "caused", "undetermined")})),
           "new_rule_safe": {str(k): verdicts[k]["verdict"] for k in sorted(safe)}}
    out["labellers"] = {name: agreement(verdicts, labels) for name, labels in
                        (("claude", claude), ("gemini", gem), ("adjudicated", fin)) if labels}
    out["labellers_on_new_rule_safe"] = {name: agreement({k: verdicts[k] for k in safe}, pick(labels, safe))
                                         for name, labels in (("claude", claude), ("gemini", gem)) if labels}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--home", type=Path, required=True)
    ap.add_argument("--final", type=Path, help="work folder with the adjudicated labels.jsonl")
    ap.add_argument("--fetch-branches", action="store_true")
    args = ap.parse_args(argv)
    branches = default_branches(args.home, args.fetch_branches)
    items = [json.loads(x) for x in (args.home / "items.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    items = [i for i in items if i.get("sample") not in (None, "none")]
    cache, verdicts = {}, {}
    for n, it in enumerate(items, 1):
        it = {**it, "run": int(it["run"]), "att": int(it["att"]), "job_id": int(it["job_id"])}
        if it["repo"] not in cache:
            data = DataStore(args.home / "ci" / it["repo"].replace("/", "__")).load()
            cache = {it["repo"]: (data, flakes(data))}
        data, ev = cache[it["repo"]]
        verdicts[n] = {**verdict(it, data, ev, branches.get(it["repo"])), "sample": it["sample"]}
    counts = defaultdict(lambda: defaultdict(int))
    for v in verdicts.values():
        counts[v["sample"]][v["verdict"]] += 1
    gemini = {int(r["id"]): r for r in csv.DictReader((HERE / "labels-gemini-flaky.csv").open(encoding="utf-8"))}
    out = {"items": len(verdicts), "by_sample": {k: dict(v) for k, v in counts.items()},
           "determined": sum(v["verdict"] != "undetermined" for v in verdicts.values()),
           "labellers_against_model_free": {"claude": agreement(verdicts, _labels_jsonl(args.home / "labels.jsonl")),
                                            "gemini": agreement(verdicts, gemini)}}
    if args.final:
        out["labellers_against_model_free"]["adjudicated"] = agreement(verdicts, _labels_jsonl(args.final / "labels.jsonl"))
    out["masking"] = masking(args.home, items, gemini, args.final)
    out["verdicts"] = {str(i): {k: v[k] for k in ("verdict", "why")} for i, v in verdicts.items()}
    (HERE / "natural-results.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "verdicts"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
