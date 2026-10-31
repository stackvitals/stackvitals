"""Test shards that finish together: test files (or classes) split into N groups by their recorded times, from the
newest test reports on the default branch or from report files on this machine."""
import glob
import json
import re
import sys
from pathlib import Path

from stackvitals.ci.api import APIError, OutOfBudget
from stackvitals.ci.collect import TEST_REPORTS
from stackvitals.ci.testreports import parse_archive, parse_report

MAX_BYTES = 50_000_000


def unit(tid: str, py_paths: bool = False) -> str:
    """What a test belongs to: the first part of its id (a file, or a class); py_paths turns a dotted pytest module into
    its file."""
    head = tid.split("::", 1)[0]
    if py_paths and "/" not in head and not head.endswith(".py"):
        parts = head.split(".")
        while len(parts) > 1 and parts[-1][:1].isupper():
            parts.pop()
        head = "/".join(parts) + ".py"
    return head


def split(times: list, n: int, extra=(), py_paths: bool = False) -> list[dict]:
    """[{"files", "ms"}] for n shards: the longest first, each onto the lightest shard. Files with no recorded time count
    as a typical file."""
    totals = {}
    for tid, ms in times:
        u = unit(tid, py_paths)
        if not u or u.startswith("-") or any(c.isspace() for c in u):
            continue  # it would reach the test command as an option ("--co"), so it is never passed on
        totals[u] = totals.get(u, 0) + (ms or 0)
    typical = sorted(totals.values())[len(totals) // 2] if totals else 0
    for f in extra:
        totals.setdefault(f, typical)
    shards = [{"files": [], "ms": 0} for _ in range(max(1, n))]
    for u, ms in sorted(totals.items(), key=lambda x: (-x[1], x[0])):
        s = min(shards, key=lambda s: (s["ms"], len(s["files"])))
        s["files"].append(u)
        s["ms"] += ms
    for s in shards:
        s["files"].sort()
    return shards


def latest_times(api, branch: str, pattern: str = TEST_REPORTS, look: int = 20) -> tuple[list, dict | None]:
    """Every test's time from the newest successful run on `branch` that kept test reports, and that run."""
    # Push runs only: a fork's pull request from its own "main" would otherwise pass for this repo's default branch.
    body = api._get(f"/repos/{api.repo}/actions/runs", {"branch": branch, "event": "push", "status": "success", "per_page": look})
    for run in body.get("workflow_runs") or []:
        arts = [a for a in api.artifacts(run["id"]) if not a.get("expired") and (a.get("size_in_bytes") or 0) <= MAX_BYTES
                and re.search(pattern, a.get("name") or "", re.I)]
        times = []
        for a in arts:
            data = api.download(a["id"])
            try:
                times += parse_archive(data)["all"]
            except Exception:  # an unreadable report is skipped, never the end of the command
                continue
        if times:
            return times, run
    return [], None


def _local(patterns: list[str]) -> list:
    times = []
    for pattern in patterns:
        for name in sorted(glob.glob(pattern, recursive=True)):
            parsed = parse_report(name, Path(name).read_bytes())
            if parsed:
                times += parsed["all"]
    return times


def _dur(ms: int) -> str:
    s = round(ms / 1000)
    return f"{s // 60}m {s % 60:02d}s" if s >= 60 else f"{s}s"


def run(args, make_api, tok: str | None) -> int:
    if args.n < 1 or args.index is not None and not 1 <= args.index <= args.n:
        print("--n must be 1 or more and --index between 1 and --n.", file=sys.stderr)
        return 2
    source = "report files on this machine"
    if args.reports:
        times = _local(args.reports)
    elif args.repo and tok:
        api = make_api(tok, args.repo, max_requests=60)
        try:
            branch = api._get(f"/repos/{args.repo}").get("default_branch") or "main"
            times, found = latest_times(api, branch)
        except (APIError, OutOfBudget) as exc:
            print(f"GitHub refused: {exc}", file=sys.stderr)
            return 1
        source = f"run {found['html_url']}" if found else source
    else:
        print("Give owner/name (with a GitHub token) or --reports 'path/*.xml'.", file=sys.stderr)
        return 2
    if not times:
        print("No test reports with times found (a test report in an artifact whose name says test results).", file=sys.stderr)
        return 1
    extra = sorted({f for pattern in args.files for f in glob.glob(pattern, recursive=True)})
    shards = split(times, args.n, extra, args.py_paths)
    if args.index is not None:
        files = shards[args.index - 1]["files"]
        if not files:
            # An empty argument list makes most test runners run everything, so say so where a person will see it.
            print(f"Shard {args.index} is empty (fewer files than shards): skip the test command in it.", file=sys.stderr)
        print(" ".join(files))
    elif args.json:
        print(json.dumps({"source": source, "tests": len(times), "shards": shards}, indent=1))
    else:
        print(f"{args.n} shards from {len(times)} tests in {sum(len(s['files']) for s in shards)} files ({source}):")
        for k, s in enumerate(shards, 1):
            print(f"Shard {k}, about {_dur(s['ms'])}: {' '.join(s['files'])}")
    return 0
