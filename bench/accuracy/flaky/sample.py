"""Draw the flaky-test accuracy sample from public repos, with StackVitals' own collector and detector.

Repos come from the crawl's CI records (at least 20 pushes and 5% of runs re-run), four per language group, seeded.
Each is read the way `stackvitals ci report` reads it (the last 14 days of runs and jobs, at most 250 requests) and
analysed by the same detector. From each repo, at most:
- 5 events the detector flagged as flakes (`flagged`), from its own evidence;
- 3 fail-then-pass re-runs a plain "passed on retry" rule (Trunk, Buildkite, CircleCI) would flag but the detector
  leaves out as part of a wider outage or as a job failing because another one did (`vendor_extra`);
- 3 failures, on pull requests, of jobs that had already flaked (`known_flaky_failure`: is "known flaky" hiding a
  failure the change caused?);
- 3 failures of jobs that never flaked (`unflagged_failure`: what the detector misses).
For each item it keeps the failing job's log excerpt and the files the change touched, for labelling. Log excerpts stay
in the local work folder; `items.csv` beside this script holds only links.

    GH_TOKEN=... python bench/accuracy/flaky/sample.py --home <work folder> [--seed 13]

Paced to at most 1,000 requests an hour and never below 2,000 left on the token.
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

from stackvitals.ci.analyze import FAIL, OUTAGE_MIN_JOBS, OUTAGE_SHARE, PASS, _downstream, _failed_step
from stackvitals.ci.store import DataStore
from stackvitals.core import services

API = "https://api.github.com"
GROUPS = {"TypeScript": "js", "JavaScript": "js", "Python": "python", "Go": "go", "Rust": "rust", "Java": "jvm",
          "Kotlin": "jvm", "C": "c", "C++": "c"}
PER_GROUP, DAYS, BUDGET = 4, 14, 250
TAKE = {"flagged": 5, "vendor_extra": 3, "known_flaky_failure": 3, "unflagged_failure": 3}
HOURLY, FLOOR = 1000, 2000
LOG_CHARS = 6000
STAMP = re.compile(r"^\d{4}-\d\d-\d\dT[\d:.]+Z ")


def frame(records: Path, seed: int, per_group: int = PER_GROUP) -> list[dict]:
    latest = {}
    for path in sorted(records.glob("ci-*.ndjson.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    latest[r["repo"].lower()] = r
    pool = [r for r in latest.values() if r["pushes"] >= 20 and r["rerun_share"] >= 0.05]
    rng = random.Random(seed)
    by_group = {}
    for r in sorted(pool, key=lambda r: r["repo"].lower()):
        by_group.setdefault(GROUPS.get(r.get("language"), "other"), []).append(r)
    chosen = []
    for group, rs in sorted(by_group.items()):
        rng.shuffle(rs)
        chosen += [{"repo": r["repo"], "group": group, "language": r.get("language")} for r in rs[:per_group]]
    return chosen


class Pacer:
    """Keeps this script under HOURLY requests an hour and the token above FLOOR, whoever else uses it."""

    def __init__(self, client: httpx.Client):
        self.client, self.spent = client, []

    def _used(self) -> tuple[int, int, int]:
        core = self.client.get(f"{API}/rate_limit").json()["resources"]["core"]
        return core["used"], core["remaining"], core["reset"]

    def before(self):
        used, remaining, reset = self._used()
        if remaining < FLOOR:
            time.sleep(max(0, reset - time.time()) + 5)
        hour = time.time() - 3600
        self.spent = [(t, n) for t, n in self.spent if t > hour]
        while sum(n for _t, n in self.spent) >= HOURLY:
            time.sleep(60)
            hour = time.time() - 3600
            self.spent = [(t, n) for t, n in self.spent if t > hour]
        self.mark = used

    def after(self):
        used, _remaining, _reset = self._used()
        self.spent.append((time.time(), max(0, used - self.mark)))


def _runs(data: dict) -> dict:
    return {(r["id"], r["att"]): r for r in data["runs"]}


def _by_attempt(data: dict) -> dict:
    out = {}
    for j in data["jobs"]:
        out.setdefault((j["run"], j["att"]), []).append(j)
    return out


def flagged(result: dict) -> list[dict]:
    return [{"sample": "flagged", "workflow": j["workflow"], "job": j["job"], "run": e["run"], "att": e["att"],
             "job_id": e["job"], "kind": e["kind"]} for j in result["jobs"] for e in j.get("evidence") or []]


def vendor_extra(data: dict) -> list[dict]:
    # Fail-then-pass re-runs the detector leaves out: the attempt was part of a wider outage, or the job failed because
    # another job of the attempt already had.
    runs, by_attempt = _runs(data), _by_attempt(data)
    last = {}
    for rid, att in runs:
        last[rid] = max(att, last.get(rid, 0))
    out = []
    for rid, final in last.items():
        seq = {}
        for att in range(1, final + 1):
            jobs = [j for j in by_attempt.get((rid, att), []) if j["c"] in FAIL | PASS]
            outage = len(jobs) >= OUTAGE_MIN_JOBS and sum(j["c"] in FAIL for j in jobs) / len(jobs) >= OUTAGE_SHARE
            for j in jobs:
                seq.setdefault(j["n"], []).append((att, j, outage, jobs))
        for name, items in seq.items():
            fails = [x for x in items if x[1]["c"] in FAIL]
            if not fails or not any(x[1]["c"] in PASS and x[0] > fails[0][0] for x in items):
                continue
            att, job, outage, jobs = fails[0]
            if outage or _downstream(job, jobs):
                out.append({"sample": "vendor_extra", "workflow": runs[(rid, final)].get("path"), "job": name, "run": rid,
                            "att": att, "job_id": job["id"], "why_left_out": "outage" if outage else "downstream"})
    return out


def failures(data: dict, result: dict) -> tuple[list[dict], list[dict]]:
    """(failures on PRs of jobs that had flaked before, failures of jobs that never flaked), final attempts only."""
    runs, by_attempt = _runs(data), _by_attempt(data)
    last = {}
    for rid, att in runs:
        last[rid] = max(att, last.get(rid, 0))
    flaked = {(j["workflow"], j["job"]): sorted(e["run"] for e in j.get("evidence") or []) for j in result["jobs"]}
    known, unflagged = [], []
    for rid, final in last.items():
        run = runs[(rid, final)]
        for j in by_attempt.get((rid, final), []):
            if j["c"] not in FAIL or _downstream(j, by_attempt[(rid, final)]):
                continue
            key = (run.get("path"), j["n"])
            item = {"workflow": key[0], "job": key[1], "run": rid, "att": final, "job_id": j["id"]}
            if flaked.get(key) and run.get("pr") and rid not in flaked[key]:
                known.append({"sample": "known_flaky_failure", **item})
            elif not flaked.get(key):
                unflagged.append({"sample": "unflagged_failure", **item})
    return known, unflagged


def _excerpt(text: str) -> str:
    # The lines leading to the first error, then the log's end, where test runners print which tests failed.
    lines = [STAMP.sub("", x) for x in text.splitlines()]
    whole = "\n".join(lines)
    first = next((i for i, x in enumerate(lines) if "##[error]" in x), None)
    if len(whole) <= LOG_CHARS or first is None:
        return whole[-LOG_CHARS:]
    end = "\n".join(lines[first + 5:])
    if len(end) <= LOG_CHARS // 2:
        return whole[-LOG_CHARS:]
    # Cut each part from the side away from what matters, so the error line itself always stays.
    head = "\n".join(lines[max(0, first - 60):first + 5])[-(LOG_CHARS * 3 // 5):]
    return head + "\n...\n" + end[-(LOG_CHARS - len(head)):]


def evidence(client: httpx.Client, repo: str, item: dict, data: dict) -> dict:
    runs, by_attempt = _runs(data), _by_attempt(data)
    run = runs.get((item["run"], item["att"])) or {}
    job_id = item["job_id"]
    job = next((j for j in by_attempt.get((item["run"], item["att"]), []) if j["id"] == job_id), {})
    try:
        resp = client.get(f"{API}/repos/{repo}/actions/jobs/{job_id}/logs")
        log = _excerpt(resp.text) if resp.status_code == 200 else f"(log unavailable: HTTP {resp.status_code})"
    except httpx.HTTPError as exc:
        log = f"(log unavailable: {type(exc).__name__})"
    files, change = [], None
    prs = run.get("pr") or []
    try:
        if prs:
            change = f"pull request #{prs[0]}"
            resp = client.get(f"{API}/repos/{repo}/pulls/{prs[0]}/files", params={"per_page": 100})
            files = [f["filename"] for f in resp.json()] if resp.status_code == 200 else []
        elif run.get("sha"):
            change = f"commit {run['sha'][:12]}"
            resp = client.get(f"{API}/repos/{repo}/commits/{run['sha']}")
            files = [f["filename"] for f in resp.json().get("files") or []] if resp.status_code == 200 else []
    except (httpx.HTTPError, ValueError):
        files = []
    later = [r for (rid, att), r in runs.items() if rid == item["run"] and att > item["att"]]
    return {**item, "repo": repo, "event": run.get("ev"), "branch": run.get("br"), "sha": run.get("sha"), "change": change,
            "failing_step": _failed_step(job) if job else None, "runner": job.get("lb"), "files_changed": files[:100],
            "rerun_attempts": len(later), "log": log,
            "url": f"https://github.com/{repo}/actions/runs/{item['run']}/job/{job_id}"}


def refresh_logs(home: Path, token: str) -> int:
    """Fetch every drawn item's log again and keep the new excerpt; the items and their order stay as drawn."""
    client = httpx.Client(timeout=60, follow_redirects=True, headers={"Authorization": f"Bearer {token}",
                                                                      "Accept": "application/vnd.github+json"})
    pacer = Pacer(client)
    path, done_path = home / "items.jsonl", home / "refreshed.json"
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    # Progress is kept, so a dropped connection resumes where it stopped.
    done = json.loads(done_path.read_text(encoding="utf-8")) if done_path.exists() else {}
    for n, row in enumerate(rows, 1):
        if not row.get("job_id") or str(row["job_id"]) in done:
            continue
        for wait in (0, 30, 120, 600):
            time.sleep(wait)
            try:
                pacer.before()
                resp = client.get(f"{API}/repos/{row['repo']}/actions/jobs/{row['job_id']}/logs")
                pacer.after()
                break
            except httpx.TransportError:
                resp = None
        if resp is None:
            print(f"item {n}: the network stayed down; run again to resume", flush=True)
            return 1
        done[str(row["job_id"])] = _excerpt(resp.text) if resp.status_code == 200 else f"(log unavailable: HTTP {resp.status_code})"
        done_path.write_text(json.dumps(done), encoding="utf-8")
    for row in rows:
        if row.get("job_id") and str(row["job_id"]) in done:
            row["log"] = done[str(row["job_id"])]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    print(f"{len(done)} logs fetched again", flush=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--records", type=Path, required=True, help="folder of the crawl's ci-YYYY-MM-DD.ndjson.gz files")
    ap.add_argument("--home", type=Path, required=True, help="local work folder (never published)")
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--limit", type=int, default=None, help="read only this many repos (a trial)")
    ap.add_argument("--per-group", type=int, default=PER_GROUP, help="repos per language group (a later pass adds more)")
    ap.add_argument("--refresh-logs", action="store_true", help="fetch the drawn items' logs again (same items, new excerpt)")
    args = ap.parse_args(argv)
    token = os.environ.get("GH_TOKEN")
    if not token:
        print("GH_TOKEN is not set", file=sys.stderr)
        return 1
    if args.refresh_logs:
        return refresh_logs(args.home, token)
    rng = random.Random(args.seed)
    args.home.mkdir(parents=True, exist_ok=True)
    chosen = frame(args.records, args.seed, args.per_group)
    (args.home / "frame.json").write_text(json.dumps(chosen, indent=1), encoding="utf-8")
    client = httpx.Client(timeout=60, follow_redirects=True, headers={"Authorization": f"Bearer {token}",
                                                                      "Accept": "application/vnd.github+json"})
    pacer = Pacer(client)
    done = {json.loads(x)["repo"] for x in (args.home / "items.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()} \
        if (args.home / "items.jsonl").exists() else set()
    now = datetime.now(timezone.utc)
    for r in chosen[: args.limit]:
        repo = r["repo"]
        if repo in done:
            continue
        pacer.before()
        try:
            result, _source = services.ci_result(repo, DAYS, token, args.home, now=now, budget=BUDGET, tests=False)
        except Exception as exc:  # noqa: BLE001 - one repo's trouble never stops the sample
            print(f"{repo}: skipped ({type(exc).__name__})", flush=True)
            pacer.after()
            continue
        pacer.after()
        data = DataStore(args.home / "ci" / repo.replace("/", "__")).load()
        known, unflagged = failures(data, result)
        pools = {"flagged": flagged(result), "vendor_extra": vendor_extra(data), "known_flaky_failure": known,
                 "unflagged_failure": unflagged}
        picked = []
        for name, pool in pools.items():
            rng.shuffle(pool)
            picked += pool[:TAKE[name]]
        pacer.before()
        with (args.home / "items.jsonl").open("a", encoding="utf-8") as f:
            for item in picked:
                f.write(json.dumps({**evidence(client, repo, item, data), "group": r["group"], "language": r["language"]}) + "\n")
            if not picked:
                f.write(json.dumps({"repo": repo, "sample": "none", "group": r["group"]}) + "\n")
        pacer.after()
        print(f"{repo}: {', '.join(f'{k} {len(v)}' for k, v in pools.items())}; kept {len(picked)}", flush=True)
    # Links only for the repo: no log text, no file lists.
    rows = [json.loads(x) for x in (args.home / "items.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    with (Path(__file__).with_name("items.csv")).open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "sample", "repo", "group", "workflow", "job", "event", "url"])
        for i, x in enumerate(r for r in rows if r.get("sample") != "none"):
            w.writerow([i + 1, x["sample"], x["repo"], x["group"], x.get("workflow"), x.get("job"), x.get("event"), x.get("url")])
    print(f"{sum(1 for x in rows if x.get('sample') != 'none')} items written", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
