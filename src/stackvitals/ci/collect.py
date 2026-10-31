import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from stackvitals.ci.api import ActionsAPI, APIError, OutOfBudget
from stackvitals.ci.store import DataStore
from stackvitals.ci import coverage
from stackvitals.ci.testreports import _empty, parse_archive

PR_EVENTS = {"pull_request", "pull_request_target"}
# New test ids kept per report, and the most test ids remembered (past that, nothing is called new).
NEW_KEEP, KNOWN_MAX = 50, 50_000
# Artifact names that usually hold test reports; users can pass their own pattern.
TEST_REPORTS = (r"junit|test[-_ ]?results?|test[-_ ]?reports?|ctrf|surefire|pytest|jest|vitest|playwright|trx|go[-_ ]?test"
                r"|xunit|nunit|mstest")
# Coverage reports too, but not HTML coverage sites (nothing to read there).
TEST_ARTIFACTS = TEST_REPORTS + r"|lcov|jacoco|cobertura|coverage(?![-_ ]?html)"


def run_record(body: dict, n: int) -> dict:
    # pull_requests on non-PR runs can list unrelated fork PRs, so it is trusted only for PR events.
    prs = [p["number"] for p in body.get("pull_requests") or []] if body.get("event") in PR_EVENTS else []
    rec = {"t": "run", "id": body["id"], "att": n, "wf": body.get("workflow_id"), "wfn": body.get("name"),
            "path": body.get("path"), "ev": body.get("event"), "br": body.get("head_branch"),
            "sha": body.get("head_sha"), "tree": (body.get("head_commit") or {}).get("tree_id"), "pr": prs,
            "c": body.get("conclusion"), "cr": body.get("created_at"), "st": body.get("run_started_at"),
            "up": body.get("updated_at")}
    if body.get("event") in PR_EVENTS:
        # Fork PR runs list no PR numbers; the head owner and branch find the PR later.
        rec["ho"] = ((body.get("head_repository") or {}).get("owner") or {}).get("login")
    return rec


def job_record(j: dict, run_id: int, n: int) -> dict:
    steps = [[s.get("number"), s.get("name"), s.get("conclusion"), s.get("started_at"), s.get("completed_at")]
             for s in j.get("steps") or []]
    return {"t": "job", "run": run_id, "att": n, "id": j["id"], "n": j.get("name"), "c": j.get("conclusion"),
            "cr": j.get("created_at"), "st": j.get("started_at"), "en": j.get("completed_at"),
            "lb": j.get("labels") or [], "steps": steps}


def _fetch(api: ActionsAPI, run: dict, n: int) -> list[dict]:
    body = run if n == run.get("run_attempt", 1) else api.attempt(run["id"], n)
    return [run_record(body, n)] + [job_record(j, run["id"], n) for j in api.jobs(run["id"], n)]


def _attempt_of(created: str | None, starts: dict[int, str]) -> int:
    # An artifact belongs to the last attempt that had started before it was uploaded.
    started = [att for att, st in starts.items() if st and created and st <= created]
    return max(started) if started else min(starts or {1: None})


def _pr_number(api: ActionsAPI, run: dict) -> int | None:
    """The pull request a pull_request run tested: the one GitHub names, else (forks) the one with that head branch."""
    if run.get("event") != "pull_request":
        return None
    named = [p.get("number") for p in run.get("pull_requests") or [] if p.get("number")]
    if named:
        return named[0]
    owner = ((run.get("head_repository") or {}).get("owner") or {}).get("login")
    if not owner or not run.get("head_branch"):
        return None
    try:
        prs = api._get(f"/repos/{api.repo}/pulls", {"head": f"{owner}:{run['head_branch']}", "state": "all", "per_page": 5})
    except APIError:
        return None
    same = [p for p in prs or [] if (p.get("head") or {}).get("sha") == run.get("head_sha")]
    return (same or prs or [{}])[0].get("number")


def _pr_files(api: ActionsAPI, number: int, pages: int = 10) -> list[dict]:
    out = []
    for page in range(1, pages + 1):
        got = api._get(f"/repos/{api.repo}/pulls/{number}/files", {"per_page": 100, "page": page}) or []
        out += got
        if len(got) < 100:
            break
    return out


def _reports(api: ActionsAPI, run: dict, starts: dict[int, str], pattern: str, max_bytes: int,
             done_arts: set) -> list[dict]:
    out, diff = [], {}
    for art in api.artifacts(run["id"]):
        if (art["id"] in done_arts or art.get("expired") or not re.search(pattern, art.get("name") or "", re.I)
                or (art.get("size_in_bytes") or 0) > max_bytes):
            continue
        data = api.download(art["id"])  # a GitHub error here is retried on the next run
        try:
            parsed = parse_archive(data)
        except Exception:  # a broken or hostile artifact is noted once and never read again
            out.append({"t": "tests", "run": run["id"], "att": _attempt_of(art.get("created_at"), starts), "art": art["id"],
                        "name": art.get("name"), **{k: v for k, v in _empty().items() if k != "all"}, "unreadable": True})
            continue
        cov = parsed.pop("cov", None)
        rec = {"t": "tests", "run": run["id"], "att": _attempt_of(art.get("created_at"), starts), "art": art["id"],
               "name": art.get("name"), **parsed}
        if cov:
            # Only the totals are kept; the line hits are read once, for the pull request's patch coverage.
            rec["cov"] = {"format": cov["format"], "lines": cov["lines"], "covered": cov["covered"]}
            # The run's pull request and its files are read once, however many coverage artifacts the matrix uploads.
            if "pr" not in diff:
                diff["pr"] = _pr_number(api, run)
            number = diff["pr"]
            if number:
                try:
                    if number not in diff:
                        diff[number] = _pr_files(api, number)
                    rec["patch"] = {"pr": number, **coverage.patch(cov, diff[number])}
                except APIError:
                    pass
        out.append(rec)
    return out


def _distrust(rec: dict, own: bool) -> None:
    # A fork PR writes its own reports: a forged "passed on retry" could make a real test known flaky (and quarantined).
    if not own:
        rec["flaky"] = []
        rec.pop("cov", None)


def _learn(rec: dict, ids: list[str], seen: set, known: bool, own: bool) -> None:
    """Note a report's tests seen for the first time, and remember them up to the cap; a fork's runs teach nothing, so
    its made-up ids can neither fill the list nor show up as new tests."""
    if not own:
        return
    full = len(seen) >= KNOWN_MAX
    new = [t for t in ids if t not in seen] if known and not full else []
    if new:
        rec["new"] = new[:NEW_KEEP]
    room = KNOWN_MAX - len(seen)
    if room > 0:
        seen.update([t for t in ids if t not in seen][:room])


def collect(api: ActionsAPI, store: DataStore, now: datetime, days: int = 90, exclude=(),
            recheck_days: int = 3, workers: int = 10, log=None, tests: bool = False,
            artifact_pattern: str = TEST_ARTIFACTS, max_artifact_bytes: int = 50_000_000) -> dict:
    """Store every new attempt of every completed run in the last `days` days, newest day first,
    and (with tests=True) the test reports in each run's artifacts."""
    state = store.state()
    scanned = state.setdefault("scanned", {})
    scanned_tests = state.setdefault("scanned_tests", {})
    checked = state.setdefault("arts_checked", {})
    loaded = store.load()
    seen = {(r["id"], r["att"]) for r in loaded["runs"]}
    done_arts = {r["art"] for r in loaded["tests"]}
    # Test ids seen before; the first collect that reads reports sets the baseline and names nothing as new.
    known = store.known_tests() if tests else None
    seen_ids = set(known or ())
    starts: dict[int, dict[int, str]] = {}
    for r in loaded["runs"]:
        starts.setdefault(r["id"], {})[r["att"]] = r.get("st")
    today = now.date()
    stamp = today.isoformat()
    excluded = set(exclude)
    touched, complete = set(), True
    pool = ThreadPoolExecutor(max_workers=max(1, workers))
    try:
        for back in range(days + 1):
            day = (today - timedelta(days=back)).isoformat()
            # Re-runs land on old runs, so the last few days are always checked again.
            jobs_done = scanned.get(day) == "done" and back > recheck_days
            tests_done = not tests or (scanned_tests.get(day) == "done" and back > recheck_days)
            if jobs_done and tests_done:
                continue
            # GitHub-managed workflows (Dependabot, CodeQL default setup, Pages) live under "dynamic/".
            listed = [run for run in api.runs_on_day(day)
                      if run.get("path") not in excluded and not (run.get("path") or "").startswith("dynamic/")
                      and run.get("status") == "completed"]
            todo = [(run, n) for run in listed for n in range(1, (run.get("run_attempt") or 1) + 1)
                    if (run["id"], n) not in seen]
            futures = [pool.submit(_fetch, api, run, n) for run, n in todo]
            stop, skipped = None, 0
            for (run, n), fut in zip(todo, futures):
                try:
                    records = fut.result()
                except OutOfBudget as exc:
                    stop = stop or exc
                    continue
                except APIError:
                    # One run GitHub can't serve right now is skipped; the day stays open for the next run.
                    skipped += 1
                    continue
                # Each attempt is written as soon as it is read, under the day the run happened.
                store.add(records, day)
                seen.add((run["id"], n))
                touched.add(run["id"])
                starts.setdefault(run["id"], {})[n] = records[0].get("st")
            if tests and not stop:
                # Reports are read once per run and attempt count, so a later re-run's reports are read too.
                mark = lambda run: f"{run['id']}:{run.get('run_attempt') or 1}"  # noqa: E731
                pending = [run for run in listed if mark(run) not in checked
                           and all((run["id"], n) in seen for n in range(1, (run.get("run_attempt") or 1) + 1))]
                rfutures = [pool.submit(_reports, api, run, starts.get(run["id"], {}), artifact_pattern,
                                        max_artifact_bytes, done_arts) for run in pending]
                for run, fut in zip(pending, rfutures):
                    try:
                        reports = fut.result()
                    except OutOfBudget as exc:
                        stop = stop or exc
                        continue
                    except APIError:
                        skipped += 1
                        continue
                    own = (run.get("head_repository") or {}).get("full_name") in (None, api.repo)
                    for rec in reports:
                        _learn(rec, [t for t, _ms in rec.pop("all", [])], seen_ids, known is not None, own)
                        _distrust(rec, own)
                    store.add(reports, day)
                    done_arts.update(r["art"] for r in reports)
                    checked[mark(run)] = day
            if log:
                log(f"{day}: {len({r['id'] for r in listed})} run(s) read, {api.requests} requests so far")
            if stop:
                raise stop
            if skipped:
                complete = False
                scanned[day] = "partial"
                state["last_stop"] = f"{skipped} run(s) GitHub could not serve on {day}; retried next time"
            else:
                scanned[day] = "done"
                if tests:
                    scanned_tests[day] = "done"
    except OutOfBudget as exc:
        complete = False
        state["last_stop"] = str(exc)
    finally:
        pool.shutdown(wait=True)
    oldest = (today - timedelta(days=days + recheck_days)).isoformat()
    state["arts_checked"] = {k: v for k, v in checked.items() if v >= oldest}
    state["last_collect"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    store.save_state(state)
    if tests and seen_ids:
        store.save_known_tests(seen_ids)
    # Past days are compressed right away, so a big first backfill never sits in git uncompressed.
    store.compress(stamp)
    return {"runs": len(touched), "requests": api.requests, "complete": complete}
