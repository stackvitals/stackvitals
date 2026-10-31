"""`stackvitals ci upload`: test reports (JUnit, CTRF, Jest or Vitest JSON, go test -json, TRX) from any CI system into
the repo's data branch, as one run with its reports, so flaky-test detection, failure groups and pages work the same as
for GitHub Actions. Needs a token that can write the repo's contents (STACKVITALS_TOKEN or GITHUB_TOKEN)."""
import argparse
import os
import sys
import zlib
from datetime import datetime, timezone
from pathlib import Path

from stackvitals.ci.store import DataStore
from stackvitals.ci.testreports import merge, parse_report
from stackvitals.core.time import iso


def _run_id(provider: str, run_id: str) -> int:
    # Negative, so an uploaded run can never collide with a GitHub Actions run id; stable for the same external run.
    return -(zlib.crc32(f"{provider}:{run_id}".encode("utf-8")) or 1)


def records(paths: list[str], sha: str, branch: str, run_id: str, job: str, event: str, attempt: int, provider: str,
            now: datetime, pr: int | None = None) -> list[dict]:
    """A run, its one job and the merged reports, in the same shapes the Actions collector stores."""
    parts = []
    for path in paths:
        data = Path(path).read_bytes()
        parsed = parse_report(path, data)
        if parsed is None:
            raise ValueError(f"{path} is not a test report StackVitals reads (JUnit, CTRF, Jest/Vitest JSON, go test -json, TRX)")
        parts.append(parsed)
    report = merge(parts)
    rid, stamp = _run_id(provider, run_id), iso(now)
    conclusion = "failure" if report["failed"] else "success"
    run = {"t": "run", "id": rid, "att": attempt, "wf": f"upload:{provider}", "wfn": provider, "path": f"upload:{provider}",
           "ev": event, "br": branch, "sha": sha, "tree": sha, "pr": [pr] if pr else [], "c": conclusion, "cr": stamp,
           "st": stamp, "up": stamp}
    job_rec = {"t": "job", "run": rid, "att": attempt, "id": rid * 1000 - attempt, "n": job, "c": conclusion, "cr": stamp,
               "st": stamp, "en": stamp, "lb": [provider], "steps": []}
    tests = {"t": "tests", "run": rid, "att": attempt, "art": rid * 1000 - attempt, "name": f"{provider}:{job}", **report}
    return [run, job_rec, tests]


def main(argv: list[str] | None = None, env: dict | None = None, now: datetime | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stackvitals ci upload",
                                     description="Add test reports from any CI system to this repo's StackVitals history.")
    parser.add_argument("reports", nargs="+", help="test report files (JUnit, CTRF, Jest/Vitest JSON, go test -json, TRX)")
    parser.add_argument("--sha", required=True, help="commit the tests ran on")
    parser.add_argument("--branch", required=True)
    parser.add_argument("--run-id", default=None, help="the CI system's id for this run (re-runs keep it)")
    parser.add_argument("--attempt", type=int, default=1, help="1 for the first try, 2 for a re-run of the same run")
    parser.add_argument("--job", default="tests")
    parser.add_argument("--event", default="push", choices=["push", "pull_request", "schedule"])
    parser.add_argument("--pr", type=int, default=None)
    parser.add_argument("--provider", default="ci", help="a short name for the CI system (jenkins, gitlab, circleci)")
    parser.add_argument("--repo", default=None, help="owner/name (default: GITHUB_REPOSITORY)")
    args = parser.parse_args(argv)
    env = dict(os.environ if env is None else env)
    now = now or datetime.now(timezone.utc)
    missing = [p for p in args.reports if not Path(p).is_file()]
    if missing:
        print(f"Report not found: {', '.join(missing)}", file=sys.stderr)
        return 2
    try:
        recs = records(args.reports, args.sha, args.branch, args.run_id or args.sha, args.job, args.event, args.attempt,
                       args.provider, now, args.pr)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.repo:
        env["GITHUB_REPOSITORY"] = args.repo
    if not env.get("GITHUB_REPOSITORY") or not (env.get("STACKVITALS_TOKEN") or env.get("GITHUB_TOKEN")
                                                 or env.get("STACKVITALS_REMOTE")):
        print("Give --repo owner/name and a token that can write the repo (STACKVITALS_TOKEN).", file=sys.stderr)
        return 2
    from stackvitals.core.workspace import run_job

    def step(ws):
        DataStore(ws.path).add(recs, now.date().isoformat())
        return None
    job = run_job(env, [("upload", step)], now, message=f"stackvitals: {args.provider} reports {now:%Y-%m-%d %H:%M} UTC",
                  catch=False)
    report = recs[2]
    print(f"Uploaded {report['total']} tests ({len(report['failed'])} failed of {report['total']}) for {args.sha[:12]} on "
          f"{args.branch}: {job['outcome']}.")
    return 0
