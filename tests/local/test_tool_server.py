import json
import subprocess
import sys

import anyio
import pytest
from mcp import Client

from mergescout.cli import main
from mergescout.mcp_server import TOOL_NAMES, App, build_server
from mergescout.snapshot.publish import MANIFEST

from tool_data import ISSUE, make_snapshot


class NoRel:
    def list_releases(self):
        raise OSError("offline")


class Live:
    def issue_status(self, owner, name, number):
        return {"state": "OPEN", "assignees": 0, "linked_open_prs": 0, "claims": [], "waits": [], "available": True,
                "reasons": [], "source": "fake"}

    def fresh_issues(self, language, since, limit=20):
        return [{"repo": "octo/widgets", "number": 99, "title": "Fresh", "labels": [], "created_at": "x",
                 "url": "u", "fresh": True}]


def ready_app(tmp_path):
    make_snapshot(tmp_path / "mergescout.sqlite")
    (tmp_path / MANIFEST).write_text(json.dumps({"sha256": "x", "built_at": "2026-10-14T05:00:00Z",
                                                 "checked_at": "2999-01-01T00:00:00Z"}))
    return App(root=tmp_path, releases=NoRel(), live=Live(), log=lambda *a: None)


def call(server, name, args):
    async def run():
        async with Client(server) as c:
            r = await c.call_tool(name, args)
            return json.loads(r.content[0].text)
    return anyio.run(run)


def test_tools_answer_from_the_snapshot_and_live(tmp_path):
    server = build_server(ready_app(tmp_path))
    found = call(server, "find_issues", {"language": "python", "fresh": True})
    assert found["results"][0]["issue"] == "octo/widgets#7" and found["fresh"][0]["number"] == 99
    assert call(server, "check_issue", {"issue": "https://github.com/octo/widgets/issues/7"})["available"] is True
    assert call(server, "action_pack", {"issue": "octo/widgets#7"})["status"]["source"] == "fake"
    assert call(server, "track", {"issue": "octo/widgets#7"})["tracked"] == ["octo/widgets#7"]
    assert call(server, "report_outcome", {"issue": "octo/widgets#7", "outcome": "merged"})["outcome"] == "merged"


def test_cli_find_prints_ranked_issues(tmp_path, monkeypatch, capsys):
    ready_app(tmp_path)
    monkeypatch.setenv("MERGESCOUT_HOME", str(tmp_path))
    assert main(["find", "--lang", "python"]) == 0
    assert "octo/widgets#7" in capsys.readouterr().out


class BlindLive(Live):
    def issue_status(self, owner, name, number):
        return {**super().issue_status(owner, name, number), "linked_open_prs": None, "source": "github rest"}
