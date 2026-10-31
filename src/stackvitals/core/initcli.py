"""`stackvitals init owner/repo`: the app's Setup page from a terminal. It commits the workflow (or opens a pull request
when the branch is protected), watches the first run, checks the data branch and turns on Pages for a public repo. A
private repo keeps Pages off, since a Pages site is public on most plans; its dashboard opens with `stackvitals ui`."""
from __future__ import annotations

import argparse
import base64
import sys
import time
from collections.abc import Callable
from urllib.parse import quote

import httpx

from stackvitals.ci import cli as ci_cli
from stackvitals.ci.api import API

FILE = ".github/workflows/stackvitals.yml"
DATA_BRANCH = "stackvitals-data"
SETUP_BRANCH = "stackvitals-setup"
TOKEN_PAGE = "https://github.com/settings/personal-access-tokens/new"


class Stop(Exception):
    """A step that can't go on; the message says what to do."""


class GitHub:
    def __init__(self, token: str, client: httpx.Client | None = None):
        self.client = client or httpx.Client(timeout=httpx.Timeout(60.0, connect=15.0), follow_redirects=True)
        self.headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                        "User-Agent": "stackvitals", "Authorization": f"Bearer {token.strip()}"}

    def call(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict, httpx.Headers]:
        try:
            r = self.client.request(method, f"{API}{path}", headers=self.headers, json=body)
        except httpx.TransportError as exc:
            raise Stop(f"Couldn't reach GitHub ({type(exc).__name__}). Check your connection and run it again.") from None
        try:
            data = r.json() if r.content else {}
        except ValueError:
            data = {}
        return r.status_code, data if isinstance(data, dict) else {"items": data}, r.headers


def site_url(repo: str) -> str:
    owner, name = repo.split("/")
    if name.lower() == f"{owner.lower()}.github.io":
        return f"https://{owner.lower()}.github.io/"
    return f"https://{owner.lower()}.github.io/{name}/"


def _protected(status: int, data: dict) -> bool:
    return status in (403, 409, 422) and any(w in str(data.get("message", "")).lower() for w in ("protect", "rule", "pull request"))


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _text(data: dict) -> str:
    try:
        return base64.b64decode(data.get("content") or "").decode("utf-8")
    except ValueError:
        return ""


def _open_pr(gh: GitHub, repo: str, base: str, yaml: str, update: bool) -> str:
    owner = repo.split("/")[0]
    st, ref, _ = gh.call("GET", f"/repos/{repo}/git/ref/heads/{quote(base, safe='')}")
    if st != 200:
        raise Stop(f"Couldn't read {base} to open a pull request: {ref.get('message', st)}.")
    st, made, _ = gh.call("POST", f"/repos/{repo}/git/refs", {"ref": f"refs/heads/{SETUP_BRANCH}", "sha": ref["object"]["sha"]})
    if st >= 400 and "already exists" not in str(made.get("message", "")).lower():
        raise Stop(f"Couldn't make the {SETUP_BRANCH} branch: {made.get('message', st)}.")
    st, there, _ = gh.call("GET", f"/repos/{repo}/contents/{FILE}?ref={SETUP_BRANCH}")
    if not (st == 200 and _text(there) == yaml):
        body = {"message": "Update the StackVitals workflow" if update else "Add the StackVitals workflow",
                "content": _b64(yaml), "branch": SETUP_BRANCH, **({"sha": there["sha"]} if st == 200 else {})}
        st, put, _ = gh.call("PUT", f"/repos/{repo}/contents/{FILE}", body)
        if st >= 400:
            raise Stop(f"Couldn't write the file on {SETUP_BRANCH}: {put.get('message', st)}.")
    st, found, _ = gh.call("GET", f"/repos/{repo}/pulls?state=open&head={quote(owner + ':' + SETUP_BRANCH, safe='')}")
    if st == 200 and found.get("items"):
        return found["items"][0]["html_url"]
    st, pr, _ = gh.call("POST", f"/repos/{repo}/pulls", {
        "title": "Update StackVitals" if update else "Add StackVitals", "head": SETUP_BRANCH, "base": base,
        "body": "Adds `.github/workflows/stackvitals.yml`, set up with `stackvitals init`. Merging it starts the first run."})
    if st >= 400:
        raise Stop(f"Couldn't open the pull request: {pr.get('message', st)}.")
    return pr["html_url"]


def run_init(repo: str, yaml: str, gh: GitHub, say: Callable[[str], None], wait: bool = True, replace: bool = False,
             sleep: Callable[[float], None] = time.sleep, max_minutes: float = 30.0, poll: float = 5.0) -> int:
    st, info, _ = gh.call("GET", f"/repos/{repo}")
    if st == 404:
        raise Stop(f"{repo} wasn't found, or your token can't see it. Check the name, or sign in again: gh auth login")
    if st >= 400:
        raise Stop(f"Couldn't read {repo}: {info.get('message', st)}.")
    branch, private = info.get("default_branch") or "main", bool(info.get("private"))
    perms = info.get("permissions") or {}
    if perms and not (perms.get("push") or perms.get("admin") or perms.get("maintain")):
        raise Stop(f"You can read {repo} but not write to it; ask a maintainer to run this, or to add you.")
    say(f"Setting up StackVitals in {repo} ({'private' if private else 'public'}, default branch {branch})")

    # 1. The workflow file on the default branch; a pull request when the branch is protected or a different file is there.
    st, cur, _ = gh.call("GET", f"/repos/{repo}/contents/{FILE}?ref={quote(branch, safe='')}")
    head_sha = None
    if st == 200 and _text(cur) == yaml:
        say(f"  1. Workflow file: already there ({FILE})")
    elif st == 200 and not replace:
        url = _open_pr(gh, repo, branch, yaml, update=True)
        say(f"  1. A different {FILE} is already there, so a pull request has the new one: {url}")
        say("     Review and merge it, then run this command again to finish.")
        return 0
    else:
        body = {"message": "Update the StackVitals workflow" if st == 200 else "Add the StackVitals workflow",
                "content": _b64(yaml), "branch": branch, **({"sha": cur["sha"]} if st == 200 else {})}
        put_st, put, _ = gh.call("PUT", f"/repos/{repo}/contents/{FILE}", body)
        if put_st < 400:
            head_sha = (put.get("commit") or {}).get("sha")
            say(f"  1. Workflow file: committed to {branch}")
        elif _protected(put_st, put):
            url = _open_pr(gh, repo, branch, yaml, update=st == 200)
            say(f"  1. {branch} is protected, so a pull request has the file: {url}")
            say("     Merge it, then run this command again to finish.")
            return 0
        elif put_st in (403, 404):
            raise Stop("GitHub refused to add the file. Your token needs Contents and Workflows (read and write) on "
                       f"{repo}: run `gh auth refresh -s workflow`, or make a token at {TOKEN_PAGE}")
        else:
            raise Stop(f"Couldn't commit the file: {put.get('message', put_st)}.")

    # 2. The first run: the commit's own run, one already going, else a dispatch.
    runs_path = f"/repos/{repo}/actions/workflows/stackvitals.yml/runs?per_page=10"

    def find(match) -> dict | None:
        for i in range(12):
            st, body, _ = gh.call("GET", runs_path)
            hits = sorted((r for r in (body.get("workflow_runs") or []) if match(r)), key=lambda r: r["id"]) if st == 200 else []
            if hits:
                return hits[0]
            if i < 11:
                sleep(3)
        return None

    found = find(lambda r: r.get("head_sha") == head_sha) if head_sha else None
    if not found:
        found = find(lambda r: r.get("status") in ("queued", "in_progress"))
    if not found:
        started = None
        for i in range(6):
            st, body, hdr = gh.call("POST", f"/repos/{repo}/actions/workflows/stackvitals.yml/dispatches", {"ref": branch})
            if st < 400:
                started = time.time()
                break
            if st == 403:
                raise Stop("GitHub refused to start the workflow; your token needs Actions (read and write) on " + repo)
            sleep(2 * (i + 1))
        if started is None:
            raise Stop("GitHub hasn't registered the workflow yet. Wait a minute and run this command again.")
        found = find(lambda r: r.get("event") == "workflow_dispatch")
        if not found:
            say("  2. First run: started; GitHub hasn't listed it yet. Run this command again in a minute to follow it.")
            return 0
    say(f"  2. First run: {found.get('html_url', '')}")
    if not wait:
        say("     Not waiting for it (--no-wait). Run this command again later to finish the setup.")
        return 0
    until, last = time.time() + max_minutes * 60, None
    while True:
        st, r, _ = gh.call("GET", f"/repos/{repo}/actions/runs/{found['id']}")
        if st >= 400:
            raise Stop(f"Couldn't read the run: {r.get('message', st)}.")
        if r.get("status") == "completed":
            if r.get("conclusion") != "success":
                raise Stop(f"The first run ended: {r.get('conclusion')}. Its summary names what to fix: {r.get('html_url')}")
            say("     Finished.")
            break
        if r.get("status") != last:
            last = r.get("status")
            say("     Queued: waiting for a runner" if last == "queued" else "     Running (a first run takes about a minute on a small repo)")
        if time.time() > until:
            say(f"     Still running after {max_minutes:.0f} minutes. Run this command again to keep following it.")
            return 0
        sleep(poll)

    # 3. The data branch the run writes.
    for i in range(4):
        if gh.call("GET", f"/repos/{repo}/branches/{DATA_BRANCH}")[0] == 200:
            break
        sleep(3)
    else:
        raise Stop(f"The run finished but no {DATA_BRANCH} branch is there. Its summary says why: {found.get('html_url')}")
    say(f"  3. Data: written to the {DATA_BRANCH} branch")

    # 4. Pages for a public repo; a private repo keeps its data private.
    if private:
        say("  4. Web page: kept off, because a GitHub Pages site is public on most plans and this repo is private.")
        say("")
        say("Done. Open your dashboard on this machine (your data stays in your private repo):")
        say(f"    stackvitals ui {repo}")
        return 0
    st, pages, _ = gh.call("GET", f"/repos/{repo}/pages")
    source = (pages.get("source") or {}) if st == 200 else {}
    ours = st == 200 and pages.get("build_type") != "workflow" and source.get("branch") == DATA_BRANCH and source.get("path") == "/docs"
    if st == 200 and not ours:
        say("  4. Web page: Pages already serves something else in this repo, so it's kept as it is.")
        say("")
        say(f"Done. Open your dashboard on this machine: stackvitals ui {repo}")
        return 0
    if st == 404:
        st, made, _ = gh.call("POST", f"/repos/{repo}/pages", {"source": {"branch": DATA_BRANCH, "path": "/docs"}})
        if st >= 400 and st != 409:
            say(f"  4. Web page: couldn't turn on Pages ({made.get('message', st)}). Turn it on in Settings, Pages: "
                f"branch {DATA_BRANCH}, folder /docs: https://github.com/{repo}/settings/pages")
            return 1
    url = (pages.get("html_url") if st == 200 else None) or site_url(repo)
    say("  4. Web page: on (GitHub publishes it within a minute or two)")
    say("")
    say(f"Done. Your dashboard: {url}")
    return 0


def main(argv: list[str] | None = None, client: httpx.Client | None = None, sleep: Callable[[float], None] = time.sleep) -> int:
    p = argparse.ArgumentParser(prog="stackvitals init", description="Set up StackVitals in one of your repos: commit the "
                                "workflow, run it once, and turn on the dashboard (Pages for a public repo; "
                                "`stackvitals ui` for a private one).")
    p.add_argument("repo", help="owner/name")
    p.add_argument("--modules", default=",".join(ci_cli.MODULES), help="the modules to install, comma-separated (ci, flow, deps, community)")
    p.add_argument("--no-wait", action="store_true", help="commit and start the first run, without waiting for it")
    p.add_argument("--replace", action="store_true", help="commit over a different stackvitals.yml (otherwise a pull request has it)")
    p.add_argument("--ref", default=ci_cli.ACTION_REF, help=argparse.SUPPRESS)
    args = p.parse_args(argv)
    repo = args.repo.strip().strip("/")
    if repo.count("/") != 1 or not all(repo.split("/")):
        print(f'"{args.repo}" isn\'t a repo name; use owner/name.', file=sys.stderr)
        return 2
    chosen = tuple(m.strip() for m in args.modules.split(",") if m.strip())
    if not chosen or set(chosen) - set(ci_cli.MODULES):
        print(f"--modules takes some of {', '.join(ci_cli.MODULES)}", file=sys.stderr)
        return 2
    tok = ci_cli.token()
    if not tok:
        print("Sign in to GitHub first: gh auth login (or set GITHUB_TOKEN). Nothing was changed.", file=sys.stderr)
        return 2
    gh = GitHub(tok, client)
    try:
        names = None
        try:
            names = ci_cli.ci_guess(ci_cli.workflow_names(ci_cli.ActionsAPI(tok, repo, client=client))) or None
        except Exception:
            names = None
        yaml = ci_cli.workflow_template(args.ref, names, modules=chosen)
        return run_init(repo, yaml, gh, print, wait=not args.no_wait, replace=args.replace, sleep=sleep)
    except Stop as exc:
        print(f"Stopped: {exc}", file=sys.stderr)
        return 1
