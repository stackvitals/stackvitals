"""One checkout of the data branch per job: every module writes into it, there is one commit, and what must happen only
after the commit (re-runs, comments, issues, alerts) runs afterwards. A rejected push (another run got there first)
re-runs every step on the fresh data, so overlapping runs converge and nothing is lost."""
import os
import shutil
import stat
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from stackvitals.ci.action import BRANCH, DataBranch, GitError
from stackvitals.core.store import DEFAULT_CAP_MB, SQUASH_EVERY, STREAMS, HistoryStore

RETRIES = 3


def _rmtree(path: Path) -> None:
    # Git leaves read-only files on Windows; clear the bit and retry so no clone is left behind.
    def onerror(fn, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            fn(p)
        except OSError:
            pass
    shutil.rmtree(path, onerror=onerror)


class Workspace:
    def __init__(self, env: dict, now: datetime | None = None):
        self.env = env
        self.now = now or datetime.now(timezone.utc)
        self.repo = env["GITHUB_REPOSITORY"]
        token = env.get("STACKVITALS_TOKEN") or env.get("GITHUB_TOKEN")
        self.remote = env.get("STACKVITALS_REMOTE") or f"https://x-access-token:{token}@github.com/{self.repo}.git"
        temp_root = env.get("RUNNER_TEMP")
        if temp_root:
            Path(temp_root).mkdir(parents=True, exist_ok=True)
        self.work = Path(tempfile.mkdtemp(prefix="stackvitals-", dir=temp_root))
        self.branch: DataBranch | None = None
        self.hooks: list[tuple[str, object]] = []
        self.notes: list[str] = []
        # Side effects already done on GitHub in this job (a settings commit), kept when a rejected push retries the steps.
        self.memo: dict = {}
        self.results: dict = {}
        # Data one step loaded and a later step may reuse, for this attempt only.
        self.cache: dict = {}

    @property
    def path(self) -> Path:
        return self.branch.path

    def open(self, attempt: int = 0) -> None:
        # Hooks registered during a rejected attempt are dropped: the steps run again and register them again.
        self.hooks = []
        self.cache = {}
        from stackvitals.core.bucket import from_env
        # A bucket when STACKVITALS_STORAGE names one (s3://...), else the stackvitals-data branch.
        self.branch = from_env(self.env, self.work / f"data{attempt}") or DataBranch(self.remote, BRANCH, self.work / f"data{attempt}")
        self.branch.open()

    def after_commit(self, fn, label: str = "", first: bool = False) -> None:
        # first: the job summary opens with it (what to fix first), whichever step registered it.
        if first:
            self.hooks.insert(0, (label, fn))
        else:
            self.hooks.append((label, fn))

    def commit(self, message: str) -> str:
        return self.branch.commit_push(message)

    def run_hooks(self) -> None:
        for label, fn in self.hooks:
            try:
                fn()
            except Exception as exc:  # noqa: BLE001
                # The data is committed by now; a chat service or a comment refusal must not fail the run.
                self.notes.append(f"{label}: {exc}")

    def close(self) -> None:
        _rmtree(self.work)


def housekeeping(ws: Workspace) -> dict:
    """Retention per stream, the size cap, and the commit counter; all tunable through the Action's inputs."""
    env, store = ws.env, HistoryStore(ws.path)
    today = ws.now.date().isoformat()
    days = {}
    if env.get("STACKVITALS_RETENTION_DAYS"):
        days.update({s: int(env["STACKVITALS_RETENTION_DAYS"]) for s in STREAMS if s != "ci/days"})
    if env.get("STACKVITALS_CI_RETENTION_DAYS"):
        days["ci/days"] = int(env["STACKVITALS_CI_RETENTION_DAYS"])
    removed = store.retention(today, days)
    cap_mb = float(env.get("STACKVITALS_SIZE_CAP_MB") or DEFAULT_CAP_MB)
    dropped = store.cap(today, int(cap_mb * 1024 * 1024))
    commits = store.bump_commits() if ws.branch.dirty() else int(store.meta().get("commits") or 0)
    return {"removed": removed, "dropped": dropped, "commits": commits, "squashed": False}


# The steps that write summary/ files, which the Explore page reads.
SUMMARY_STEPS = ("CI Health", "Team Flow")


def _explore(ws, steps) -> None:
    if not any(label in SUMMARY_STEPS for label, _ in steps) and not (ws.path / "summary" / "manifest.json").exists():
        return  # a Portal-only job has nothing to explore
    try:
        from stackvitals.core.explore import write_explore
        write_explore(ws.path, ws.repo)
    except Exception as exc:  # noqa: BLE001 - an extra page must never cost the modules' data
        ws.notes.append(f"Explore page skipped ({exc}).")


def run_job(env: dict, steps: list[tuple[str, object]], now: datetime | None = None, message: str | None = None,
            catch: bool = True, prepare=None) -> dict:
    """Open the data branch once, run every step on it, keep house, commit once, then run the hooks. Returns the
    outcome (pushed, unchanged), each step's result, the errors of steps that failed, and the hooks' notes. `prepare`
    runs first on each fresh checkout (the repo's settings, shared by every step)."""
    ws = Workspace(env, now)
    try:
        for attempt in range(RETRIES):
            if attempt:
                # Two runs collided; a random, growing wait keeps them from colliding again in step.
                from stackvitals.core.bucket import backoff
                time.sleep(backoff(attempt))
            ws.open(attempt)
            if prepare is not None:
                try:
                    prepare(ws)
                except Exception as exc:  # noqa: BLE001 - the steps still run, on the defaults
                    ws.notes.append(f"Settings were not read ({exc}); the defaults were used.")
            try:
                from stackvitals.core.webapp import write_webapp
                write_webapp(ws.path / "docs")  # the app at the site's front door, before the pages that link to it
            except Exception as exc:  # noqa: BLE001 - the app's files must never cost the modules' data
                ws.notes.append(f"App files skipped ({exc}).")
            _explore(ws, steps)  # before the modules, so every page they write links to it from the first run
            results, errors = {}, {}
            ws.results = results
            for label, step in steps:
                if not catch:
                    results[label] = step(ws)
                    continue
                try:
                    results[label] = step(ws)
                except Exception as exc:  # noqa: BLE001
                    # One step's trouble must not lose the others' work; the runner reports it.
                    errors[label] = str(exc)
            _explore(ws, steps)  # and after, so its own header lists every page the modules wrote
            try:
                from stackvitals.core.appdata import write_app_data
                write_app_data(ws)  # what the app reads: what ran, settings, decisions, the tables beside the pages
            except Exception as exc:  # noqa: BLE001 - the app's files must never cost the modules' data
                ws.notes.append(f"App files skipped ({exc}).")
            house = housekeeping(ws)
            try:
                from stackvitals.core.health import write_health
                write_health(ws, results, errors, house)  # the app's Data health page
            except Exception as exc:  # noqa: BLE001 - an extra page must never cost the modules' data
                ws.notes.append(f"Data health skipped ({exc}).")
            names = ", ".join(label for label, _ in steps)
            outcome = ws.commit(message or f"stackvitals: {names} {ws.now:%Y-%m-%d %H:%M} UTC")
            if outcome != "rejected":
                break
        else:
            raise GitError("the data branch kept changing under us; the next run will catch up")
        if (env.get("STACKVITALS_SQUASH") or "").strip().lower() == "true" and house["commits"] >= SQUASH_EVERY:
            # Opt-in: the files stay byte for byte, only the git history behind them becomes one commit.
            store = HistoryStore(ws.path)
            store.save_meta({**store.meta(), "commits": 0})
            house["squashed"] = ws.branch.squash(f"stackvitals: history squashed {ws.now:%Y-%m-%d}") == "pushed"
        ws.run_hooks()
        if (env.get("STACKVITALS_STORAGE") or "git") != "git":
            ws.notes.append("History is kept in the bucket: stackvitals ui and sql, Explore, the MCP server, the Portal's org "
                            "view and quarantine in your CI read the stackvitals-data branch only, so they don't see it yet."
                            + ("" if env.get("STACKVITALS_PAGES_DIR") else " No branch publishes the app either: set pages to "
                               "deploy or artifact."))
        # Pages from the Action (opt-in): the published folder goes to the deploy steps when this job changed it.
        pages = bool(env.get("STACKVITALS_PAGES_DIR")) and outcome == "pushed" and (ws.path / "docs").is_dir()
        if pages:
            out = Path(env["STACKVITALS_PAGES_DIR"])
            shutil.copytree(ws.path / "docs", out, dirs_exist_ok=True)
            if env.get("STACKVITALS_PAGES_MODE") == "artifact":
                # A download for people who can read the repo, so Explore gets the tables a private repo's Pages leave out.
                if (ws.path / "summary").is_dir() and not (out / "summary").exists():
                    shutil.copytree(ws.path / "summary", out / "summary")
                # The app reads its files over HTTP; bound to this machine so nobody else on the network can open it.
                (out / "OPEN-ME.txt").write_text(
                    "Open the StackVitals app from this folder: run `python -m http.server 8000 --bind 127.0.0.1` here,\n"
                    "then visit http://127.0.0.1:8000/ in a browser. Opening index.html directly doesn't work: browsers block\n"
                    "its data files.\n", encoding="utf-8")
        return {"outcome": outcome, "results": results, "errors": errors, "notes": ws.notes, "housekeeping": house, "pages": pages}
    finally:
        ws.close()
