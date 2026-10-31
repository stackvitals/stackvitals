"""`stackvitals ui owner/repo`: a repo's StackVitals pages on your machine, Explore included, from a local copy of its
stackvitals-data branch. Private repos and self-hosters get the full dashboard without Pages; nothing is served beyond
127.0.0.1."""
import argparse
import base64
import functools
import os
import subprocess
import sys
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from stackvitals.ci import cli as ci_cli
from stackvitals.ci.action import BRANCH


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):  # one line per file would bury the address
        pass


def _git(args: list[str], tok: str | None, remote: str | None) -> subprocess.CompletedProcess:
    # The token goes in a header for this one command, through its environment: never the copy's config or the process list.
    env = None
    if tok and not remote:
        basic = base64.b64encode(f"x-access-token:{tok}".encode()).decode()
        env = dict(os.environ)
        try:
            n = int(env.get("GIT_CONFIG_COUNT") or 0)
        except ValueError:
            n = 0
        env.update({"GIT_CONFIG_COUNT": str(n + 1), f"GIT_CONFIG_KEY_{n}": "http.extraheader",
                    f"GIT_CONFIG_VALUE_{n}": f"AUTHORIZATION: basic {basic}"})
    return subprocess.run(["git", *args], capture_output=True, text=True, env=env)


def fetch(repo: str, tok: str | None, folder: Path, remote: str | None = None) -> Path:
    """A shallow copy of the data branch in `folder`, brought up to date (the branch may have been squashed and
    force-pushed, so the copy follows it rather than merging)."""
    folder = Path(folder)
    url = remote or f"https://github.com/{repo}.git"
    if (folder / ".git").is_dir():
        done = _git(["-C", str(folder), "fetch", "--depth", "1", url, BRANCH], tok, remote)
        if done.returncode == 0:
            _git(["-C", str(folder), "reset", "--hard", "FETCH_HEAD"], None, None)
            return folder
    folder.parent.mkdir(parents=True, exist_ok=True)
    done = _git(["clone", "--quiet", "--depth", "1", "--branch", BRANCH, "--single-branch", url, str(folder)], tok, remote)
    if done.returncode != 0:
        raise RuntimeError(f"no {BRANCH} branch to read in {repo} (does StackVitals run there, and can your token read it?)")
    return folder


def serve(folder: Path, port: int = 0) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), functools.partial(_Quiet, directory=str(folder)))


def first_page(docs: Path) -> str | None:
    """The page to open: the app's home when there is one, else the first module page the branch has (Portal alone too)."""
    from stackvitals import shell
    return next((p for p in ("index.html", *(name for name, _ in shell.MODULES)) if (Path(docs) / p).is_file()), None)


def _run_job(argv: list[str], env: dict) -> int:
    # The Action's own job, in this process, with the environment a GitHub run would have.
    import os
    from stackvitals.ci.cli import action_main
    saved = dict(os.environ)
    os.environ.update(env)
    try:
        return action_main(argv)
    finally:
        os.environ.clear()
        os.environ.update(saved)


def collect_locally(repo: str, tok: str | None, home: Path, days: int = 90) -> str:
    """Runs the Action's job on this machine into a local data branch (a bare repo under `home`), reading GitHub with the
    given token and never writing to it. Returns the local remote's URL."""
    import tempfile
    bare = Path(home) / "local" / f"{repo.replace('/', '__')}.git"
    if not (bare / "HEAD").exists():
        bare.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    env = {"GITHUB_REPOSITORY": repo, "STACKVITALS_TOKEN": tok or "", "GITHUB_TOKEN": tok or "", "STACKVITALS_REMOTE": str(bare),
           "GITHUB_EVENT_NAME": "schedule", "STACKVITALS_READ_ONLY": "1", "RUNNER_TEMP": tempfile.mkdtemp(prefix="stackvitals-")}
    code = _run_job(["--modules", "ci,flow", "--days", str(days), "--pr-comments", "false"], env)
    if code:
        raise RuntimeError(f"the local run ended with code {code}")
    # A plain path, not a file:// URL: Git Bash setups that skip path conversion misread file:///C:/... addresses.
    return str(bare)


def main(argv: list[str] | None = None, tok: str | None = None, home: Path | None = None, open_browser=webbrowser.open) -> int:
    parser = argparse.ArgumentParser(prog="stackvitals ui", description="Open a repo's StackVitals pages from a local copy.")
    parser.add_argument("repo", help="owner/name")
    parser.add_argument("--port", type=int, default=0, help="port on 127.0.0.1 (default: any free one)")
    parser.add_argument("--no-open", action="store_true", help="print the address instead of opening a browser")
    parser.add_argument("--remote", help=argparse.SUPPRESS)  # another place to clone from (tests, mirrors)
    parser.add_argument("--collect", action="store_true",
                        help="no StackVitals in the repo? read its history on this machine first (no Action, no server; nothing is written to GitHub)")
    parser.add_argument("--days", type=int, default=90, help="with --collect: days of history to read")
    args = parser.parse_args(argv)
    tok = tok if tok is not None else (None if args.remote else ci_cli.token())
    folder = Path(home or ci_cli.home()) / "ui" / args.repo.replace("/", "__")
    if args.collect and not args.remote:
        print(f"Reading {args.repo}'s history on this machine (a few minutes; nothing is written to GitHub)...", flush=True)
        try:
            args.remote = collect_locally(args.repo, tok, Path(home or ci_cli.home()), args.days)
        except Exception as exc:  # noqa: BLE001 - say what went wrong instead of a traceback
            print(f"Could not read {args.repo}: {exc}", file=sys.stderr)
            return 1
    try:
        fetch(args.repo, tok, folder, remote=args.remote)
    except RuntimeError as exc:
        print(f"Could not open {args.repo}: {exc}", file=sys.stderr)
        return 1
    if (folder / "docs").is_dir():
        # This install's app, not the copy the branch was last written with (a branch may lag a release or two).
        from stackvitals.core.webapp import write_webapp
        write_webapp(folder / "docs")
    page = first_page(folder / "docs")
    if page is None:
        print(f"{args.repo}'s {BRANCH} branch has no pages yet.", file=sys.stderr)
        return 1
    server = serve(folder, args.port)
    url = f"http://127.0.0.1:{server.server_port}/docs/{page}"
    print(f"StackVitals for {args.repo}: {url} (Explore: /docs/explore.html). Ctrl+C to stop.", flush=True)
    if not args.no_open:
        open_browser(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
