"""The crawl's agent leaderboard: each coding agent across public repos (its account, or its branch prefix from a
person's account), with its merge share, the share someone other than its author merged, and its gap against people's
PRs of the same repo, month and size; agents seen in too few repos are left out."""
from datetime import datetime, timezone

import pytest

from mergescout.signals.flow_bench import agent_leaderboard
from test_ai_matched import _agent_crawl

NOW = datetime(2026, 10, 19, tzinfo=timezone.utc)


def test_each_agent_gets_its_own_line_from_its_account_or_branch():
    board = agent_leaderboard(_agent_crawl(), NOW)
    assert set(board["agents"]) == {"copilot", "codex"}
    cop = board["agents"]["copilot"]
    assert cop["repos"] == 30 and cop["prs"] == 300 and cop["merged"] == pytest.approx(0.3)
    assert cop["merged_by_others"] == pytest.approx(0.0)  # whoever ran the agent merged every one
    assert cop["vs_people"]["gap"] == pytest.approx(-0.4) and cop["vs_people"]["high"] < 0
    assert board["agents"]["codex"]["repos"] == 30 and board["window_days"] == 180


def test_an_agent_seen_in_too_few_repos_is_left_out():
    assert agent_leaderboard(_agent_crawl(repos=8), NOW)["agents"] == {}
