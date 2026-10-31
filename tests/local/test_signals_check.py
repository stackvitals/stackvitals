from mergescout.signals.check import owner_logins, sample_repos, score_identity, spearman


def test_owner_logins_reads_codeowners_and_maintainers():
    text = "* @org/core @alice\n/docs/ @Bob # docs\nMaintainers:\n- Carol (@carol-x)\nemail: dave@example.com"
    assert owner_logins(text) == {"alice", "bob", "carol-x"}


def test_sample_is_stratified_and_repeatable():
    stats = [{"repo_id": i, "stars": s, "outsider_prs": 30} for i, s in enumerate([150] * 20 + [5000] * 20 + [50000] * 20)]
    stats.append({"repo_id": 999, "stars": 150, "outsider_prs": 3})
    a = sample_repos(stats, n=30, seed=7)
    assert len(a) == 30 and a == sample_repos(stats, n=30, seed=7) and 999 not in a
    tiers = [next(s["stars"] for s in stats if s["repo_id"] == r) for r in a]
    assert tiers.count(150) == tiers.count(5000) == tiers.count(50000) == 10


def test_score_counts_missed_insiders_by_pr_share():
    s = score_identity({"a": "insider", "b": "outsider", "c": "outsider"}, {"a", "b"}, {"b": 5, "c": 15})
    assert (s["insider_confirmed"], s["insider_checkable"]) == (1, 1)
    assert s["missed_insiders"] == ["b"] and s["missed_pr_share"] == 0.25


def test_spearman():
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0 and spearman([1, 2, 3], [3, 2, 1]) == -1.0
