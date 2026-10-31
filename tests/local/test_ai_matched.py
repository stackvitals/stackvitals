"""Phase 13 M2: AI-assisted outcomes that compare like with like (mode split, within-author matching, detectable effect)."""
import math
from datetime import datetime, timezone

import pytest

from stackvitals.core import stats
from stackvitals.core.ai_outcomes import mode, outcomes

NOW = datetime(2026, 10, 21, 9, tzinfo=timezone.utc)


def test_the_mantel_haenszel_difference_reduces_to_the_plain_one_in_a_single_group():
    rd, se = stats.mh_risk_difference([(30, 50, 20, 50)])
    assert rd == pytest.approx(0.2) and se == pytest.approx(math.sqrt(0.0096))
    # Two identical groups: the same difference, half the variance.
    rd2, se2 = stats.mh_risk_difference([(30, 50, 20, 50)] * 2)
    assert rd2 == pytest.approx(0.2) and se2 == pytest.approx(math.sqrt(0.0048))


def test_groups_with_only_one_side_carry_no_weight_and_none_left_means_no_answer():
    assert stats.mh_risk_difference([(3, 3, 0, 0), (0, 0, 2, 5)]) == (None, None)
    rd, _ = stats.mh_risk_difference([(1, 1, 0, 1), (5, 9, 0, 0)])
    assert rd == pytest.approx(1.0)


def test_many_tiny_groups_keep_an_honest_variance():
    # 200 authors with one PR on each side: a per-group Wald variance would be 0 in every group; Sato's isn't.
    groups = [(1, 1, 0, 1)] * 60 + [(0, 1, 1, 1)] * 40 + [(1, 1, 1, 1)] * 50 + [(0, 1, 0, 1)] * 50
    rd, se = stats.mh_risk_difference(groups)
    assert rd == pytest.approx(0.1) and 0.04 < se < 0.08



def _pr(n, author="dev", ai=(), head=None, at="User", merged="2026-10-01T10:00:00Z", lines=30, merger=None):
    p = {"n": n, "au": author, "at": at, "ai": list(ai), "lb": [], "ti": f"Change {n}", "head": head or f"feature-{n}",
         "mg": merged, "cr": merged, "add": lines, "del": 0, "ev": []}
    if merged:
        p["ev"] = [["merged", merged, merger or "maintainer"]]
    return p


def test_a_pr_is_an_agents_a_person_working_with_ai_or_a_persons():
    assert mode(_pr(1, author="copilot-swe-agent[bot]", at="Bot")) == "agent"
    assert mode(_pr(2, head="codex/fix-cache")) == "agent"  # an agent's branch, opened from a person's account
    assert mode(_pr(3, ai=["claude"])) == "assisted"
    assert mode(_pr(4)) == "person"


def test_agents_assisted_and_other_prs_are_kept_apart():
    rows = [(_pr(1, head="codex/x"), {}, None), (_pr(2, ai=["claude"]), {}, None), (_pr(3), {}, None)]
    w = outcomes(rows, {"runs": []}, [], NOW, min_n=1)["window"]
    assert (w["agent"]["n"], w["assisted"]["n"], w["others"]["n"]) == (1, 1, 1)


def test_assisted_prs_are_compared_with_the_same_authors_other_prs():
    rows, n = [], 0
    for k in range(30):
        author = f"dev{k}"
        for assisted in (True, False):
            n += 1
            rows.append((_pr(n, author=author, ai=["claude"] if assisted else ()), {}, None))
    # Assisted PRs get reverted 12 times in 30, the same authors' others 3 times: a real gap.
    reverts = []
    for target in [r[0]["n"] for r in rows if r[0]["ai"]][:12] + [r[0]["n"] for r in rows if not r[0]["ai"]][:3]:
        n += 1
        reverts.append((_pr(n, author="maintainer", lines=1000) | {"ti": f"Revert #{target}"}, {}, None))
    out = outcomes(rows + reverts, {"runs": []}, [], NOW, min_n=1)
    m = out["matched"]["assisted"]["reverted"]
    assert m["gap"] == pytest.approx(0.3, abs=0.01) and m["low"] > 0 and m["verdict"] == "higher"
    assert m["matched"] == 30 and m["matched_share"] == 1.0 and m["detectable"] > 0
    cov = out["coverage"]
    # The 15 reverts are people's PRs too: 30 marked of 75.
    assert cov["marked_share"] == pytest.approx(30 / 75, abs=0.01) and cov["authors_marking"] == 30


def test_a_small_repo_reads_no_measurable_difference_with_what_it_could_have_seen():
    rows = [(_pr(1, author="a", ai=["claude"]), {}, None), (_pr(2, author="a"), {}, None),
            (_pr(3, author="b", ai=["claude"]), {}, None), (_pr(4, author="b"), {}, None)]
    m = outcomes(rows, {"runs": []}, [], NOW, min_n=1)["matched"]["assisted"]["reverted"]
    assert m["verdict"] == "too few" and m["gap"] is None


def test_merges_are_compared_with_and_without_self_merges():
    decided, n = [], 0
    for k in range(40):
        for agent in (True, False):
            n += 1
            # Agents' PRs are merged by their own author two times in three; people's by a maintainer.
            self_merge = agent and k % 3 != 0
            p = _pr(n, author=f"dev{k}", head=f"codex/x{n}" if agent else None,
                    merger=f"dev{k}" if self_merge else "maintainer")
            decided.append(p)
    out = outcomes([], {"runs": []}, [], NOW, decided=decided, min_n=1)
    agent = out["matched"]["agent"]
    assert agent["merged"]["verdict"] == "no measurable difference"
    assert agent["merged_by_others"]["gap"] == pytest.approx(-26 / 40, abs=0.02) and agent["merged_by_others"]["verdict"] == "lower"


def _agent_crawl(repos=60):
    import duckdb
    import pyarrow as pa
    con = duckdb.connect()
    con.execute("CREATE TABLE repo_meta (repo_id BIGINT, name VARCHAR, stars INT, language VARCHAR)")
    rows, when = [], datetime(2026, 9, 10, tzinfo=timezone.utc)
    for r in range(repos):
        con.execute("INSERT INTO repo_meta VALUES (?, ?, ?, ?)", [r, f"o/r{r}", 500, "Python"])
        for k in range(10):
            # Half the repos' agents are known by their account, half only by an agent's branch from a person's account.
            by_account = r % 2 == 0
            merged = k < 3
            rows.append([r, 100 + k, when, when if merged else None, when, "MERGED" if merged else "CLOSED",
                         "Copilot" if by_account else "dev", "agent" if by_account else "insider",
                         "fix-x" if by_account else f"codex/task-{k}", ("Copilot" if by_account else "dev") if merged else None, 30, 0])
            merged = k < 7
            rows.append([r, 200 + k, when, when if merged else None, when, "MERGED" if merged else "CLOSED", f"u{k}",
                         "outsider", f"feature-{k}", "maintainer" if merged else None, 30, 0])
    cols = ["repo_id", "number", "created_at", "merged_at", "closed_at", "state", "author_login", "author_role", "head_ref",
            "merged_by", "additions", "deletions"]
    con.register("batch", pa.table({c: [x[i] for x in rows] for i, c in enumerate(cols)}))
    con.execute("CREATE TABLE pr_class AS SELECT * FROM batch")
    return con


def test_the_crawl_publishes_the_agent_gap_within_the_same_repo_month_and_size():
    from mergescout.signals.flow_bench import agent_matched
    now = datetime(2026, 10, 19, tzinfo=timezone.utc)
    g = agent_matched(_agent_crawl(), now)["all|all"]
    assert g["repos"] == 60 and g["agent_prs"] == 600
    assert g["merged"]["gap"] == pytest.approx(-0.4) and g["merged"]["high"] < 0
    # Every merged agent PR was merged by whoever ran the agent: nobody else accepted any.
    assert g["merged_by_others"]["gap"] == pytest.approx(-0.7)
    assert agent_matched(_agent_crawl(repos=5), now) == {}


def test_a_repos_baseline_carries_its_groups_like_for_like_agent_gap():
    from stackvitals.core.ai_outcomes import baseline
    group = {"repos_with_agent_prs": 40, "agent": {"decided": 900, "merged": 0.62}, "outsider": {"decided": 3000, "merged": 0.55}}
    matched = {"repos": 35, "agent_prs": 800, "merged": {"gap": -0.04, "low": -0.06, "high": -0.02},
               "merged_by_others": {"gap": 0.01, "low": -0.01, "high": 0.03}}
    out = baseline({"agent_prs": {"Python|all": group}, "agent_matched": {"Python|all": matched}}, "Python", 50)
    assert out["matched"]["merged_by_others"]["gap"] == 0.01 and out["matched"]["repos"] == 35
    assert "matched" not in baseline({"agent_prs": {"Python|all": group}, "agent_matched": {"Python|all": {"merged": "x"}}}, "Python", 50)


def test_a_comparison_where_every_pair_goes_one_way_still_has_a_range_inside_minus_one_to_one():
    # Review finding: Sato's variance is zero when every discordant pair agrees, which printed "+100 (likely +100 to +100)".
    from stackvitals.core.ai_outcomes import matched
    treated = [{"k": k, "hit": 1} for k in range(6)]
    control = [{"k": k, "hit": 0} for k in range(6)]
    out = matched(treated, control, key=lambda x: x["k"], hit=lambda x: x["hit"])
    assert out["gap"] == 1.0 and out["high"] <= 1.0 and out["low"] < 1.0 and -1.0 <= out["low"]
