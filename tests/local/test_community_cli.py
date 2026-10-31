import json

import pytest

from test_ci_mcp import NoRel, mcp_call
from test_community_action import NOW, Fake, rest

from mergescout.mcp_server import App
from stackvitals.community.cli import main
from stackvitals.mcp_server import build_server


@pytest.fixture(autouse=True)
def _offline_benchmarks(tmp_path, monkeypatch):
    # With a token the benchmarks would be fetched from GitHub; unit tests never go to the network.
    for name in ("STACKVITALS_COMMUNITY_BENCH_URL", "STACKVITALS_STARS_BENCH_URL"):
        monkeypatch.setenv(name, str(tmp_path / "missing.json"))


def test_the_local_report_reads_prs_issues_and_stars_and_lists_who_waits(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("STACKVITALS_HOME", str(tmp_path / "home"))
    assert main(["report", "o/r"], now=NOW, make_gql=lambda tok: Fake(), make_api=rest(), tok="tok") == 0
    out = capsys.readouterr().out
    assert "Newcomers waiting for a first answer" in out and "Issue #5: waiting 1 day" in out and "PR #1" in out
    assert main(["report", "o/r", "--json"], now=NOW, make_gql=lambda tok: Fake(), make_api=rest(), tok="tok") == 0
    data = json.loads(capsys.readouterr().out)
    assert [w["n"] for w in data["waiting"]] == [1, 5] and data["traffic"]["views"][0][0] == "2026-10-18"


def test_without_a_token_that_reads_traffic_the_report_says_so_and_still_runs(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("STACKVITALS_HOME", str(tmp_path / "home"))
    assert main(["report", "o/r"], now=NOW, make_gql=lambda tok: Fake(), make_api=rest(traffic_status=403), tok="tok") == 0
    assert "Traffic is off" in capsys.readouterr().out


def test_agents_get_community_health_and_the_newcomers_waiting(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    import test_community_action
    # Agent tools use the real clock, so the fake data is placed relative to it.
    monkeypatch.setattr(test_community_action, "NOW", datetime.now(timezone.utc))
    app = App(root=tmp_path / "h", releases=NoRel(), live=None, log=lambda *a: None)
    server = build_server(app, ci_api=rest(), ci_home=tmp_path / "sv", ci_token="tok", flow_gql=lambda tok: Fake())
    health = mcp_call(server, "community_health", {"repo": "o/r"})
    assert health["source"].startswith("read live") and health["newcomers"]["first_time"] == 0
    assert health["first_answers"]["issues"]["items"] == 1 and "score" in health
    # Too little merged work to say who carries it; the tenure split is there with its counts.
    assert health["who_carries_the_work"] is None and health["first_answers_by_tenure"]["days"] == 90
    waiting = mcp_call(server, "newcomers_waiting", {"repo": "o/r"})
    assert [(w["kind"], w["number"]) for w in waiting["waiting"]] == [("pr", 1), ("issue", 5)]
    assert waiting["waiting"][1]["url"] == "https://github.com/o/r/issues/5"
