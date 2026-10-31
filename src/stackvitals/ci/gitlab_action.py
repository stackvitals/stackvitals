"""StackVitals inside GitLab CI: the job in a pipeline's last stage reads the project's finished pipelines, keeps them in
a stackvitals-data branch of the project, writes the CI Health pages into public/ for GitLab Pages, and notes a merge
request whose pipeline failed (known flake, failing on the default branch too, or likely from this change).

    stackvitals ci gitlab-action          # in GitLab CI (templates/gitlab/stackvitals.yml)

Needs a CI/CD variable GITLAB_TOKEN: a project access token with the api and write_repository scopes."""
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit

from stackvitals.ci.action import BRANCH, DataBranch, GitError, write_outputs
from stackvitals.ci.analyze import analyze
from stackvitals.ci.api import APIError, OutOfBudget
from stackvitals.ci.feedback import MARKER, classify_run, render_comment
from stackvitals.ci.gitlab import API, GitLab, collect, records
from stackvitals.ci.store import DataStore
from stackvitals.core.webapp import write_webapp

RETRIES = 3
PASSING = f"{MARKER}\n### StackVitals: CI is passing now\nThe latest run passed."
CHECK = (f"check that {BRANCH} is not a protected branch and no push rule or hook blocks it, and that GITLAB_TOKEN "
         "has the write_repository scope")


def _remote_url(env: dict, token: str) -> str:
    # The server's own scheme, host, port and path (self-managed GitLab), with the token as the password.
    url = urlsplit((env.get("CI_SERVER_URL") or "https://gitlab.com").rstrip("/"))
    return f"{url.scheme}://oauth2:{quote(token, safe='')}@{url.netloc}{url.path}/{env['CI_PROJECT_PATH']}.git"


def _mr_iid(env: dict) -> str | None:
    # A merge request pipeline names its MR; a branch pipeline lists open ones as "group/project!12,group/other!3".
    if env.get("CI_MERGE_REQUEST_IID"):
        return env["CI_MERGE_REQUEST_IID"]
    for entry in (env.get("CI_OPEN_MERGE_REQUESTS") or "").split(","):
        path, _, iid = entry.strip().rpartition("!")
        if path == env.get("CI_PROJECT_PATH") and iid:
            return iid
    return None


def _note(lab: GitLab, iid: str, body: str | None) -> str | None:
    # One note per merge request, edited on later pipelines, like the pull request comment on GitHub.
    mine = [n for n in lab.pages(f"/merge_requests/{iid}/notes", {"sort": "asc"}, limit=20) if MARKER in (n.get("body") or "")]
    if mine:
        lab.send("PUT", f"/merge_requests/{iid}/notes/{mine[0]['id']}", {"body": body or PASSING})
        return "updated"
    if body is None:
        return None  # passing and never noted: nothing to say
    lab.send("POST", f"/merge_requests/{iid}/notes", {"body": body})
    return "created"


def run(env: dict, now: datetime | None = None, make_lab=GitLab, remote: str | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    project, token = env.get("CI_PROJECT_PATH"), env.get("GITLAB_TOKEN")
    if not project:
        raise SystemExit("This runs inside GitLab CI (templates/gitlab/stackvitals.yml); to read a project from here, "
                         "use: stackvitals ci gitlab group/project")
    if not token:
        raise SystemExit("Set a GITLAB_TOKEN CI/CD variable: a project access token with api and write_repository.")
    lab = make_lab(project, token=token, base=env.get("CI_API_V4_URL") or API)
    remote = remote or _remote_url(env, token)
    work = Path(tempfile.mkdtemp(prefix="stackvitals-gitlab-"))
    try:
        for attempt in range(RETRIES):
            branch = DataBranch(remote, BRANCH, work / f"data{attempt}")
            branch.open()
            store = DataStore(branch.path)
            got = collect(lab, store, now, days=int(env.get("STACKVITALS_DAYS") or 14))
            data = store.load()
            default = store.state().get("default_branch") or env.get("CI_DEFAULT_BRANCH")
            result = analyze(data, now, window_days=30, default_branch=default)
            write_webapp(branch.path / "docs")  # the app at the site's front door, as on GitHub Pages
            write_outputs(branch.path, result, project)
            try:
                outcome = branch.commit_push(f"stackvitals: GitLab CI data {now:%Y-%m-%d %H:%M} UTC")
            except GitError as exc:
                raise SystemExit(f"Could not save the CI history: {exc}. To fix: {CHECK}.") from None
            if outcome != "rejected":
                break
            time.sleep(2 * (attempt + 1))
        else:
            raise SystemExit(f"Could not save the CI history: the push to {BRANCH} was turned down {RETRIES} times. "
                             f"If no other pipeline was saving at the same moment, {CHECK}.")
        out = {"pipelines": got["pipelines"], "stopped": got["stopped"], "outcome": outcome, "note": None}
        # This pipeline is still running (the job is in it), so its failed jobs are read here, not from the history.
        iid, pid = _mr_iid(env), env.get("CI_PIPELINE_ID")
        if iid and pid:
            try:
                pipeline = {**lab.get(f"/pipelines/{pid}"), "status": "failed"}
                jobs = [j for j in lab.pages(f"/pipelines/{pid}/jobs", {"include_retried": "true"}, limit=5)
                        if j.get("name") != env.get("CI_JOB_NAME")]
                recs = records(pipeline, jobs)
                live = {"runs": data["runs"] + [r for r in recs if r["t"] == "run"],
                        "jobs": data["jobs"] + [r for r in recs if r["t"] == "job"], "tests": data.get("tests") or []}
                items = classify_run(live, {**result, "default_branch": default}, int(pid))
                if items:
                    # GitLab has no StackVitals verdict check, so the GitHub sentence about it goes.
                    body = render_comment(items, project, pipeline.get("sha")).replace(
                        " The StackVitals verdict passes once CI is green.", "")
                    out["note"] = _note(lab, iid, body)
                elif max((r for r in recs if r["t"] == "run"), key=lambda r: r["att"], default={}).get("c") == "success":
                    # Green now: an old failure note says so, and no note is started.
                    out["note"] = _note(lab, iid, None)
            except (APIError, OutOfBudget) as exc:
                out["note"] = f"not posted ({exc}); the token needs the api scope"
        pages = Path(env.get("STACKVITALS_PAGES_DIR") or "public")
        if (branch.path / "docs").is_dir():
            shutil.copytree(branch.path / "docs", pages, dirs_exist_ok=True)
        return out
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    import json
    import os
    out = run(dict(os.environ))
    print(json.dumps(out, indent=1))
    return 0
