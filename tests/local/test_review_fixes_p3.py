import json
import os
import sqlite3
import threading
import time

import anyio
import httpx
from mcp import Client

from mergescout.github.releases import ReleaseError
from mergescout.mcp_server import App, build_server
from mergescout.signals.evidence import build_all
from mergescout.snapshot.build import build_snapshot
from mergescout.snapshot.publish import MANIFEST, PACKED, SNAPSHOT, pack
from mergescout.tool.action_pack import build_action_pack
from mergescout.tool.live import GitHubLive, LiveError
from mergescout.tool.queries import Snapshot
from mergescout.tool.refs import parse_ref
from mergescout.tool.store import SnapshotStore
from mergescout.tool.tracking import Tracker

from signals_data import NOW, make_con, pr, t
from tool_data import ISSUE, REPO, make_snapshot


class NoRel:
    def list_releases(self):
        raise OSError("offline")


class OkLive:
    def issue_status(self, owner, name, number):
        return {"state": "OPEN", "assignees": 0, "linked_open_prs": 0, "claims": [], "waits": [], "available": True,
                "reasons": [], "source": "fake"}

    def fresh_issues(self, language, since, limit=20):
        return []


class DownLive(OkLive):
    def issue_status(self, owner, name, number):
        raise httpx.ConnectError("no network")

    def fresh_issues(self, language, since, limit=20):
        raise httpx.ConnectError("no network")


def ready(tmp_path, live=None, issues=(ISSUE,), repos=(REPO,)):
    make_snapshot(tmp_path / SNAPSHOT, repos=repos, issues=issues)
    (tmp_path / MANIFEST).write_text(json.dumps({"sha256": "x", "built_at": "2026-10-14T05:00:00Z",
                                                 "checked_at": "2999-01-01T00:00:00Z"}))
    return App(root=tmp_path, releases=NoRel(), live=live or OkLive(), log=lambda *a: None)


def call_app(app, name, args):
    async def run():
        async with Client(build_server(app)) as c:
            return json.loads((await c.call_tool(name, args)).content[0].text)
    return anyio.run(run)


def test_live_client_follows_renames_and_reads_graphql_errors():
    assert GitHubLive(None).client.follow_redirects is True

    def handler(req):
        return httpx.Response(200, json={"data": None, "errors": [{"type": "RATE_LIMITED", "message": "API rate limit"}]})
    live = GitHubLive("tok", client=httpx.Client(transport=httpx.MockTransport(handler)))
    try:
        live.issue_status("o", "r", 1)
        raise AssertionError("expected LiveError")
    except LiveError as exc:
        assert "rate limit" in str(exc).lower() and "does not exist" not in str(exc)


def test_cli_update_without_access_says_how_to_fix(tmp_path, monkeypatch, capsys):
    from mergescout import cli

    class Denied:
        def list_releases(self):
            raise ReleaseError("listing releases failed: HTTP 404 Not Found")
    monkeypatch.setattr(cli, "App", lambda log=None: App(root=tmp_path, releases=Denied(), live=OkLive(), log=log))
    assert cli.main(["update"]) == 1
    assert "MERGESCOUT_TOKEN" in capsys.readouterr().err


# 2. Label evidence matches the issue's label however it is written.
def test_label_evidence_matches_decorated_labels(tmp_path):
    repo = {**REPO, "labels_json": '[{"label": "good first issue", "enough": true, "median_fix_lines": 24, '
                                   '"median_fix_files": 2}]'}
    snap = Snapshot(make_snapshot(tmp_path / "s.sqlite", repos=(repo,),
                                  issues=({**ISSUE, "labels": '["Good First Issue :sparkles:"]'},)))
    assert snap.explain("octo/widgets", 7)["labels"][0]["label"] == "good first issue"
    assert "24 lines" in build_action_pack(snap, parse_ref("octo/widgets#7"))["level"]


def test_a_damaged_tracking_file_is_set_aside(tmp_path):
    (tmp_path / "tracked.json").write_text("{")
    t_ = Tracker(tmp_path)
    assert t_.tracked() == {} and (tmp_path / "tracked.json.bad").exists()


def test_download_temp_names_are_per_process_and_thread(tmp_path):
    name = SnapshotStore(tmp_path, NoRel())._tmp("x.part").name
    assert str(os.getpid()) in name and str(threading.get_ident()) in name


# 9. A topic with no searchable words is said plainly; any script counts as words.
def test_topics_without_searchable_words_return_nothing_with_a_note(tmp_path):
    snap = Snapshot(make_snapshot(tmp_path / "s.sqlite"))
    out = snap.find_issues(topic="the")
    assert out["results"] == [] and "no searchable words" in out["note"]
    assert snap.find_issues(topic="データベース")["results"] == []
