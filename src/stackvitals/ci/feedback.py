import json
import re
from collections import defaultdict
from importlib import resources
from math import comb
from datetime import timedelta

from stackvitals.ci.analyze import FAIL, _downstream, _failed_step
from stackvitals.ci.api import ActionsAPI, APIError, OutOfBudget
from stackvitals.ci.fingerprint import normalise
from stackvitals.ci.kinds import kind_of
from stackvitals.ci.report import _md, began_text
from stackvitals.ci.triggers import PR_EVENTS
from stackvitals.core.time import parse as _t

MARKER = "<!-- stackvitals:ci -->"
# How often each verdict held on labelled public CI (written by bench/accuracy/summary.py from the accuracy cards).
TRACK_RECORD = json.loads(resources.files("stackvitals.ci").joinpath("track_record.json").read_text(encoding="utf-8"))
KNOWN = {"flaky", "suspect", "fixed"}
LABEL = {"known flaky": "Likely flaky", "outside failure": "Outside failure", "flaked before": "Flaked before",
         "already failing": "Already failing on main", "maybe flaky": "Maybe flaky", "new": "New", "PR details": "PR details",
         "maybe yours": "Maybe yours"}
# An error about the PR itself, from a job that reads it (triggers.py): a PR template, title or label check.
PR_WORDS = re.compile(r"(?i)\bpull request\b|\bPR (?:title|description|body|template|labels?)\b|\badd\b.{0,40}\blabel"
                      r"|\blabels?\b.{0,40}\b(?:required|missing|needed)\b|\bmissing\b.{0,30}\blabels?\b"
                      # A checkbox or template alone is common in code errors; with a PR's wording beside it, it isn't.
                      r"|\b(?:checkbox|checklist|template)\b.{0,80}\b(?:not (?:checked|ticked|filled)|unchecked|incomplete)\b"
                      r"|\b(?:section|description)\b.{0,80}\b(?:checkbox|checklist|template)\b")
PR_DETAIL = ("this job checks the pull request's title, description or labels and runs again when they change: fix them "
             "on the pull request; the code is not the problem and a re-run with the same details fails again")
# A registry, a cache, the network or the runner failing, as job logs say it: on 284 labelled public CI failures, none of
# the 32 whose failing step showed one was caused by the change (bench/accuracy/flaky/outside.py).
OUTSIDE = re.compile(r"(?i)(ENOTFOUND|EAI_AGAIN|ECONNRESET|ECONNREFUSED|ETIMEDOUT|socket hang up|Could not resolve host|"
                     r"Temporary failure in name resolution|Name or service not known|Failed to fetch|"
                     r"Failed to download(?! and build)|\b50[234] (Service Unavailable|Bad Gateway|Gateway Time-?out)|"
                     r"HTTP (error )?50[234]|status code 50[234]|TLS handshake timeout|i/o timeout|"
                     r"Connection (timed out|reset|refused)|ServerBusy|No space left on device|"
                     # Phase 15: curl's connect and timeout codes (not 22, an HTTP error a change can cause), more network
                     # errors; out of memory stays out (on the labels, the one match was the change's).
                     r"curl: \((6|7|28|35|52|56)\)|Network is unreachable|Could not connect to|SSL_ERROR_SYSCALL|"
                     r"Connection reset by peer|"
                     r"runner has received a shutdown signal|lost communication with the server|Cannot connect to the Docker daemon|"
                     r"failed to connect to the docker API|The hosted runner encountered an error|Unable to make request|"
                     r"toomanyrequests|Too Many Requests|secondary rate limit)")
# Safe to re-run needs this many flakes in the window and the failing step among theirs: on labelled public pull requests,
# 15 of 34 failures of jobs that had flaked before were caused by the change; none of those passing this rule were.
SAFE_FLAKES = 3
TEST_STEP = re.compile(r"test|pytest|jest|vitest|mocha|rspec|phpunit|gradle|mvn|maven|ctest|tox|nox|playwright|cypress",
                       re.I)


def _verdict(entry: dict | None) -> str:
    if entry and entry["state"] in KNOWN and entry.get("flake_events", 0) + (entry["state"] == "fixed") > 0:
        return "known flaky"
    if entry and entry["state"] == "broken":
        return "already failing"
    return "new"


# A failing test is never excused, whatever it logged; pytest's "::test FAILED" counts, ninja's "FAILED:" (a build step) doesn't.
TEST_FAILED = re.compile(r"(::\S+ FAILED|FAILED \S+::|--- FAIL|AssertionError|\b\d+ (tests?|specs?|examples?) failed|"
                         r"\b\d+ failed\b|\b\d+ failing\b|Tests:.*\d+ failed|There were failing tests)")


def failing_section(log: str | None) -> str:
    """The failing step's part of a job log: from that step's start to just after the first error (at most 80 lines),
    warnings left out."""
    lines = (log or "").splitlines()
    first = next((i for i, x in enumerate(lines) if "##[error]" in x), len(lines))
    # Logs from the API put a time before every line, so the step's start is looked for after it.
    start = max((i for i in range(max(0, first - 80), first) if LOG_TIME.sub("", lines[i]).startswith("##[group]")),
                default=max(0, first - 80))
    return "\n".join(x for x in lines[start:first + 1] if "##[warning]" not in x)


def outside_signature(log: str | None) -> str | None:
    """The outside failure the failing step's log shows, else None (and None whenever a test failed there)."""
    section = failing_section(log)
    m = OUTSIDE.search(section)
    return m.group(0) if m and not TEST_FAILED.search(section) else None


# How flaky checks fail: a wait or deadline running out, a benchmark gate, a live service inside a test. On labelled
# public CI logs, none of the 25 failures showing one was caused by the change (bench/accuracy/flaky/maybe.py).
FLAKY_LOOK = re.compile(r"(?i)(timed? ?out (after|in|waiting)|timeout of \d+ ?ms exceeded|exceeded (the )?timeout|test timed out|"
                        r"deadline exceeded|TimeoutError|Timeout - Async callback|waiting for .{0,80} timed out|"
                        r"Expected condition failed: waiting for|Matcher did not succeed in time|"
                        r"benchmark.{0,60}(regress|slower|threshold)|performance regression|slower than (the )?baseline|"
                        r"retries \d+ exhausted|retries exhausted|max(imum)? retries (exceeded|reached)|returned HTTP 5\d\d|"
                        r"rate limit|quota exceeded|Service Unavailable)")


def flaky_signature(text: str | None) -> str | None:
    """What in a failing step's log (or a test's message) looks like a flaky check failing, else None."""
    m = FLAKY_LOOK.search(failing_section(text))
    return m.group(0) if m else None


def flake_kind(text: str | None) -> str | None:
    """infrastructure, network, concurrency or timing, from a failing step's log or a test's message; else None."""
    return kind_of(failing_section(text))


def _with_kind(item: dict, text: str | None) -> dict:
    # Only failures already read as flaky say what kind they look like; one likely from the change never does.
    kind = flake_kind(text) if item["verdict"] in ("known flaky", "flaked before", "maybe flaky") else None
    return {**item, "flake": kind, "detail": f"{item['detail']}; looks like a {kind} flake"} if kind else item



MAX_LOGS = 5


def failed_logs(api, data: dict, run_id: int, cache: dict | None = None, index=None) -> dict:
    """The logs of a run's failed jobs in its final attempt (at most five), by job id; read once per run, and skipped
    quietly when GitHub refuses or the budget runs out."""
    cache = {} if cache is None else cache
    if run_id in cache:
        return cache[run_id]
    atts = [r["att"] for r in (index.attempts.get(run_id, []) if index else (r for r in data["runs"] if r["id"] == run_id))]
    out = cache[run_id] = {}
    mine = index.jobs.get((run_id, max(atts)), []) if index and atts else [j for j in data["jobs"] if atts and j["run"] == run_id
                                                                          and j["att"] == max(atts)]
    for j in [j for j in mine if j["c"] in FAIL][:MAX_LOGS]:
        try:
            # Only the failing step's part is kept: that is all the verdict reads.
            out[j["id"]] = failing_section(api._get(f"/repos/{api.repo}/actions/jobs/{j['id']}/logs", raw=True).decode("utf-8", "replace"))
        except APIError as exc:
            if "HTTP 403" in str(exc):
                break  # the token can't read logs here: no point asking for the rest
            continue  # an expired log leaves that job as it was
        except OutOfBudget:
            break
    return out


# A pull request's failure in a step the default branch failed in this soon before was already failing there.
ALREADY_WINDOW = timedelta(days=3)


def _ago(delta: timedelta) -> str:
    hours = round(delta.total_seconds() / 3600)
    return "under an hour" if hours < 1 else f"{hours} hours" if hours < 48 else f"{hours // 24} days"


class Index:
    """One pass over the stored history, shared by every run a job classifies: runs, jobs and reports by run, and the
    default branch's failed jobs and tests (a busy repo's 180 days hold hundreds of thousands of jobs)."""

    def __init__(self, data: dict, default_branch: str | None):
        self.branch = default_branch
        self.attempts, self.jobs, self.reports = defaultdict(list), defaultdict(list), defaultdict(list)
        runs = {}
        for r in data.get("runs") or []:
            runs[(r["id"], r["att"])] = r
            self.attempts[r["id"]].append(r)
        for j in data.get("jobs") or []:
            self.jobs[(j["run"], j["att"])].append(j)
        for t in data.get("tests") or []:
            self.reports[(t["run"], t["att"])].append(t)
        # Every attempt of each pull request's runs, to compare how often a check fails there with its rate on main.
        self.runs, self.pr_attempts = runs, defaultdict(set)
        for key, r in runs.items():
            for p in r.get("pr") or ():
                self.pr_attempts[p].add(key)
        on_main = lambda r: r is not None and r.get("ev") == "push" and default_branch and r.get("br") == default_branch  # noqa: E731
        self.main_jobs, self.main_tests = defaultdict(list), defaultdict(list)
        for (rid, att), js in self.jobs.items():
            r = runs.get((rid, att))
            if on_main(r):
                for j in js:
                    if j["c"] in FAIL and (t := _t(j.get("en"))):
                        self.main_jobs[(r.get("path"), j["n"], _failed_step(j))].append((t, rid, j["id"]))
        for (rid, att), reps in self.reports.items():
            r = runs.get((rid, att))
            if on_main(r) and (t := _t(r.get("cr"))):
                for rep in reps:
                    for f in rep["failed"]:
                        self.main_tests[f[0]].append((t, rid, f[1], f[2]))


def _on_default(run: dict, branch: str) -> bool:
    # A pull request from a fork's "main" is still a pull request, never the default branch.
    return run.get("br") == branch and run.get("ev") not in PR_EVENTS


def failed_on_default(data: dict, run: dict, job: dict, step: str, default_branch: str | None,
                      index: Index | None = None) -> dict | None:
    """The newest default-branch push run whose same job failed in this step in the 3 days before this job ended."""
    when = _t(job.get("en")) or _t(run.get("cr"))
    if not default_branch or not when or _on_default(run, default_branch):
        return None
    index = index or Index(data, default_branch)
    found = None
    for t, rid, jid in index.main_jobs.get((run.get("path"), job["n"], step), ()):
        if rid != run["id"] and timedelta(0) <= when - t <= ALREADY_WINDOW and (found is None or t > found["t"]):
            found = {"run": rid, "job": jid, "t": t, "ago": _ago(when - t)}
    return found


def _tests_failed_on_default(index: Index, run: dict, tids) -> dict:
    """Test id -> the newest default-branch push run that failed it in the 3 days before this run, for these tests."""
    when = _t(run.get("cr"))
    if not index.branch or not when or _on_default(run, index.branch):
        return {}
    out = {}
    for tid in tids:
        for t, rid, fp, msg in index.main_tests.get(tid, ()):
            if rid != run["id"] and timedelta(0) <= when - t <= ALREADY_WINDOW and (tid not in out or t > out[tid]["t"]):
                out[tid] = {"run": rid, "t": t, "ago": _ago(when - t), "fp": fp, "msg": msg}
    return out


def _same_test_failure(f: list, before: dict) -> bool:
    # The fingerprint when both have one, else the message without what changes between runs.
    if f[1] and before["fp"]:
        return f[1] == before["fp"]
    return normalise(f[2]) == normalise(before["msg"])


LOG_ERROR = re.compile(r"(?i)##\[error\]|\berror\b|\bfail|panic|exception|assert|timeout|timed out")
LOG_TIME = re.compile(r"^\d{4}-\d\d-\d\dT[\d:.]+Z ")
# Summary lines every failing run of a tool prints: shared by any two failures, so they never count as the same error.
BOILERPLATE = re.compile(r"(?i)^\s*(##\[error\])?\s*(Test Suites:|Tests:|Snapshots:|Time:|Ran all test suites|"
                         r"npm ERR! (Failed at|code|errno|A complete log|This is probably|Test failed|lifecycle)|"
                         r"ELIFECYCLE|error Command failed with exit code|Command failed with exit code|"
                         r"make(\[\d+\])?: \*\*\*|Error: Process completed with exit code|=+ .*\b\d+ failed\b.* =+$|"
                         r"FAILED\s*$|ERROR: Job failed|error: Recipe .* failed)")
# On 24 labelled pull-request failures in a step the default branch had just failed in, the 15 sharing at least 2 of
# every 3 error lines with it were all not caused by the change; the 4 the change caused shared a third or less.
SAME_ERROR = 0.6


def error_lines(section: str | None) -> set:
    """A failing step's error lines without what changes between runs (times, ids, paths, numbers)."""
    lines = {normalise(LOG_TIME.sub("", x)) for x in (section or "").splitlines()
             if LOG_ERROR.search(x) and "Process completed with exit code" not in x
             and not BOILERPLATE.search(LOG_TIME.sub("", x))}
    lines.discard("")
    return lines


def error_excerpt(section: str | None, limit: int = 5) -> list[str]:
    """A failing step's error lines as the log printed them (times cut), for an agent to read instead of the whole log."""
    return [LOG_TIME.sub("", x).strip()[:200] for x in (section or "").splitlines()
            if LOG_ERROR.search(x) and "Process completed with exit code" not in x][:limit]


def same_error(log: str | None, other: str | None) -> bool:
    """Whether most of this failure's error lines appear in the other failure's too."""
    mine = error_lines(log)
    return bool(mine) and len(mine & error_lines(other)) / len(mine) >= SAME_ERROR


def _job_verdict(entry: dict | None, step: str) -> str:
    """A job's verdict from history alone: known flaky only when it flaked often enough and in the step that failed now
    (classify_run then asks the log and the pull request's files too)."""
    verdict = _verdict(entry)
    if verdict == "known flaky" and (entry["flake_events"] < SAFE_FLAKES or step not in (entry.get("flake_steps") or ())):
        return "flaked before"
    return verdict


def _test_verdict(entry: dict | None) -> str:
    """A test's verdict from history alone: known flaky only when it flaked as often as a job must (the test is its own step)."""
    verdict = _verdict(entry)
    return "flaked before" if verdict == "known flaky" and entry["flake_events"] < SAFE_FLAKES else verdict


def named_files(text: str | None, files) -> list[str]:
    """The pull request's changed files that this text names: by file name, or by a stem of 8+ characters as a word;
    stems under 5 characters (main, util, index) never count."""
    out = []
    for f in files or ():
        base = f.rsplit("/", 1)[-1]
        stem = base.rsplit(".", 1)[0]
        if len(stem) >= 5 and base not in out and (base in (text or "") or (
                len(stem) >= 8 and re.search(r"\b" + re.escape(stem) + r"\b", text or ""))):
            out.append(base)
    return out


def flake_sign(text: str | None) -> str | None:
    """What in a failing step's log (or a test's message) shows a flake: an outside service or the runner failing, or a
    wait or live service running out, and never with a failing test beside it."""
    section = failing_section(text)
    if not section.strip() or TEST_FAILED.search(section):
        return None
    m = OUTSIDE.search(section) or FLAKY_LOOK.search(section)
    return m.group(0) if m else None


def _files_text(files) -> str:
    n = len(files)
    return f"{n} file{'' if n == 1 else 's'}"


def _sharpen(verdict: str, text: str | None, changed: list | None, name: str = "") -> tuple[str, str | None, list]:
    """History's "known flaky" or "flaked before", checked against the log and the pull request's files (pre-registered
    2026-10-28, bench/accuracy/flaky/README.md): known flaky only with a flake's sign and no changed file named; a
    changed file named makes it "maybe yours". Returns the verdict, the sign and the files named."""
    if verdict not in ("known flaky", "flaked before"):
        return verdict, None, []
    named = named_files(f"{name}\n{failing_section(text)}", changed)
    if named:
        return "maybe yours", None, named
    sign = flake_sign(text)
    if verdict == "known flaky" and not sign:
        return "flaked before", None, []
    return verdict, sign, []


def _only_here(entry: dict | None, run: dict, verdict: str) -> str | None:
    """A flaky-looking verdict whose flakes all came from this pull request: the change's own (a race it added), so it
    reads "new". Returns the detail then, else None."""
    if verdict not in ("known flaky", "flaked before", "maybe flaky") or not entry or not entry.get("flake_events"):
        return None
    if entry.get("only_pr") is None or entry["only_pr"] not in (run.get("pr") or ()):
        return None
    times = "once" if entry["flake_events"] == 1 else f"{entry['flake_events']} times"
    return (f"flaked {times} in the last 30 days, all of them only on this pull request and nowhere else: likely a race "
            "or order dependence this change added; look at the change before re-running")


# Main runs a check must have passed, all of them, for a first flaky-looking failure on a pull request to be worth a look.
STABLE_MAIN = 20
# A likely flake reads new when this pull request's failures would come from its main rate less than 5% of the time,
# with at least 2 failures and 10 main runs to judge by (one failure can't tell a 5% flake from a 40% one).
WORSE_P, WORSE_MIN_FAILS, WORSE_MIN_MAIN = 0.05, 2, 10


def _pr_record(index: Index, run: dict, path: str | None = None, job: str | None = None, suite: str | None = None,
               test: str | None = None) -> tuple[int, int]:
    """(failed, ran): how many attempts of this pull request's runs failed this job or test, out of those that ran it."""
    keys = set().union(*(index.pr_attempts.get(p, set()) for p in run.get("pr") or ()))
    failed = ran = 0
    for key in keys:
        if test:
            reps = [r for r in index.reports.get(key, ()) if r["name"] == suite]
            if reps:
                ran += 1
                failed += any(f[0] == test for r in reps for f in r["failed"])
        elif index.runs[key].get("path") == path:
            js = [j for j in index.jobs.get(key, ()) if j["n"] == job and (j["c"] in FAIL or j["c"] == "success")]
            if js:
                ran += 1
                failed += any(j["c"] in FAIL for j in js)
    return failed, ran


def _tail(k: int, n: int, p: float) -> float:
    """The chance of k or more failures in n runs at failure rate p."""
    return sum(comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1))


def _main_record(item: dict, entry: dict | None, here: tuple[int, int] | None = None) -> dict:
    """The check's record on the default branch beside a flaky-looking verdict: a likely flake shows how often it fails
    there; a "maybe flaky" check that passed every recent run there says so (still maybe flaky: never-flaked timeouts were
    mostly real flakes on the labels), and a green re-run of it is flagged later."""
    n = (entry or {}).get("main_runs") or 0
    if item["verdict"] == "known flaky" and n:
        # A change can make a flaky check fail far more often: its rate on main lets a reviewer compare.
        bad = (entry or {}).get("main_failures") or 0
        k, ran = here or (0, 0)
        # The main rate is smoothed (one failure and one pass added) so a clean main never makes one failure damning.
        if k >= WORSE_MIN_FAILS and n >= WORSE_MIN_MAIN and _tail(k, ran, (bad + 1) / (n + 2)) < WORSE_P:
            return item | {"verdict": "new", "detail": f"flaky, but it failed {k} of {ran} runs on this pull request against "
                           f"{bad} of {n} ({bad / n:.0%}) on the default branch in the last 30 days: this change likely "
                           "made it fail more often; look at the change before re-running"}
        return item | {"detail": item["detail"] + f"; on the default branch it failed {bad} of {n} runs ({bad / n:.0%}) "
                       "in the last 30 days: if it fails here more often than that, this change may have made it worse"}
    if item["verdict"] != "maybe flaky" or n < STABLE_MAIN or (entry or {}).get("main_failures"):
        return item
    return item | {"stable_on_main": n, "detail": item["detail"] + f"; it passed all {n} runs on the default branch in the "
                   "last 30 days, so if a re-run passes, look for a race this change added"}


def _detail(entry: dict | None, verdict: str, message: str | None = None, step: str | None = None,
            kind: str = "job", hint: str | None = None, sign: str | None = None, named: list | None = None,
            changed: list | None = None) -> str:
    times = ("once" if entry["flake_events"] == 1 else f"{entry['flake_events']} times") if entry else ""
    if verdict == "maybe yours":
        shown = ", ".join(named[:3]) + (f" and {len(named) - 3} more" if len(named) > 3 else "")
        return (f"the error names {shown}, which this pull request changed: likely this change, though it "
                + (f"flaked {times} in {entry['runs']} runs in the last 30 days" if entry and entry["flake_events"]
                   else "was flaky until a recent fix") + "; look at the change before re-running")
    if verdict == "known flaky":
        last = (entry.get("last_flake") or "")[:10]
        began = entry.get("began") or {}
        files = f"; the error names none of the {_files_text(changed)} this pull request changed" if changed else ""
        return (f"flaked {times} in {entry['runs']} runs in the last 30 days" + (f", last {last}" if last else "")
                + (" in this step" if kind == "job" else "")
                + f", and the {'message' if kind == 'test' else 'log'} shows a flake's sign (\"{sign}\"): looks like a flake, "
                "check the error, then re-run it" + files + (f"; it {began_text(began)}" if began.get("clear") else ""))
    if verdict == "flaked before" and not entry["flake_events"]:
        return "flaky until a recent fix, with no flakes in the last 30 days: check whether this change caused it"
    if verdict == "flaked before" and entry["flake_events"] >= SAFE_FLAKES and (kind == "test" or step in (entry.get("flake_steps") or ())):
        # Often enough to look like a known flake, but nothing in this failure shows a flake.
        return (f"flaked {times} in {entry['runs']} runs in the last 30 days" + (" in this step" if kind == "job" else "")
                + f", but this failure {'message' if kind == 'test' else 'log'} shows no sign of a flake (an outside service, "
                "the runner or a wait failing): check whether this change caused it")
    if verdict == "flaked before" and kind == "test":
        return (f"flaked {times} in {entry['runs']} runs in the last 30 days, too few to call it a known flake: "
                "check whether this change caused it")
    if verdict == "flaked before":
        where = ", ".join(entry.get("flake_steps") or []) or "an unknown step"
        return (f"flaked {times} in {entry['runs']} runs in the last 30 days, in {where}; this time in {step or 'an unknown step'}: "
                "check whether this change caused it")
    if verdict == "already failing":
        return "also failing on the default branch, not caused by this change"
    if verdict == "maybe flaky":
        return (f"no earlier flakes, but it failed the way flaky checks often do (\"{hint}\"): re-run it once to tell; "
                "if it fails again, look at this change")
    return f"no earlier flakes: likely from this change" + (f" (fails with \"{message}\")" if message else "")


def classify_run(data: dict, result: dict, run_id: int, logs: dict | None = None, index: Index | None = None,
                 changed: list | None = None) -> list[dict]:
    """What failed in the final attempt of one run, and whether history says it's flaky, broken or new; with the failed
    jobs' logs (by job id), a new failure whose log shows an outside service or the runner failing says so, one that
    failed the way flaky checks do reads "maybe flaky", and one with the same error as the default branch just before
    reads "already failing". A known flake also needs a flake's sign in its log and no file the pull request changed
    (`changed`) named there; one naming such a file reads "maybe yours". Pass the same `index` for every run of one history."""
    main = result.get("default_branch")
    index = index or Index(data, main)
    atts = index.attempts.get(run_id)
    if not atts:
        return []
    run = max(atts, key=lambda r: r["att"])
    jobs = index.jobs.get((run_id, run["att"]), [])
    reports = index.reports.get((run_id, run["att"]), [])
    job_state = {(j["workflow"], j["job"]): j for j in result.get("jobs", [])}
    test_state = {t["id"]: t for t in result.get("tests", [])}
    groups = {g["id"]: g for g in result.get("failure_groups") or []}
    pr_edits = set(result.get("pr_edit_workflows") or ())
    on_main = _tests_failed_on_default(index, run, {f[0] for r in reports for f in r["failed"]}) if reports else {}
    items = []
    for r in reports:
        for f in r["failed"]:
            tid, msg = f[0], f[2]
            entry = test_state.get(tid)
            verdict, sign, named = _sharpen(_test_verdict(entry), msg, changed, name=tid)
            hint = flaky_signature(msg) if verdict == "new" else None
            verdict = "maybe flaky" if hint else verdict
            here = _only_here(entry, run, verdict)
            verdict = "new" if here else verdict
            item = _with_kind({"kind": "test", "name": tid, "verdict": verdict,
                               "detail": here or _detail(entry, verdict, msg, kind="test", hint=hint, sign=sign, named=named,
                                                         changed=changed)}, msg)
            item = _main_record(item, entry, _pr_record(index, run, suite=(entry or {}).get("suite"), test=tid)
                                if item["verdict"] == "known flaky" else None)
            before = on_main.get(tid) if verdict in ("new", "flaked before", "maybe flaky", "maybe yours") else None
            if before and _same_test_failure(f, before):
                item |= {"verdict": "already failing", "detail": f"failed the same way on the default branch {before['ago']} "
                         f"before this (run {before['run']}): not caused by this change"}
            elif before:
                item["detail"] += f"; it failed differently on the default branch {before['ago']} before this (run {before['run']})"
            if r.get("seed") and item["verdict"] != "already failing":
                item["detail"] += f"; the tests ran in random order, seed {r['seed']}: replay with it"
            group = groups.get(f[3]) if len(f) > 3 else None
            if group and group["tests"] > 1:
                # Many tests failing the same way usually share one cause: say so, so nobody fixes them one by one.
                item["group"] = {k: group[k] for k in ("id", "tests", "runs", "where", "type", "first")}
                item["detail"] += f"; same failure in {group['tests']} tests since {group['first'][:10]}"
            items.append(item)
    tests_failed = any(r["failed"] for r in reports)
    for j in jobs:
        if j["c"] not in FAIL or _downstream(j, jobs):
            continue
        base = {"kind": "job", "job_id": j["id"], "name": f"{run.get('wfn') or 'CI'} / {j['n']}"}
        mine = (logs or {}).get(j["id"])
        # Checked first: label edits look like flakes in a history that didn't know the job reads the PR. A job gated
        # on labels by `if:` or reading the PR in a script is found by its workflow and an error about the PR.
        section = failing_section(mine) if run.get("path") in pr_edits else ""
        if (run.get("ev") in PR_EVENTS and section and not TEST_FAILED.search(section)
                and any(PR_WORDS.search(x) for x in error_excerpt(section))):
            items.append({**base, "verdict": "PR details", "detail": PR_DETAIL})
            continue
        entry = job_state.get((run.get("path"), j["n"]))
        failing_step = _failed_step(j)
        verdict, sign, named = _sharpen(_job_verdict(entry, failing_step), mine, changed)
        # A job that failed with failing tests is explained by its tests, unless the job itself is known;
        # a known flaky job whose test step failed is explained by its tests too, so it is never called a known flake.
        if tests_failed and (verdict in ("new", "flaked before", "maybe yours")
                             or (verdict == "known flaky" and TEST_STEP.search(failing_step))):
            continue
        before = (failed_on_default(data, run, j, failing_step, main, index)
                  if verdict in ("new", "flaked before", "maybe yours") else None)
        theirs = (logs or {}).get(before["job"]) if before else None
        if before and same_error(mine, theirs):
            items.append({**base, "verdict": "already failing",
                          "detail": f"the same error as on the default branch {before['ago']} before this (run "
                                    f"{before['run']}), in this step: not caused by this change"})
            continue
        seen = outside_signature(mine) if verdict in ("new", "flaked before") else None
        if seen:
            items.append({**base, "verdict": "outside failure",
                          "detail": f"the log shows an outside service or the runner failing (\"{seen}\"): likely not this "
                                    "change; re-run it"})
            continue
        hint = flaky_signature(mine) if verdict == "new" else None
        verdict = "maybe flaky" if hint else verdict
        here = _only_here(entry, run, verdict)
        verdict = "new" if here else verdict
        item = _with_kind({**base, "verdict": verdict, "detail": here or _detail(entry, verdict, step=failing_step, hint=hint,
                                                                                 sign=sign, named=named, changed=changed)}, mine)
        item = _main_record(item, entry, _pr_record(index, run, path=run.get("path"), job=j["n"])
                            if item["verdict"] == "known flaky" else None)
        if before:
            item["detail"] += (f"; the default branch failed in this step {before['ago']} before this (run {before['run']})"
                               + (", with a different error" if mine and theirs else ""))
            if mine and not theirs:
                item["main_job"] = before["job"]  # classify() reads that log and asks again
        items.append(item)
    return items


def pr_files(api, index: Index, run_id: int, cache: dict) -> list | None:
    """The files the run's pull request changes (first 100, one request, read once per pull request); None when the run
    has no pull request or GitHub refuses."""
    atts = index.attempts.get(run_id) or []
    prs = max(atts, key=lambda r: r["att"]).get("pr") if atts else None
    if not prs:
        return None
    key = ("pr_files", prs[0])
    if key not in cache:
        try:
            got = api._get(f"/repos/{api.repo}/pulls/{prs[0]}/files", {"per_page": 100}) or []
            cache[key] = [f["filename"] for f in got if isinstance(f, dict) and f.get("filename")]
        except (APIError, OutOfBudget):
            cache[key] = None
    return cache[key]


def _job_log(api, job_id: int) -> str | None:
    try:
        return failing_section(api._get(f"/repos/{api.repo}/actions/jobs/{job_id}/logs", raw=True).decode("utf-8", "replace"))
    except (APIError, OutOfBudget):
        return None


def classify(api, data: dict, result: dict, run_id: int, cache: dict | None = None) -> list[dict]:
    """classify_run with the failed jobs' logs, read once per run (the cache is shared across a job's calls), and the
    log of a default-branch failure in the same step just before, read once, to tell the same error from a new one."""
    cache = {} if cache is None else cache
    main = result.get("default_branch")
    # Built once per history and reused for every run this job classifies.
    key = ("index", id(data), main, len(data.get("jobs") or []))
    index = cache.get(key) or cache.setdefault(key, Index(data, main))
    logs = failed_logs(api, data, run_id, cache, index)
    items = classify_run(data, result, run_id, logs=logs, index=index)
    # The pull request's files matter only to failures that flaked before: read them only then.
    changed = pr_files(api, index, run_id, cache) if any(i["verdict"] in ("known flaky", "flaked before") for i in items) else None
    if changed:
        items = classify_run(data, result, run_id, logs=logs, index=index, changed=changed)
    wanted = [i["main_job"] for i in items if i.get("main_job")]
    if wanted:
        known = cache.setdefault("default_branch_logs", {})
        for jid in wanted[:MAX_LOGS]:
            if jid not in known:
                known[jid] = _job_log(api, jid)
        items = classify_run(data, result, run_id, logs=logs | {k: v for k, v in known.items() if v}, index=index,
                             changed=changed)
    for i in items:
        i.pop("main_job", None)
    return items


def _quiet(text) -> str:
    # Text from logs, reports or a model: no @-mention that pings someone, no bare link that opens elsewhere.
    text = re.sub(r"(?i)\b(https?):(?=//)", lambda m: m[1] + ":​", str(text))
    return text.replace("@", "@​").replace("www.", "www​.")


def _code(text) -> str:
    # Inside a code span a backslash escapes nothing: a backtick becomes a quote; a pipe stays escaped for the table.
    return _quiet(str(text).replace("`", "'").replace("|", "\\|"))


def failure_summary(items: list[dict]) -> str:
    """One line on what to do about a failed run, for an agent (MCP ci_failure)."""
    verdicts = {i["verdict"] for i in items}
    if not verdicts:
        return "nothing failed that StackVitals could classify"
    if verdicts == {"known flaky"}:
        return "every failure looks like a known flake (it flaked before and its log shows a flake's sign): check the errors, then re-run the failed jobs"
    if verdicts == {"PR details"}:
        return "only checks on the pull request's title, description or labels failed: fix those, not the code"
    if verdicts & {"new", "flaked before", "maybe yours"}:
        return "some failures may be the change's: look at the ones marked new, maybe yours or flaked before first"
    return ("no failure points at the change: " + "; ".join(
        {"outside failure": "outside ones need a re-run", "already failing": "already failing ones fail on the default "
         "branch too", "maybe flaky": "maybe flaky ones need one re-run to tell", "known flaky": "known flakes need a "
         "look at the error, then a re-run", "PR details": "PR checks need the PR's details fixed"}.get(v, v)
        for v in sorted(verdicts)))


# Verdicts that blame the change: in strict mode a green re-run of the same code needs a person to accept it.
BLAMED = {"new", "flaked before", "maybe yours"}
BLAMED_NOTE = re.compile(r"<!-- stackvitals:blamed ([0-9a-f]{7,40}) -->")


def blamed_sha(body: str | None) -> str | None:
    """The commit our comment last blamed on the change, if any."""
    m = BLAMED_NOTE.search(body or "")
    return m[1] if m else None


def green_note(body: str | None, sha: str) -> str:
    """Our comment once CI turns green: a warning, without blocking, when the failure it replaces on this same commit
    looked like the change's own or failed a check main always passes (a race a change adds passes on a re-run)."""
    if blamed_sha(body) != sha:
        return f"{MARKER}\n### StackVitals: CI is passing now\nThe latest run passed."
    return (f"{MARKER}\n### StackVitals: a re-run turned this green\nA failure on this commit looked like the change's own, or "
            "failed a check that passes on the default branch every time, and passed when run again. That is how a race or "
            "order dependence a change adds usually shows up: look at it before merging.\n<!-- stackvitals:blamed " + sha + " -->")


def render_comment(items: list[dict], repo: str, sha: str | None = None) -> str:
    known = sum(i["verdict"] == "known flaky" for i in items)
    outside = sum(i["verdict"] == "outside failure" for i in items)
    # Never "safe": held out, no rule here kept the change's own failures under 5% (bench/accuracy/flaky, 2026-10-28).
    kinds = "flakes or outside failures" if outside else "flakes"
    if items and known + outside == len(items):
        head = (f"All {len(items)} failure(s) look like {kinds}: check the errors, then re-run them. "
                "The StackVitals verdict passes once CI is green.")
    elif known + outside:
        head = f"{known + outside} of {len(items)} failure(s) look like {kinds}; the rest need a look."
    else:
        head = "None of these failures look like known flakes."
    if any(i["verdict"] == "PR details" for i in items):
        head += " Fix the pull request's details (title, description or labels) for the PR checks; their jobs run again on their own."
    # One short row per failure; the evidence behind it and how often each verdict has held are folded below.
    shown = items[:MAX_ROWS]
    parts = [_clauses(i["detail"]) for i in shown]
    rows = [f"| {LABEL[i['verdict']]} | {i['kind']} `{_code(i['name'])}` | {_quiet(_md(p[0]))} |" for i, p in zip(shown, parts)]
    more = [f"... and {len(items) - MAX_ROWS} more."] if len(items) > MAX_ROWS else []
    evidence = [f"- {LABEL[i['verdict']]} {i['kind']} `{_code(i['name'])}`: {_quiet(_md('; '.join(p[1:])))}"
                for i, p in zip(shown, parts) if len(p) > 1]
    held = [f"- {LABEL.get(v, v)}: {TRACK_RECORD[v]}" for v in dict.fromkeys(i["verdict"] for i in shown) if v in TRACK_RECORD]
    if any(i.get("model") for i in shown):
        held.append(f"- A model's view: {TRACK_RECORD['model']}")
    folded = ["<details><summary>Evidence, and how often these verdicts have held</summary>", "", *evidence,
              *([""] if evidence else []), "On labelled public CI failures:", *held, "", "</details>", ""]
    views = {str(i["job_id"]): i["model"] for i in items if i.get("model") and i.get("job_id")}
    if views:
        # A dash only ever sits inside a JSON string here, so escaping it keeps any "-->" from closing the note.
        folded.append("<!-- stackvitals:triage " + json.dumps(views, ensure_ascii=True).replace("-", "\\u002d") + " -->")
    if sha and re.fullmatch(r"[0-9a-f]{7,40}", sha) and any(i["verdict"] in BLAMED or i.get("stable_on_main") for i in items):
        folded.append(f"<!-- stackvitals:blamed {sha} -->")
    return "\n".join([MARKER, "### StackVitals: about this CI failure", head, "",
                      "| Verdict | What failed | Why |", "|---|---|---|", *rows, *more, "", *folded,
                      f"<sub>From the CI history kept in {_md(repo)}'s stackvitals-data branch.</sub>"])


MAX_ROWS = 25


def _clauses(detail: str) -> list[str]:
    """A detail's clauses, split at "; " outside quotes, so a quoted error message is never cut."""
    out, start, quoted = [], 0, False
    for i, ch in enumerate(detail):
        if ch == '"':
            quoted = not quoted
        elif not quoted and detail.startswith("; ", i):
            out.append(detail[start:i])
            start = i + 2
    return out + [detail[start:]]


def quarantined_failures(data: dict, run_ids, quarantined: set | None) -> list[str]:
    """Quarantined tests that failed in the final attempt of these runs: they passed CI only by being let through."""
    if not quarantined:
        return []
    final = {}
    for r in data.get("runs") or []:
        if r["id"] in set(run_ids):
            final[r["id"]] = max(final.get(r["id"], 0), r["att"])
    failed = {f[0] for t in data.get("tests") or [] if final.get(t["run"]) == t["att"] for f in t["failed"]}
    return sorted(failed & set(quarantined))


LONG_QUARANTINE_DAYS = 30


def quarantine_note(tests: list[str], repo: str, result: dict | None = None, now=None) -> str:
    """Says which quarantined tests were let through; with the CI result, how long each has been flaky and who owns it,
    so a test left in quarantine for weeks gets noticed (owners are named without pinging them)."""
    known = {t["id"]: t for t in (result or {}).get("tests") or []}
    rows, old = [], []
    for tid in tests[:10]:
        t, extra = known.get(tid) or {}, []
        since = _t(t.get("since")) if t.get("since") else None
        if since and now:
            days = (now - since).days
            extra.append(f"flaky since {since.date().isoformat()}, {days} days")
            if days > LONG_QUARANTINE_DAYS:
                old.append(tid)
        if t.get("owners"):
            extra.append("owners " + " ".join(t["owners"]))
        name = f"`{_md(tid).replace('`', '')}`" + (f" ({'; '.join(extra)})" if extra else "")
        rows.append(name.replace("@", "@\u200b"))
    more = f" and {len(tests) - 10} more" if len(tests) > 10 else ""
    lines = [MARKER, "### StackVitals: CI passed only because of quarantine",
             f"The checks passed only because these known-flaky tests are quarantined and were let through: "
             f"{', '.join(rows)}{more}. They failed on this commit, so a real failure there would be hidden too."]
    if old:
        lines.append(f"{len(old)} of them have been flaky for over {LONG_QUARANTINE_DAYS} days: fix them, or take one out of "
                     f"quarantine with `/stackvitals unquarantine test:<id>` so its failures count again.")
    return "\n".join(lines + ["", f"<sub>From the CI history kept in {_md(repo)}'s stackvitals-data branch.</sub>"])


def find_pr(api: ActionsAPI, payload: dict) -> int | None:
    run = payload.get("workflow_run") or {}
    prs = run.get("pull_requests") or []
    if prs:
        return prs[0]["number"]
    # Fork PRs come with an empty list; find the open PR by its head owner and branch.
    owner = ((run.get("head_repository") or {}).get("owner") or {}).get("login")
    if not owner or not run.get("head_branch"):
        return None
    found = api._get(f"/repos/{api.repo}/pulls", {"state": "open", "head": f"{owner}:{run['head_branch']}"})
    return found[0]["number"] if found else None


def our_comment(api: ActionsAPI, pr: int) -> dict | None:
    return next((c for c in api._get(f"/repos/{api.repo}/issues/{pr}/comments", {"per_page": 100}) or []
                 if MARKER in (c.get("body") or "")), None)


def upsert_comment(api: ActionsAPI, pr: int, body: str, found: dict | None = None) -> str:
    # One comment per PR, edited in place on every run.
    c = found or our_comment(api, pr)
    if c:
        api.send("PATCH", f"/repos/{api.repo}/issues/comments/{c['id']}", {"body": body})
        return "updated"
    api.send("POST", f"/repos/{api.repo}/issues/{pr}/comments", {"body": body})
    return "created"


TRIAGE_NOTE = re.compile(r"<!-- stackvitals:triage (\{.*?\}) -->", re.S)


def remembered(body: str | None) -> dict:
    """The model's earlier views on this PR's failures, kept in our own comment, so one failure is sent once."""
    m = TRIAGE_NOTE.search(body or "")
    try:
        got = json.loads(m[1]) if m else {}
    except ValueError:
        return {}
    return got if isinstance(got, dict) else {}


VERDICT_NAME = "StackVitals verdict"


def verdict_payload(items: list[dict], green: bool, waiting: int = 0, patch: dict | None = None, min_patch: float = 0.0,
                    held: bool = False) -> dict:
    """The check run for a pull request's newest code: success when it is green, and its added lines ran at least
    `min_patch` of the time when that is set; in progress while other workflows on that commit still run, so a required
    check never passes early. A likely flake never passes it by itself: on 81 held-out calls from history alone in 15
    public repos, 13 were the change's own failures (16%), and the stricter rule's 4 fresh calls can't show 5%, so a re-run
    decides (a flake passes, the change's fails again)."""
    if waiting:
        return {"name": VERDICT_NAME, "status": "in_progress",
                "output": {"title": f"Waiting for {waiting} workflow{'' if waiting == 1 else 's'} to finish",
                           "summary": "The verdict comes once every workflow on this commit has finished."}}
    blocking = [i for i in items if i.get("verdict") != "known flaky"]
    if green and held:
        # Strict mode: a failure that looked like the change's own went green on a re-run of the same code.
        conclusion, title = "failure", "A failure that looked like this change's own passed on a re-run: comment /stackvitals accept rerun to pass"
    elif green or not items:
        conclusion, title = "success", "CI passed"
    elif not blocking:
        conclusion, title = "failure", f"Only likely flakes failed ({len(items)}): check the errors, then re-run them; this passes once CI is green"
    else:
        conclusion, title = "failure", f"{len(blocking)} failure{'' if len(blocking) == 1 else 's'} to look at"
    summary = "\n".join(f"- {i.get('kind')} `{_code(i.get('name'))}`: {i.get('verdict')}" for i in items[:50])
    if patch and patch.get("lines"):
        share = patch["covered"] / patch["lines"]
        line = f"Patch coverage: {share:.0%} ({patch['covered']} of {patch['lines']} added lines ran)"
        if min_patch and share < min_patch:
            conclusion, title = "failure", f"Patch coverage {share:.0%}, under this repo's {min_patch:.0%}" + (
                f"; {title}" if title != "CI passed" else "")
            line += f"; this repo asks for {min_patch:.0%} under [ci.coverage] min_patch."
        summary = f"{summary}\n\n{line}".strip()
    return {"name": VERDICT_NAME, "status": "completed", "conclusion": conclusion,
            "output": {"title": title, "summary": summary or "Every check on the newest code passed."}}
