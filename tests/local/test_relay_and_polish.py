import json
import sqlite3
from datetime import datetime, timezone

import anyio
import httpx
import pytest
from mcp import Client

from mergescout.crawl.chain import next_step, write_last_run
from mergescout.crawl.state import CrawlState
from mergescout.github.releases import ReleaseError, Releases
from mergescout.mcp_server import App, build_server
from mergescout.signals.evidence import build_all
from mergescout.signals.identity import build_people, build_pr_class
from mergescout.snapshot.publish import MANIFEST, PACKED, SNAPSHOT, pack, publish
from mergescout.tool.live import GitHubLive
from mergescout.tool.queries import Snapshot
from mergescout.tool.refs import parse_ref
from mergescout.tool.tracking import Tracker

from signals_data import NOW, make_con, pr, t
from tool_data import ISSUE, REPO, make_snapshot

TODAY = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


# Relay: each run decides what runs next, so crawling no longer waits for GitHub's unreliable hourly schedule.
def relay(tmp_path, discovered="2026-10-16", repos=50, reason="time", queued=10):
    state = CrawlState(tmp_path / "crawl.sqlite", now=lambda: TODAY)
    state.upsert_repos([{"repo_id": i, "name": f"o/r{i}", "priority": 1} for i in range(queued)])
    if discovered:
        (tmp_path / "last-discover").write_text(discovered + "\n")
    write_last_run(tmp_path, {"repos": repos, "reason": reason, "points": 100, "failed": 0})
    return next_step(state, tmp_path, TODAY)


# Replacing a release file uploads the new copy before removing the old one.
def releases_with(routes, seen):
    def handler(req):
        seen.append(req)
        for method, part, resp in routes:
            if req.method == method and part in str(req.url):
                return resp(req) if callable(resp) else resp
        return httpx.Response(500, text=f"unexpected {req.method} {req.url}")
    return Releases("tok", "me/repo", client=httpx.Client(transport=httpx.MockTransport(handler)))


REL = {"id": 7, "tag_name": "crawl-state"}


def test_bundle_writes_to_folders_with_quotes(tmp_path):
    from mergescout.signals.__main__ import write_bundle
    con = make_con({"prs": [pr(1, "a")], "repo_meta": [{"repo_id": 1, "name": "o/r"}],
                    "issues": [{"repo_id": 1, "number": 2, "state": "OPEN", "labels": [], "assignees": 0}]})
    build_all(con, NOW)
    out = tmp_path / "it's here"
    out.mkdir()
    assert write_bundle(con, out).exists()


# The public crawler gets only what the crawler needs.
def test_crawler_pyproject_drops_tool_only_packages():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("sync", Path(__file__).resolve().parents[2] / "scripts" / "sync_crawler.py")
    sync = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync)
    text = (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text()
    out = sync.crawler_pyproject(text)
    assert "mcp" not in out and "zstandard" not in out and "[project.scripts]" not in out
    assert 'crawl = ["orjson>=3.10", "pyarrow>=17"]' in out and "httpx" in out
