"""End-to-end replays: what the pull-request comment and the verdict check would have said on every failed pull-request
attempt, with the history before it only, scored against what happened next on the same code.

    GH_TOKEN=... python bench/accuracy/replay/replay.py read --home <work> --repos pytorch/pytorch ... [--budget 600]
    python bench/accuracy/replay/replay.py pool --home <work> [--home <another work folder>]
    GH_TOKEN=... python bench/accuracy/replay/replay.py fetch --home <work>   # labelling evidence for the re-run calls
    python bench/accuracy/replay/replay.py score --home <work> [--labels <final labels.jsonl>]

read: a busy repo's CI a day at a time, newest first, with the same collector and store as the Action (flaky/wide.py),
until its budget runs out. pool: every failed attempt of a pull-request run, classified by the product's own
`classify_run` on the history before that attempt (no logs: the history-only verdict), and what happened next to each
failed job on the same code (a re-run passed, failed again, or none). fetch: the evidence for each "known flaky" call
that was re-run, for blind labelling. score: counts only, into replay-results.json beside this script.
"""
import argparse
import json
import os
import random
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "flaky"))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[2] / "src"))
import wide  # noqa: E402
from fair import by_repo  # noqa: E402
from sample import Pacer, evidence  # noqa: E402

from stackvitals.ci.analyze import FAIL, PASS, analyze  # noqa: E402
from stackvitals.ci.api import ActionsAPI, APIError, OutOfBudget  # noqa: E402
from stackvitals.ci.feedback import Index, classify_run, verdict_payload  # noqa: E402
from stackvitals.ci.store import DataStore  # noqa: E402
from stackvitals.ci.triggers import PR_EVENTS  # noqa: E402
from stackvitals.core.stats import wilson  # noqa: E402

# Busy public repos on GitHub Actions, monorepos among them (Nx, Bazel-built Angular, Turborepo-built Next.js).
BUSY = ("pytorch/pytorch", "microsoft/vscode", "home-assistant/core", "grafana/grafana", "vercel/next.js",
        "angular/angular", "apache/airflow", "nrwl/nx", "rust-lang/rust", "python/cpython")
MIN_HISTORY_DAYS = 3  # attempts with less history than this before them are left out (every verdict would be "new")


def _t(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.exists() else []


def read(home: Path, repos: list[str], budget: int) -> int:
    import httpx
    token = os.environ["GH_TOKEN"]
    client = httpx.Client(timeout=60, follow_redirects=True, headers={"Authorization": f"Bearer {token}",
                                                                      "Accept": "application/vnd.github+json"})
    pacer, now = Pacer(client), datetime.now(timezone.utc)
    for repo in repos:
        store = DataStore(home / "ci" / repo.replace("/", "__"))
        if store.state().get("wide") == "done":
            continue
        for attempt in range(5):
            try:
                pacer.before()
                got = wide.read(ActionsAPI(token, repo, max_requests=budget), store, now)
                pacer.after()
                break
            except (APIError, OutOfBudget) as exc:
                got = {"skipped": type(exc).__name__}
                break
            except httpx.TransportError:
                time.sleep(60 * (attempt + 1))  # the connection dropped: read this repo again (stored runs are kept)
        else:
            got = {"skipped": "no connection"}
        print(repo, json.dumps(got), flush=True)
    return 0


def _outcome(index: Index, data_runs: dict, run: dict, job: dict) -> tuple[str, float | None]:
    """What ran this job next on the same code, and the hours from this failure to that re-run's start."""
    code = run.get("tree") or run.get("sha")
    ended = _t(job.get("en")) or _t(run.get("up"))
    nxt = []
    for r in index.attempts.get(run["id"], []):
        if r["att"] > run["att"]:
            nxt += [(r, j) for j in index.jobs.get((r["id"], r["att"]), []) if j["n"] == job["n"]]
    if not nxt and code:
        for (rid, att), r in data_runs.items():
            if rid != run["id"] and r.get("path") == run.get("path") and (r.get("tree") or r.get("sha")) == code \
                    and (r.get("st") or "") > (run.get("st") or ""):
                nxt += [(r, j) for j in index.jobs.get((rid, att), []) if j["n"] == job["n"]]
    nxt = [(r, j) for r, j in nxt if j["c"] in PASS or j["c"] in FAIL]
    if not nxt:
        return "not run again", None
    r, j = min(nxt, key=lambda x: x[0].get("st") or "")
    wait = (_t(r.get("st")) - ended).total_seconds() / 3600 if ended and _t(r.get("st")) else None
    return ("passed on re-run" if j["c"] in PASS else "failed again"), wait


def pool(homes: list[Path]) -> list[dict]:
    out = []
    for home in homes:
        for folder in sorted((home / "ci").iterdir()):
            store = DataStore(folder)
            data, state = store.load(), store.state()
            repo, branch, start = folder.name.replace("__", "/", 1), state.get("default_branch"), state.get("covered_from")
            if not start or not data["runs"]:
                continue
            runs = {(r["id"], r["att"]): r for r in data["runs"]}
            full = Index(data, branch)
            first = min(_t(r["st"] or r["cr"]) for r in data["runs"])
            by_st = sorted(data["runs"], key=lambda r: r.get("st") or r["cr"])
            for run in by_st:
                if run.get("ev") not in PR_EVENTS or run.get("c") not in FAIL or (run.get("cr") or "") < start:
                    continue
                when = _t(run.get("st") or run["cr"])
                if (when - first).days < MIN_HISTORY_DAYS:
                    continue
                earlier = {k for k, r in runs.items() if _t(r.get("st") or r["cr"]) < when}
                before = {"runs": [runs[k] for k in earlier], "tests": [],
                          "jobs": [j for j in data["jobs"] if (j["run"], j["att"]) in earlier]}
                result = analyze(before, when, window_days=30, default_branch=branch)
                # This attempt as the newest the Action would have seen: its own jobs, none of its later attempts.
                asof = {"runs": before["runs"] + [run], "tests": [],
                        "jobs": before["jobs"] + [j for j in data["jobs"] if j["run"] == run["id"] and j["att"] == run["att"]]}
                items = classify_run(asof, {**result, "default_branch": branch}, run["id"])
                jobs = {j["id"]: j for j in full.jobs.get((run["id"], run["att"]), [])}
                check = verdict_payload(items, green=False)
                for it in items:
                    job = jobs.get(it.get("job_id"))
                    if not job:
                        continue
                    happened, wait = _outcome(full, runs, run, job)
                    out.append({"repo": repo, "store": str(folder), "run": run["id"], "att": run["att"], "job": job["n"], "job_id": job["id"],
                                "workflow": run.get("path"), "verdict": it["verdict"], "check": check["conclusion"],
                                "check_title": check["output"]["title"], "happened": happened,
                                "wait_h": round(wait, 2) if wait is not None else None,
                                "history_days": (when - first).days})
            print(f"{repo}: {sum(1 for o in out if o['repo'] == repo)} failed jobs replayed", flush=True)
    (homes[0] / "replay-pool.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


BLAMED, SEED = 90, 19


def blamed_sample(rows: list[dict]) -> list[dict]:
    """A seeded random draw of the calls that blamed the change but passed when run again: at most 3 per run, so one pull
    request whose dependency broke 30 jobs can't fill it."""
    rng = random.Random(SEED)
    by_run = defaultdict(list)
    for r in rows:
        if r["verdict"] in ("new", "flaked before") and r["happened"] == "passed on re-run":
            by_run[(r["repo"], r["run"])].append(r)
    pool_ = [x for k in sorted(by_run) for x in rng.sample(by_run[k], min(3, len(by_run[k])))]
    rng.shuffle(pool_)
    return pool_[:BLAMED]


def fetch(home: Path) -> int:  # noqa: C901
    """Evidence for every "known flaky" call that ran again (and the same number of new-failure calls that passed on
    re-run), in the labelling format of the flaky card; the view leaves out every verdict and outcome."""
    import httpx
    token = os.environ["GH_TOKEN"]
    client = httpx.Client(timeout=60, follow_redirects=True, headers={"Authorization": f"Bearer {token}",
                                                                      "Accept": "application/vnd.github+json"})
    pacer = Pacer(client)
    rows = json.loads((home / "replay-pool.json").read_text(encoding="utf-8"))
    # At most 3 calls per job, so no one job's record decides the result.
    per_job = Counter()

    def capped(rs):
        keep = []
        for r in rs:
            per_job[(r["repo"], r["job"], r["verdict"] == "known flaky")] += 1
            if per_job[(r["repo"], r["job"], r["verdict"] == "known flaky")] <= 3:
                keep.append(r)
        return keep
    picked = capped([r for r in rows if r["verdict"] == "known flaky" and r["happened"] != "not run again"])
    picked += blamed_sample(rows)
    done = {(r["repo"], r["job_id"]) for r in _jsonl(home / "items.jsonl")}
    with (home / "items.jsonl").open("a", encoding="utf-8") as f:
        for p in picked:
            if (p["repo"], p["job_id"]) in done:
                continue
            for attempt in range(5):
                try:
                    pacer.before()
                    item = evidence(client, p["repo"], {k: p[k] for k in ("workflow", "job", "run", "att", "job_id")},
                                    DataStore(Path(p["store"])).load())
                    pacer.after()
                    break
                except httpx.TransportError:
                    time.sleep(60 * (attempt + 1))  # the connection dropped: wait and try the same item again
            else:
                raise SystemExit("no connection for 15 minutes; run fetch again to resume")
            f.write(json.dumps({**item, "verdict": p["verdict"], "happened": p["happened"]}) + "\n")
            f.flush()
    _refresh(home, client, pacer)
    items = _jsonl(home / "items.jsonl")
    shown = ("repo", "workflow", "job", "event", "branch", "change", "failing_step", "runner", "files_changed", "log")
    (home / "view.jsonl").write_text("".join(json.dumps({"id": n, **{k: r.get(k) for k in shown}}) + "\n"
                                             for n, r in enumerate(items, 1)), encoding="utf-8")
    print(f"{len(items)} items with evidence; view.jsonl is blind (no verdicts, no outcomes)")
    return 0


def _refresh(home: Path, client, pacer) -> None:
    """Items whose log read hit a dropped connection are read again in place, so their numbers (labels' ids) stay."""
    items = _jsonl(home / "items.jsonl")
    changed = False
    for n, it in enumerate(items):
        if "ConnectError" not in str(it.get("log")) and "ReadTimeout" not in str(it.get("log")):
            continue
        pool_ = {(r["repo"], r["job_id"]): r for r in json.loads((home / "replay-pool.json").read_text(encoding="utf-8"))}
        p = pool_.get((it["repo"], it["job_id"]))
        if not p:
            continue
        pacer.before()
        fresh = evidence(client, p["repo"], {k: p[k] for k in ("workflow", "job", "run", "att", "job_id")},
                         DataStore(Path(p["store"])).load())
        pacer.after()
        items[n] = {**fresh, "verdict": it["verdict"], "happened": it["happened"]}
        changed = True
    if changed:
        (home / "items.jsonl").write_text("".join(json.dumps(r) + "\n" for r in items), encoding="utf-8")


def cross(home: Path, max_calls: int = 40) -> dict:
    """Gemini adjudicates every "caused by the change" disagreement too (the first adjudicator is Claude, the first
    labeller's family), blind like the first; its rulings make a second final label set (cross-labels.jsonl)."""
    from adjudicate import packets
    from crosscheck import ASK, SCHEMA
    from labeller import MODEL, Cache, Gemini, QuotaStop, _hash, _short, codebook, first_labels, load_items, load_key, \
        second_labels
    first = first_labels("replay", home)
    second = second_labels("replay", Cache(home / "gemini-cache", "replay", MODEL, _hash(codebook("replay"))))
    items = {i["id"]: i for i in load_items("replay", home)}
    packs = [p for p in packets(items, first, second, ["caused_by_change"])]
    folder = home / "cross-adjudicate"
    folder.mkdir(exist_ok=True)
    done = {d["id"]: d for f in folder.glob("*.json") for d in [json.loads(f.read_text(encoding="utf-8"))]}
    todo = [p for p in packs if str(p["id"]) not in done]
    if todo:
        gemini, calls = Gemini(load_key(), MODEL, thinking={"thinkingLevel": "minimal"}), 0
        try:
            for n in range(0, len(todo), 4):
                if calls >= max_calls:
                    break
                part = todo[n:n + 4]
                text = "\n".join([ASK] + [json.dumps({"id": str(p["id"]), "field": p["field"], "labels": p["labels"],
                                                      "item": _short(p["item"], 6000)}, ensure_ascii=False) for p in part])
                got, _usage = gemini.generate(codebook("replay"), text, SCHEMA)
                calls += 1
                for g in got:
                    p = next((x for x in part if str(x["id"]) == str(g.get("id"))), None)
                    if p:
                        label = g.get("label") or p["labels"].get(g.get("pick"), "")
                        (folder / f"{p['id']}.json").write_text(json.dumps({"id": str(p["id"]), "label": label}), encoding="utf-8")
                        done[str(p["id"])] = {"label": label}
        except QuotaStop:
            pass
    final = {k: {**v, "caused_by_change": (done.get(str(k)) or {}).get("label", v["caused_by_change"])} for k, v in first.items()}
    (home / "cross-labels.jsonl").write_text("".join(json.dumps({**v, "id": k}) + "\n" for k, v in sorted(final.items())),
                                             encoding="utf-8")
    return {"disagreements": len(packs), "settled": sum(str(p["id"]) in done for p in packs)}


def _rate(k: int, n: int) -> dict:
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "share": round(k / n, 4) if n else None, "low": round(lo, 4), "high": round(hi, 4)}


def score(home: Path, labels: Path | None) -> dict:
    rows = json.loads((home / "replay-pool.json").read_text(encoding="utf-8"))
    by = defaultdict(Counter)
    for r in rows:
        by[r["verdict"]][r["happened"]] += 1
    rerun = [r for r in rows if r["happened"] != "not run again"]
    known = [r for r in rerun if r["verdict"] == "known flaky"]
    blame = [r for r in rerun if r["verdict"] in ("new", "flaked before")]
    waits = lambda rs: [r["wait_h"] for r in rs if r["happened"] == "passed on re-run" and r["wait_h"] is not None]  # noqa: E731
    med = lambda xs: {"n": len(xs), "median_minutes": round(median(xs) * 60) if xs else None}  # noqa: E731
    attempts = defaultdict(list)
    for r in rows:
        attempts[(r["repo"], r["run"], r["att"])].append(r["verdict"])
    out = {"repos": len({r["repo"] for r in rows}), "failed_jobs": len(rows), "attempts": len(attempts),
           # By design, not a finding: the verdict check fails every red attempt, a known flake's too, until a re-run is green.
           "check_passes_red_ci": False, "check_passed_red": sum(1 for r in rows if r["check"] == "success"),
           "by_verdict": {k: dict(v) for k, v in sorted(by.items())},
           "known_flaky_rerun_passed": _rate(sum(r["happened"] == "passed on re-run" for r in known), len(known)),
           "known_flaky_rerun_passed_by_repo": by_repo([(r["repo"], r["happened"] == "passed on re-run") for r in known]),
           "blamed_on_change_rerun_passed": _rate(sum(r["happened"] == "passed on re-run" for r in blame), len(blame)),
           "wait_to_rerun_that_passed": {"all": med(waits(rows)), "known_flaky": med(waits(known))},
           # [automation] rerun_flaky re-runs an attempt only when every failure in it is a known flake.
           "attempts_rerun_flaky_would_rerun": sum(all(v == "known flaky" for v in vs) for vs in attempts.values())}
    if labels:
        items = _jsonl(home / "items.jsonl")
        number = {(it["repo"], it["job_id"]): n for n, it in enumerate(items, 1)}
        sample = {(r["repo"], r["job_id"]) for r in blamed_sample(rows)}
        import csv
        sets = {"first_claude": {int(x["id"]): x for x in _jsonl(home / "labels.jsonl")},
                "second_gemini": {int(x["id"]): x for x in csv.DictReader((HERE / "labels-gemini-replay.csv").open(encoding="utf-8"))},
                "adjudicated_by_claude": {int(x["id"]): x for x in _jsonl(labels)},
                "adjudicated_by_gemini": {int(x["id"]): x for x in _jsonl(home / "cross-labels.jsonl")}}

        def caused(lab: dict, pick) -> dict:
            got = [(it["repo"], lab[n]["caused_by_change"]) for n, it in enumerate(items, 1) if n in lab and pick(it)]
            known_ = [(r, c == "yes") for r, c in got if c in ("yes", "no")]
            return {**_rate(sum(c for _r, c in known_), len(known_)), "unclear": sum(c == "unclear" for _r, c in got),
                    "by_repo": by_repo(known_)}
        groups = {
            # The reviewers' question: a "known flaky" call whose re-run went green, but the change had caused it.
            "known_flaky_green_but_caused": lambda it: it["verdict"] == "known flaky" and it["happened"] == "passed on re-run",
            "known_flaky_failed_again_caused": lambda it: it["verdict"] == "known flaky" and it["happened"] == "failed again",
            # What a re-run lets through anyway, on a seeded random sample capped per run.
            "blamed_green_caused": lambda it: (it["repo"], it["job_id"]) in sample}
        for name, pick in groups.items():
            out[name] = {s: caused(lab, pick) for s, lab in sets.items() if lab}
        out["blamed_sample"] = {"drawn": len(sample), "labelled": sum(k in number for k in sample), "seed": SEED, "per_run": 3}
        out["labelled"] = {"items": len(items), "labellers": "Claude, then Gemini 3.5 Flash-Lite, blind; disagreements "
                                                             "adjudicated blind by Claude and, separately, by Gemini; no person audited"}
    (HERE / "replay-results.json").write_text(json.dumps(out, indent=1, sort_keys=True), encoding="utf-8")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=("read", "pool", "fetch", "cross", "score"))
    ap.add_argument("--home", type=Path, action="append", required=True)
    ap.add_argument("--repos", nargs="*", default=list(BUSY))
    ap.add_argument("--budget", type=int, default=600, help="requests per repo at most (read)")
    ap.add_argument("--labels", type=Path, help="adjudicated labels for the fetched items (score)")
    args = ap.parse_args(argv)
    if args.cmd == "read":
        return read(args.home[0], args.repos, args.budget)
    if args.cmd == "pool":
        rows = pool(args.home)
        print(f"{len(rows)} failed jobs: {dict(Counter((r['verdict'], r['happened']) for r in rows))}")
        return 0
    if args.cmd == "fetch":
        return fetch(args.home[0])
    if args.cmd == "cross":
        print(json.dumps(cross(args.home[0])))
        return 0
    print(json.dumps(score(args.home[0], args.labels), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
