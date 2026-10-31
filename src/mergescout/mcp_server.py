import json
import os
import sys
import threading
from datetime import datetime
from pathlib import Path

import httpx
from mcp.server.mcpserver import MCPServer

from mergescout.github.releases import ReleaseError, Releases
from mergescout.tool.action_pack import build_action_pack
from mergescout.tool.live import GitHubLive, LiveError
from mergescout.tool.queries import Snapshot
from mergescout.tool.refs import parse_ref
from mergescout.tool.store import DEFAULT_REPO, SnapshotStore, data_token, home
from mergescout.tool.tracking import Tracker

TOOL_NAMES = ("find_issues", "action_pack", "repo_health", "repos_needing_help", "check_issue", "similar_issues",
              "explain", "track", "report_outcome")
INSTRUCTIONS = ("MergeScout answers from a daily snapshot of GitHub repos: which open issues an outsider can "
                "realistically get merged, with evidence (merge rates with sample sizes, review times, walls). "
                "Call check_issue before telling someone an issue is free. Quote the evidence and say "
                "'not enough evidence' whenever a result does.")


class NoSnapshot(RuntimeError):
    pass


class App:
    def __init__(self, root: Path | None = None, releases=None, live=None, log=None):
        self.root = root or home()
        self.log = log or (lambda msg: print(msg, file=sys.stderr))
        repo = os.environ.get("MERGESCOUT_DATA_REPO", DEFAULT_REPO)
        self.store = SnapshotStore(self.root, releases or Releases(data_token(), repo))
        self.live = live or GitHubLive(data_token())
        self.tracker = Tracker(self.root)
        self._snap = None
        # Tools run in worker threads; only one of them may check for and download a snapshot.
        self._lock = threading.Lock()

    def snapshot(self) -> Snapshot:
        with self._lock:
            if self._snap is None:
                path = self.store.ensure(log=self.log)
                if path is None:
                    raise NoSnapshot("No issue snapshot is available yet: it isn't published for outside use. "
                                     "Maintainers with access to the private data set MERGESCOUT_TOKEN, then run "
                                     "`mergescout update`.")
                self._snap = Snapshot(path)
            return self._snap


def plain(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPError):
        return f"Could not reach GitHub (network problem: {exc}). Answers from the snapshot still work."
    if isinstance(exc, ReleaseError):
        return (f"Could not read the issue snapshot ({exc}). It isn't published for outside use yet; maintainers "
                "with access to the private data set MERGESCOUT_TOKEN.")
    return str(exc)


def _safe(fn):
    # Agents read plain answers better than stack traces.
    def run(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (NoSnapshot, LiveError, ValueError, httpx.HTTPError, ReleaseError) as exc:
            return {"error": plain(exc)}
    run.__name__, run.__doc__ = fn.__name__, fn.__doc__
    return run


def live_status(app: App, ref) -> dict:
    status = app.live.issue_status(ref.owner, ref.name, ref.number)
    if status.get("linked_open_prs") is not None:
        return status
    # Without a token GitHub hides linked PRs; keep the open PR the snapshot last saw.
    try:
        snap = app.snapshot()
    except NoSnapshot:
        return status
    row = snap.issue(ref.repo, ref.number)
    if row and row["linked_open_prs"]:
        status = {**status, "linked_open_prs": row["linked_open_prs"], "available": False,
                  "reasons": status.get("reasons", []) + [f"open PR (seen in the snapshot of {snap.built_at})"]}
    return status


def verify_live(app: App, out: dict, limit: int) -> dict:
    # Real queries (2026-10-16): 7 of 60 snapshot results were taken within a day; check the list in one call.
    refs = [parse_ref(r["issue"]) for r in out["results"]]
    try:
        statuses = app.live.issue_statuses([(f.owner, f.name, f.number) for f in refs])
    except Exception as exc:  # noqa: BLE001 - any odd answer falls back to the snapshot list
        out["results"] = out["results"][:limit]
        out["note"] += f" Live check failed ({plain(exc)}); availability is from the snapshot."
        return out
    kept, taken, gone = [], 0, 0
    for r, f in zip(out["results"], refs):
        s = statuses.get((f.owner, f.name, f.number))
        if s is None or not s["available"]:
            taken += s is not None
            gone += s is None
            continue
        r = {**r, "checked_live": True}
        if s["older_claims"]:
            r["earlier_claims"] = (f"{len(s['older_claims'])} older offer(s) to work on it, the last on "
                                   f"{s['older_claims'][-1]['at'][:10]}; ask on the issue before starting")
        if s.get("note"):
            r["live_note"] = s["note"]
        kept.append(r)
    out["note"] = (f"Checked live on GitHub just now: {taken} of {len(refs)} candidates are taken or not ready and "
                   f"{gone} no longer exist; they are left out.")
    out["results"] = kept[:limit]
    return out


def build_server(app: App) -> MCPServer:
    server = MCPServer("mergescout", instructions=INSTRUCTIONS)

    @server.tool()
    def find_issues(language: str | None = None, topic: str | None = None, beginner_labels_only: bool = False,
                    min_score: float = 0.0, allow_walls: bool = True, fresh: bool = False, limit: int = 10,
                    detail: bool = False) -> dict:
        """Open issues an outsider can likely get merged, best first, each with its evidence.
        topic: plain words matched against titles, labels and bodies. allow_walls=False hides repos with a CLA,
        DCO, issue-first rule or AI ban. fresh=True also lists beginner issues opened after the snapshot."""
        return _safe(_find)(language, topic, beginner_labels_only, min_score, allow_walls, fresh, limit, detail)

    def _find(language, topic, beginner_labels_only, min_score, allow_walls, fresh, limit, detail):
        snap = app.snapshot()
        limit = max(1, min(limit, 50))
        # With a token, twice the candidates are read so the list stays full after taken ones are dropped.
        live = bool(getattr(app.live, "token", None))
        out = snap.find_issues(language, topic, beginner_labels_only, min_score, allow_walls,
                               min(limit * 2, 50) if live else limit, detail)
        if live and out["results"]:
            out = verify_live(app, out, limit)
        if fresh:
            since = datetime.fromisoformat(snap.built_at.replace("Z", "+00:00"))
            try:
                out["fresh"] = snap.with_repo_stats(app.live.fresh_issues(language, since, limit))[:limit]
            except (LiveError, httpx.HTTPError) as exc:
                out["fresh"], out["fresh_note"] = [], f"fresh lane unavailable: {plain(exc)}"
        return out

    @server.tool()
    def action_pack(issue: str) -> dict:
        """Everything needed to start on one issue: live status, what it asks, accepted outsider PRs to copy,
        the project's rules as a checklist, a size hint and next steps. issue: owner/name#number or a URL."""
        def run():
            ref = parse_ref(issue)
            try:
                status, failed = live_status(app, ref), None
            except (LiveError, httpx.HTTPError) as exc:
                status, failed = None, plain(exc)
            pack = build_action_pack(app.snapshot(), ref, status)
            if failed:
                pack["status"]["note"] = f"live check failed ({failed}); status is from the snapshot of {app.snapshot().built_at}"
            return pack
        return _safe(run)()

    @server.tool()
    def repo_health(repo: str, detail: bool = False) -> dict:
        """How outsiders fare in one repo: merge rates with sample sizes, review time, walls, how to reach it."""
        def run():
            out = app.snapshot().repo_health(parse_ref(repo).repo, detail)
            return out or {"error": f"{repo} is not in the snapshot (not crawled yet or too inactive)."}
        return _safe(run)()

    @server.tool()
    def repos_needing_help(language: str | None = None, limit: int = 10) -> dict:
        """Repos that merge outsider PRs but have very few active maintainers."""
        return _safe(lambda: app.snapshot().repos_needing_help(language, limit))()

    @server.tool()
    def check_issue(issue: str) -> dict:
        """Live check on GitHub right now: open, assigned, linked PRs, recent claims, maintainer 'please wait'."""
        def run():
            return live_status(app, parse_ref(issue))
        return _safe(run)()

    @server.tool()
    def similar_issues(issue: str, limit: int = 5) -> dict:
        """Free issues whose titles share words with this one (keyword match)."""
        def run():
            ref = parse_ref(issue)
            return app.snapshot().similar_issues(ref.repo, ref.number, limit)
        return _safe(run)()

    @server.tool()
    def explain(issue: str) -> dict:
        """The full evidence record behind an issue's score: counts, ranges, windows, exclusions and notes."""
        def run():
            ref = parse_ref(issue)
            return app.snapshot().explain(ref.repo, ref.number) or {"error": f"{ref.key} is not in the snapshot."}
        return _safe(run)()

    @server.tool()
    def track(issue: str | None = None, untrack: bool = False) -> dict:
        """Track an issue (stored on this machine); untrack=True stops tracking it.
        Without an issue: list tracked issues and what changed since the last look."""
        def run():
            if issue and untrack:
                app.tracker.untrack(parse_ref(issue).key)
            elif issue:
                ref = parse_ref(issue)
                app.tracker.track(ref.key, live_status(app, ref))
            return {"tracked": sorted(app.tracker.tracked()), "changes": [] if issue else app.tracker.updates(app.live)}
        return _safe(run)()

    @server.tool()
    def report_outcome(issue: str, outcome: str, note: str = "") -> dict:
        """Record what happened (started, pr_opened, merged, closed_unmerged, abandoned, taken_by_someone_else).
        Kept on this machine only."""
        return _safe(lambda: app.tracker.report_outcome(parse_ref(issue).key, outcome, note))()

    @server.resource("corpus://stats", mime_type="application/json")
    def stats() -> str:
        """Snapshot date and coverage."""
        try:
            return json.dumps(app.snapshot().stats())
        except NoSnapshot as exc:
            return json.dumps({"error": str(exc)})

    return server
