import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from stackvitals.ci.analyze import SHOWN, analyze
from stackvitals.ci.api import ActionsAPI, APIError, OutOfBudget
from stackvitals.ci import bench
from stackvitals.ci.automation import (alert_message, apply_decisions, new_flakes, owners_of, quarantine_list, rerun_failed_jobs, send_alert,
                                       should_rerun, sync_issues)
from stackvitals.ci.collect import PR_EVENTS, collect
from stackvitals.ci.feedback import (MARKER, classify, find_pr, our_comment, quarantine_note, quarantined_failures,
                                     remembered, render_comment, upsert_comment, verdict_payload, blamed_sha, green_note)
from stackvitals.ci.owners import attach_owners, read_codeowners, test_files
from stackvitals.ci.report import detail_name, render_detail, render_html, render_markdown
from stackvitals.ci.store import DataStore
from stackvitals.ci.triage import MAX_CALLS, UNDECIDED, triage
from stackvitals.ci.triggers import pr_edit_workflows, pr_metadata_workflows
from stackvitals.ci.monitors import transitions
from stackvitals.core.store import published
from stackvitals.core.summary import write_ci_summary
from stackvitals import shell

BRANCH = "stackvitals-data"
LABEL = "CI Health"
GREEN = {"success", "neutral", "skipped"}
FEEDBACK_OVERLAP = timedelta(minutes=15)
MAX_PRS, MAX_RERUNS, MAX_LOOKUPS, AFTER_COLLECT = 20, 5, 30, 60
BOT = ("github-actions[bot]", "41898282+github-actions[bot]@users.noreply.github.com")
DATA_README = """# StackVitals data

This branch holds CI history collected by StackVitals: `ci/days/` (one file per day), `ci/state.json`,
and the dashboard in `docs/`. To publish the dashboard (public repos), set GitHub Pages to deploy from
this branch, folder `/docs`. Nothing here is sent anywhere else.
"""


class GitError(RuntimeError):
    pass


class DataBranch:
    # A shallow clone of the data branch; the remote URL may carry a token, so it is never printed.
    def __init__(self, remote: str, branch: str, path: Path):
        self.remote, self.branch, self.path = remote, branch, Path(path)

    def _git(self, *args, cwd=None, check=True) -> subprocess.CompletedProcess:
        # Git for Windows can turn on a file watcher for every repo; a short-lived clone must not leave one running.
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_COUNT": "1",
               "GIT_CONFIG_KEY_0": "core.fsmonitor", "GIT_CONFIG_VALUE_0": "false"}
        run = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=env)
        if check and run.returncode:
            raise GitError(f"git {args[0]} failed: {run.stderr.replace(self.remote, '<remote>')[-300:]}")
        return run

    def _network(self, *args, cwd=None) -> subprocess.CompletedProcess:
        # Network steps can hiccup ("could not read from remote"); try three times before giving up.
        for attempt in range(3):
            run = self._git(*args, cwd=cwd, check=False)
            if run.returncode == 0:
                return run
            if self.path.exists() and args[0] == "clone":
                shutil.rmtree(self.path, ignore_errors=True)
            time.sleep(2 * (attempt + 1))
        raise GitError(f"git {args[0]} failed: {run.stderr.replace(self.remote, '<remote>')[-300:]}")

    def open(self) -> None:
        if self.path.exists():
            shutil.rmtree(self.path)
        heads = self._network("ls-remote", "--heads", self.remote, self.branch)
        if heads.stdout.strip():
            self._network("clone", "-q", "--depth", "1", "--branch", self.branch, "--single-branch", self.remote,
                          str(self.path))
            return
        # First run: an empty branch with no shared history with the code.
        self.path.mkdir(parents=True)
        self._git("init", "-q", cwd=self.path)
        self._git("checkout", "-q", "--orphan", self.branch, cwd=self.path)
        self._git("remote", "add", "origin", self.remote, cwd=self.path)

    def dirty(self) -> bool:
        self._git("add", "-A", cwd=self.path)
        return bool(self._git("diff", "--cached", "--quiet", cwd=self.path, check=False).returncode)

    def squash(self, message: str) -> str:
        """Rewrite the branch to one commit holding the current files; refused if anyone pushed in between."""
        expected = self._git("rev-parse", "HEAD", cwd=self.path).stdout.strip()
        self._git("add", "-A", cwd=self.path)
        self._git("checkout", "-q", "--orphan", "stackvitals-squash", cwd=self.path)
        self._git("-c", f"user.name={BOT[0]}", "-c", f"user.email={BOT[1]}", "commit", "-q", "-m", message, cwd=self.path)
        push = self._git("push", "-q", f"--force-with-lease=refs/heads/{self.branch}:{expected}", "origin",
                         f"HEAD:refs/heads/{self.branch}", cwd=self.path, check=False)
        if push.returncode == 0:
            return "pushed"
        if "rejected" in push.stderr or "stale info" in push.stderr:
            return "rejected"
        raise GitError(f"git push failed: {push.stderr.replace(self.remote, '<remote>')[-300:]}")

    def commit_push(self, message: str) -> str:
        if not self.dirty():
            return "unchanged"
        self._git("-c", f"user.name={BOT[0]}", "-c", f"user.email={BOT[1]}", "commit", "-q", "-m", message, cwd=self.path)
        for attempt in range(3):
            push = self._git("push", "-q", "origin", f"HEAD:refs/heads/{self.branch}", cwd=self.path, check=False)
            if push.returncode == 0:
                return "pushed"
            # The server said no (protected branch, push rule, hook): trying again can't help.
            if "[remote rejected]" in push.stderr and "cannot lock ref" not in push.stderr:
                raise GitError(f"the server refused the push to {self.branch} (a protected branch, push rule or hook, or "
                               f"a token that can't write): {push.stderr.replace(self.remote, '<remote>')[-300:]}")
            # Someone else pushed first: the caller starts again on top of their data.
            if "rejected" in push.stderr or "fetch first" in push.stderr or "non-fast-forward" in push.stderr:
                return "rejected"
            time.sleep(2 * (attempt + 1))
        raise GitError(f"git push failed: {push.stderr.replace(self.remote, '<remote>')[-300:]}")


def _own_workflow(env: dict) -> str | None:
    # GITHUB_WORKFLOW_REF looks like owner/repo/.github/workflows/name.yml@refs/heads/main.
    ref = env.get("GITHUB_WORKFLOW_REF") or ""
    repo = env.get("GITHUB_REPOSITORY") or ""
    return ref.split("@")[0][len(repo) + 1:] if ref.startswith(repo + "/") else None


def write_outputs(root: Path, result: dict, repo: str, site: str = "docs", data_readme: bool = True) -> None:
    docs = root / site
    docs.mkdir(parents=True, exist_ok=True)
    # The header links only the module pages already written, so a link never leads nowhere.
    pages = shell.present(docs) | {"ci.html"}
    write_details(docs, result, repo, pages)
    # index.html is the app now (core/webapp.py); this is the printable CI page.
    (docs / "ci.html").write_text(render_html(result, repo, pages), encoding="utf-8")
    # The per-run history goes only into the pages; the public data file stays small.
    out = {k: v for k, v in result.items() if k != "history"}
    from stackvitals.ci.investigate import prompt
    # A prompt to hand an AI agent for the biggest failure groups; the app copies it.
    out["failure_groups"] = [{**g, "prompt": prompt(repo, g, result.get("tests") or [])} if k < PROMPTS else g
                             for k, g in enumerate(result.get("failure_groups") or [])]
    (docs / "data.json").write_text(json.dumps(published(out), indent=1), encoding="utf-8")
    (docs / ".nojekyll").write_text("", encoding="utf-8")
    (docs / "badge.json").write_text(json.dumps(bench.badge(result.get("pushes"))), encoding="utf-8")
    if data_readme:
        (root / "README.md").write_text(DATA_README, encoding="utf-8")


PROMPTS = 10
DETAIL_FILE = re.compile(r"(job|test)-[a-z0-9-]*-[0-9a-f]{8}\.html")


def write_details(docs: Path, result: dict, repo: str, pages) -> None:
    """A history page per test or job that is not ok; pages of items that are ok again are removed (only ours)."""
    folder = docs / "history"
    if folder.is_dir():
        for old in folder.iterdir():
            if DETAIL_FILE.fullmatch(old.name):
                old.unlink()
    history = result.get("history") or {}
    items = [("job", f"{j['workflow']}|{j['job']}", j) for j in result.get("jobs") or []]
    items += [("test", t["id"], t) for t in result.get("tests") or []]
    for kind, ident, item in items:
        rows = (history.get(kind + "s") or {}).get(ident)
        if rows:
            folder.mkdir(exist_ok=True)
            (folder / detail_name(kind, ident)).write_text(render_detail(kind, ident, item, rows, result, repo, pages),
                                                           encoding="utf-8")


def add_owners(api, store, result: dict, ref: str | None, today: str) -> None:
    """Owners for what the dashboard lists, from CODEOWNERS (a few requests a day); never stops a run."""
    tests = [t["id"] for t in result.get("tests") or [] if t["state"] in SHOWN]
    if not tests and not any(j["state"] in SHOWN for j in result.get("jobs") or []):
        return
    try:
        co = read_codeowners(api, ref, store, today)
        attach_owners(result, co, test_files(api, ref, store, today, tests) if co["text"] and tests else {})
    except (APIError, OutOfBudget):
        pass


def _trigger(env: dict) -> dict | None:
    # The finished CI run that started this one (workflow_run trigger), if any.
    if env.get("GITHUB_EVENT_NAME") != "workflow_run" or not env.get("GITHUB_EVENT_PATH"):
        return None
    try:
        return json.loads(Path(env["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _latest(data: dict) -> dict:
    latest = {}
    for r in data["runs"]:
        if r["att"] >= latest.get(r["id"], {}).get("att", 0):
            latest[r["id"]] = r
    return latest


def _finished_since(latest: dict, old: dict | None, trigger_id) -> list[dict]:
    # GitHub cancels queued runs of a busy concurrency group, so each run also covers what finished since the last.
    ids = {trigger_id} if trigger_id else set()
    if old and old.get("generated"):
        cut = datetime.fromisoformat(old["generated"].replace("Z", "+00:00")) - FEEDBACK_OVERLAP
        ids |= {rid for rid, r in latest.items() if (r.get("up") or "") >= cut.strftime("%Y-%m-%dT%H:%M:%SZ")}
    return [latest[i] for i in sorted(ids) if i in latest]


def _same_pr(r: dict, seed: dict, pr: int) -> bool:
    if r.get("ev") not in PR_EVENTS:
        return False
    if pr in (r.get("pr") or []):
        return True
    return not r.get("pr") and bool(r.get("ho")) and (r.get("ho"), r.get("br")) == (seed.get("ho"), seed.get("br"))


def _pr_of(api, r: dict) -> int | None:
    if r.get("pr"):
        return r["pr"][0]
    if not r.get("ho") or not r.get("br"):
        return None
    found = api._get(f"/repos/{api.repo}/pulls", {"state": "open", "head": f"{r['ho']}:{r['br']}"})
    return found[0]["number"] if found else None


def _patch_of(data: dict, run_ids: set) -> dict | None:
    """The widest patch coverage measured in these runs (matrix jobs measure the same code)."""
    found = [t["patch"] for t in data.get("tests") or [] if t["run"] in run_ids and t.get("patch")]
    return max(found, key=lambda p: p.get("lines") or 0) if found else None


def _triage_on(settings: dict | None, private: bool = False, notes: list | None = None) -> bool:
    t = ((settings or {}).get("ci") or {}).get("triage") or {}
    if t.get("provider", "off") == "off" or not os.environ.get("STACKVITALS_TRIAGE_KEY"):
        return False
    if private and not t.get("allow_private"):
        if notes is not None and not any("ci.triage" in n for n in notes):
            notes.append("Model triage is off for this private repo: set [ci.triage] allow_private = true once your "
                         "provider's terms suit you (free tiers may keep what they're sent).")
        return False
    return True


def _pr_files(api, repo: str, pr: int) -> list[str]:
    try:
        return [f["filename"] for f in api._get(f"/repos/{repo}/pulls/{pr}/files", {"per_page": 100}) or []]
    except (APIError, OutOfBudget):
        return []


def _pr_feedback(recent: list[dict], latest: dict, payload: dict | None, api, data: dict, result: dict,
                 repo: str, quarantined: set | None = None, comments: bool = True, verdict: bool = False,
                 notes: list | None = None, min_patch: float = 0.0, logs: dict | None = None,
                 settings: dict | None = None, private: bool = False, decided: dict | None = None) -> str | None:
    # One comment per PR about every failing workflow on its newest code; a passing PR only edits an old comment.
    trigger = (payload or {}).get("workflow_run") or {}
    prs, looked, announce = {}, {}, set()
    for r in recent:
        if r.get("ev") not in PR_EVENTS or len(prs) >= MAX_PRS:
            continue
        if r["id"] == trigger.get("id"):
            pr = find_pr(api, payload)
            # Events go out once per triggering run, and never for a fork's pull request.
            if r.get("ho") in (None, repo.split("/")[0]):
                announce.add(pr)
        elif r.get("pr"):
            pr = r["pr"][0]
        elif (r.get("ho"), r.get("br")) in looked or len(looked) < MAX_LOOKUPS:
            # Fork PR runs carry no PR number: one lookup per head owner and branch, and only a few per run.
            key = (r.get("ho"), r.get("br"))
            pr = looked[key] if key in looked else looked.setdefault(key, _pr_of(api, r))
        else:
            pr = None
        if pr:
            prs.setdefault(pr, r)
    outcomes = []

    def post_verdict(sha: str, code: list[dict], items: list[dict], held: bool = False) -> None:
        try:
            # Cancelled, timed out or never started blocks too; only green passes (known flakes are re-run, never let through).
            stopped = [{"kind": "run", "name": r.get("wfn") or "CI", "verdict": r.get("c")} for r in code
                       if r.get("c") not in GREEN and r.get("c") != "failure"]
            running = [w for w in (api._get(f"/repos/{repo}/actions/runs", {"head_sha": sha, "per_page": 50}) or {})
                       .get("workflow_runs") or [] if w.get("status") != "completed" and w.get("path") != own]
            patch = _patch_of(data, {r["id"] for r in code})
            api.send("POST", f"/repos/{repo}/check-runs",
                     {**verdict_payload(items + stopped, all(r.get("c") in GREEN for r in code), len(running), patch, min_patch,
                                        held),
                      "head_sha": sha})
        except (APIError, OutOfBudget) as exc:
            if notes is not None:
                notes.append(f"Could not post the StackVitals verdict check ({exc}); it needs `checks: write`.")
    own = (os.environ.get("GITHUB_WORKFLOW_REF") or "").split("@")[0].split("/", 2)[-1] or None
    strict = verdict and bool(((settings or {}).get("automation") or {}).get("verdict_strict"))
    calls_left = MAX_CALLS
    for pr, seed in prs.items():
        mine = [r for r in latest.values() if _same_pr(r, seed, pr)] or [seed]
        newest = max(mine, key=lambda r: r.get("cr") or "")["sha"]
        code = [r for r in mine if r["sha"] == newest]
        items = [i for r in code if r.get("c") == "failure"
                 for i in classify(api, data, result, r["id"], logs)]
        found = None
        if comments and items and _triage_on(settings, private, notes):
            # Advice only: the verdict check below is posted from the same verdicts either way. Views already in our
            # comment are reused, and one run makes at most MAX_CALLS calls across all its pull requests.
            found = our_comment(api, pr)
            read = {jid: sec for r in code for jid, sec in ((logs or {}).get(r["id"]) or {}).items()}
            needs = any(i["verdict"] in UNDECIDED and str(i.get("job_id")) not in remembered((found or {}).get("body"))
                        for i in items)
            calls_left -= triage(items, read, _pr_files(api, repo, pr) if needs and calls_left else [], settings,
                                 os.environ.get("STACKVITALS_TRIAGE_KEY"), private=private,
                                 memory=remembered((found or {}).get("body")), limit=calls_left)
        held = False
        if strict and not items and all(r.get("c") in GREEN for r in code):
            # Strict mode: the comment blamed this very commit on the change, and CI went green only on a re-run.
            found = found or our_comment(api, pr)
            if blamed_sha((found or {}).get("body")) == newest:
                ok = (decided or {}).get(f"rerun:{pr}") or {}
                held = not (ok.get("verb") == "accept" and (ok.get("at") or "") >= ((found or {}).get("updated_at") or ""))
        if verdict:
            post_verdict(newest, code, items, held)
        if items and pr in announce:
            from stackvitals.core import events as outbound
            sent = outbound.send([outbound.pr_verdict(pr, newest, items, repo, datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"))], settings)
            if notes is not None:
                notes += sent
        if not comments:
            continue
        if held:
            note = (f"{MARKER}\n### StackVitals: a re-run turned this green\nA failure on this commit looked like the change's own "
                    "and passed when run again. A green re-run doesn't prove the change clean, so this repo's verdict waits: "
                    "after a look, comment `/stackvitals accept rerun`.\n<!-- stackvitals:blamed " + newest + " -->")
            outcomes.append(upsert_comment(api, pr, note, found))
            continue
        if items:
            outcomes.append(upsert_comment(api, pr, render_comment(items, repo, newest), found))
        elif all(r.get("c") in GREEN for r in code):
            let_through = quarantined_failures(data, [r["id"] for r in code], quarantined)
            if let_through:
                # Green only because quarantined tests were let through: say so, or a real failure could hide there.
                note = quarantine_note(let_through, repo, result, datetime.now(timezone.utc))
                outcomes.append(upsert_comment(api, pr, note))
                continue
            existing = [c for c in api._get(f"/repos/{repo}/issues/{pr}/comments", {"per_page": 100}) or []
                        if MARKER in (c.get("body") or "")]
            if existing:
                outcomes.append(upsert_comment(api, pr, green_note(existing[0].get("body"), newest), existing[0]))
    if verdict:
        # A merge queue tests its own commit, so a required verdict must be posted there too.
        queued = {r["sha"] for r in recent if r.get("ev") == "merge_group" and r.get("sha")}
        for sha in sorted(queued)[:MAX_PRS]:
            code = [r for r in latest.values() if r.get("sha") == sha and r.get("ev") == "merge_group"]
            post_verdict(sha, code, [i for r in code if r.get("c") == "failure"
                                     for i in classify(api, data, result, r["id"], logs)])
    return "created" if "created" in outcomes else "updated" if outcomes else None


def _previous(root: Path) -> dict | None:
    # Last run's findings, to alert only on what newly turned flaky.
    try:
        return json.loads((root / "docs" / "data.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def ci_step(ws, env: dict, now: datetime, days: int = 90, window_days: int = 30, retention_days: int = 180,
            budget: int = 800, exclude: list[str] | None = None, make_api=ActionsAPI, tests: bool = True,
            artifact_pattern: str | None = None, pr_comments: bool = True, rerun_flaky: bool = False,
            quarantine: bool = False, issues: bool = False, webhook: str | None = None, mention_owners: bool = False,
            assign_owners: bool = False, verdict_check: bool = False) -> dict:
    """CI Health's part of a job: collect into the shared checkout, analyze, write the pages; what needs the commit
    first (re-runs, comments, issues, alerts, the summary) is registered as the job's after-commit hook."""
    repo, token = ws.repo, env.get("STACKVITALS_TOKEN") or env.get("GITHUB_TOKEN")
    skip = [p for p in [_own_workflow(env), *(exclude or [])] if p]
    payload = _trigger(env)
    store = DataStore(ws.path)
    # Collection may spend the budget; the repo lookup comes first and a little is kept for feedback.
    api = make_api(token, repo, max_requests=max(budget - AFTER_COLLECT, 1))
    info = ws.cache.get("repo_info") or api._get(f"/repos/{repo}")
    stats = collect(api, store, now, days=days, exclude=skip, tests=tests,
                    **({"artifact_pattern": artifact_pattern} if artifact_pattern else {}))
    api.max_requests = budget
    today = now.date().isoformat()
    store.compact(today, retention_days)
    data = store.load()
    ws.cache["ci"] = data
    meta = pr_metadata_workflows(api, store, data, info.get("default_branch"), today)
    settings, setting_notes = ws.cache.get("settings"), []
    if settings is None:
        # Run on its own (no job-wide read): the same reader, its notes in CI's own summary.
        from stackvitals.core.settings import load
        got = load(api, ws.path, now)
        settings, setting_notes = got.cfg, got.notes
        ws.cache["settings"] = settings
    status_file = ws.path / "ci" / "status.json"
    try:
        previous_status = json.loads(status_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous_status = {}
    result = analyze(data, now, window_days, default_branch=info.get("default_branch"), pr_metadata=meta, attempts=True,
                     pr_edits=pr_edit_workflows(store),
                     config=settings, previous=previous_status)
    # Each test's status with the day it began, and one line per change, so "flaky since" survives every run.
    status, changes = transitions(previous_status, result.get("tests") or [], now)
    status_file.write_text(json.dumps(status, indent=1, sort_keys=True), encoding="utf-8")
    if changes:
        log = ws.path / "ci" / "transitions" / f"{today}.ndjson"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8", newline="\n") as f:
            f.writelines(json.dumps(c, separators=(",", ":")) + "\n" for c in changes)
    from stackvitals.ci.cost import report as cost_report
    # What CI costs in minutes and money over the last 30 days, and what flaky re-runs add.
    result["cost"] = cost_report(data, now, private=bool(info.get("private")), days=30)
    from stackvitals.ci import impact
    from stackvitals.flow.store import FlowStore
    # Test impact: learned from past PRs' changed files and real failures, and replayed on them before anyone trusts it.
    if (ws.path / "flow").is_dir():
        pr_paths = {p["n"]: p.get("paths") or [] for p in FlowStore(ws.path).load().get("closed") or [] if p.get("paths")}
        hist = impact.history_from(data, pr_paths, {t["id"] for t in result.get("tests") or [] if t.get("state") == "flaky"})
        files = sorted({f for _c, failed in hist for f in failed} | {p for paths in pr_paths.values() for p in paths if impact.TEST.search(p)})
        result["impact"] = impact.backtest(hist, files) if hist else None
        (ws.path / "ci" / "impact.json").write_text(json.dumps({"learned": impact.learn(hist), "backtest": result["impact"]},
                                                               sort_keys=True), encoding="utf-8")
    from stackvitals.ci.cost import flaky_tests
    # Which flaky tests cost the most re-run minutes, and how many PRs each got in the way of.
    result["cost"]["tests"] = flaky_tests(data, result.get("tests") or [], private=bool(info.get("private")))
    for t in result.get("tests") or []:
        t.pop("_attempts", None)
    # Comparisons come from a public file only (none before launch): no extra request otherwise.
    result["benchmark"] = bench.compare(result["pushes"], bench.load(None, ws.work / "bench"),
                                        info.get("language"), info.get("stargazers_count"))
    share_doc = None
    if ((settings or {}).get("benchmarks") or {}).get("share"):
        from stackvitals.ci import share
        # The id file goes into this run's commit, so next month's figures replace this month's.
        share_doc = share.figures(result["pushes"], info.get("language"), info.get("stargazers_count"),
                                  share.share_id(ws.path), now, repo if settings["benchmarks"].get("name") else None)
        shared = bench.compare(result["pushes"], bench.load(None, ws.work / "bench", name=bench.SHARED_FILE,
                               url_env="STACKVITALS_SHARED_BENCH_URL", default_url=bench.SHARED_URL),
                               info.get("language"), info.get("stargazers_count"), everyone="repos that shared their figures")
        # Shared peers resemble a private team's work more than the crawl's sample, unless only they are a loose fit.
        if shared and (not shared["fit"] or not result["benchmark"] or result["benchmark"]["fit"]):
            result["benchmark"] = {**shared, "group": f"shared: {shared['group']}", "peers": bench.SHARED_ARE}
    add_owners(api, store, result, info.get("default_branch"), today)
    # What people decided on GitHub (quarantine, mute, acknowledge) shapes the list, the alerts, the issues and the page.
    from stackvitals.core.decisions import Store as Decisions
    decided = Decisions(ws.path).state(now.date())
    apply_decisions(result, decided)
    feedback = Decisions(ws.path).feedback()
    if feedback:
        from stackvitals.core.decisions import verdict_accuracy
        # How often this team confirmed what StackVitals said, per verdict: the repo's own running accuracy (counts only).
        result["verdict_feedback"] = verdict_accuracy(feedback)
    old = _previous(ws.path)
    latest = _latest(data)
    recent = _finished_since(latest, old, ((payload or {}).get("workflow_run") or {}).get("id"))
    # Failed jobs' logs, read once per run, show outside failures (a registry or the runner) the history can't.
    logs = {}
    to_rerun = []
    if rerun_flaky:
        # Decided and remembered before the commit, so overlapping runs never re-run a run twice.
        done = store.state().get("reran", [])
        for r in recent:
            # Only first attempts can be re-run, so only their logs are read, and only until enough runs are picked.
            if len(to_rerun) >= MAX_RERUNS or r.get("c") != "failure" or r["id"] in done or r["att"] != 1:
                continue
            if should_rerun(classify(api, data, result, r["id"], logs), r["att"]):
                to_rerun.append(r["id"])
        if to_rerun:
            store.save_state({**store.state(), "reran": (done + to_rerun)[-200:]})
    from stackvitals.ci.tickets import sync as sync_tickets
    # A Jira or Linear ticket per flaky test, when the team asked for one; before the commit, so what was filed is kept.
    tickets = sync_tickets(ws.path, result, settings or {}, env)
    qfile = ws.path / "ci" / "quarantine.json"
    if quarantine:
        qfile.write_text(json.dumps(quarantine_list(result, settings, decided, now)), encoding="utf-8")
        from stackvitals.ci.automation import expired
        # Flaky tests past [ci.quarantine] max_days fail builds again; the page lists them as overdue for a fix.
        result["quarantine_expired"] = expired(result, settings, now)
    elif qfile.exists():
        # Turning quarantine off must stop it at once, so the old list is removed.
        qfile.unlink()
    write_outputs(ws.path, result, repo)
    write_ci_summary(ws.path, result, now)
    fresh = new_flakes(old, result)
    out = {"collect": stats, "flaky": sum(j["state"] == "flaky" for j in result["jobs"]), "comment": None, "rerun": False,
           "new_flaky": fresh}

    def after_commit():
        notes = list(setting_notes)
        # Re-runs go first: they are already recorded as done, so nothing after the commit may stop them.
        for rid in to_rerun:
            try:
                rerun_failed_jobs(api, rid)
                out["rerun"] = True
                notes.append(f"Run {rid} failed only on known flakes or outside failures, so its failed jobs were re-run once.")
            except (APIError, OutOfBudget) as exc:
                notes.append(f"Could not re-run run {rid} ({exc}); add `actions: write` to the workflow permissions.")
        if verdict_check and info.get("private") and (env.get("STACKVITALS_EVERY_CI_RUN") or "").lower() != "true":
            # The workflow starts no job for a passing CI run on a private repo, so the check would wait for the next
            # 3-hourly run to turn green.
            notes.append("The verdict check is on, but CI runs that pass don't start StackVitals on this private repo: set the "
                         "repository variable STACKVITALS_EVERY_CI_RUN to true so the check passes as soon as CI does.")
        if pr_comments or verdict_check:
            try:
                out["comment"] = _pr_feedback(recent, latest, payload, api, data, result, repo,
                                              set(quarantine_list(result, settings, decided, now)) if quarantine else None,
                                              comments=pr_comments, verdict=verdict_check, notes=notes,
                                              min_patch=((settings or {}).get("ci") or {}).get("coverage", {}).get("min_patch", 0.0),
                                              logs=logs, settings=settings, private=bool(info.get("private")),
                                              decided=decided)
            except (APIError, OutOfBudget) as exc:
                notes.append(f"Could not comment on pull requests ({exc}); add `pull-requests: write` to the workflow permissions.")
        if issues:
            try:
                counts = sync_issues(api, result, mention_owners=mention_owners, assign_owners=assign_owners,
                                     linear=bool((((settings or {}).get("connectors") or {}).get("linear") or {}).get("teams")))
                notes.append(f"Flaky-test issues: {counts['created']} opened, {counts['updated']} updated, {counts['closed']} closed, "
                             f"{counts['reopened']} reopened, {counts['kept_closed']} left closed as not planned.")
            except (APIError, OutOfBudget) as exc:
                notes.append(f"Could not update flaky-test issues ({exc}); add `issues: write` to the workflow permissions.")
        if tickets.get("tickets"):
            notes.append(f"{tickets['tickets'].title()} tickets: {len(tickets.get('opened') or [])} opened, "
                         f"{len(tickets.get('closed') or [])} closed" + (f"; {tickets['problem']}" if tickets.get("problem") else "") + ".")
        auto = (settings or {}).get("automation") or {}
        if auto.get("fix_requests"):
            from stackvitals.ci.selfheal import sync_fix_requests
            try:
                fixes = sync_fix_requests(api, result, assign="copilot" if auto.get("fix_by_copilot") else None,
                                          branch=info.get("default_branch"))
                out["fix_requests"] = fixes
                notes.append(f"Fix requests: {fixes['created']} opened ({fixes['assigned']} assigned to Copilot), "
                             f"{fixes['verified']} verified fixed and closed, {fixes['reopened']} reopened, {fixes['updated']} "
                             f"updated" + (f", {fixes['held']} waiting for the next run" if fixes["held"] else "") + ".")
            except (APIError, OutOfBudget) as exc:
                notes.append(f"Could not update fix requests ({exc}); add `issues: write` to the workflow permissions.")
        from stackvitals.core import chat
        # Each owning team with its own webhook hears about its tests; the rest go to the repo's webhook.
        for hook, names in chat.route(owners_of(fresh, result), {**env, "STACKVITALS_WEBHOOK": webhook or ""}).items():
            app = chat.app_url(repo, info, "ci")
            links = [("Open CI health", app)] if app else [("Workflow runs", f"https://github.com/{repo}/actions")]
            # The data is committed by now; a chat service being down must not fail the run, only be reported.
            failed = send_alert(hook, alert_message(names, repo, result, links))
            if failed:
                notes.append(failed)
        if fresh:
            from stackvitals.core import events as outbound
            notes += outbound.send(outbound.newly_flaky(fresh, repo, now.strftime("%Y-%m-%dT%H:%M:%SZ")), settings, env)
        summary = env.get("GITHUB_STEP_SUMMARY")
        sharing = (settings or {}).get("benchmarks") or {}
        if sharing.get("share"):
            # Opt-in: a link a person opens to file this month's rounded figures; the Action itself sends nothing.
            from stackvitals.ci import share
            notes.append(share.summary_line(share_doc))
        if summary:
            note = "" if stats["complete"] else "\n\nStill filling in older history (GitHub's hourly limit); the next run continues."
            with open(summary, "a", encoding="utf-8") as f:
                f.write(render_markdown(result, repo) + note + "".join(f"\n\n{n}" for n in notes) + "\n")
    ws.after_commit(after_commit, LABEL)
    return out


def run_action(env: dict, now: datetime | None = None, days: int = 90, window_days: int = 30,
               retention_days: int = 180, budget: int = 800, exclude: list[str] | None = None,
               make_api=ActionsAPI, tests: bool = True, artifact_pattern: str | None = None,
               pr_comments: bool = True, rerun_flaky: bool = False, quarantine: bool = False,
               issues: bool = False, webhook: str | None = None, mention_owners: bool = False, workspace=None,
               assign_owners: bool = False, verdict_check: bool = False) -> dict:
    """One StackVitals CI run inside GitHub Actions: collect, store in the data branch, rebuild the dashboard.
    With a shared workspace the job commits once for every module; alone, this does its own checkout and commit."""
    from stackvitals.core.workspace import run_job
    now = now or datetime.now(timezone.utc)

    def step(ws):
        return ci_step(ws, env, now, days, window_days, retention_days, budget, exclude, make_api, tests, artifact_pattern,
                       pr_comments, rerun_flaky, quarantine, issues, webhook, mention_owners, assign_owners, verdict_check)
    if workspace is not None:
        return step(workspace)
    from stackvitals.core.settings import prepare
    job = run_job(env, [(LABEL, step)], now, message=f"stackvitals: CI data {now:%Y-%m-%d %H:%M} UTC", catch=False,
                  prepare=prepare(env, make_api))
    return {**job["results"][LABEL], "pushed": job["outcome"] == "pushed", "unchanged": job["outcome"] == "unchanged"}
