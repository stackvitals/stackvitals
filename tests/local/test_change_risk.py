"""Change risk before merge: from this repo's own history (PRs later reverted, or shipped in a small deployment that
failed), how risky an open PR's folders, size, author familiarity, tests and authorship are, with the reasons, and a
backtest on newer PRs that says how much the score is worth."""
from datetime import datetime, timedelta, timezone

from stackvitals.core import change_risk

NOW = datetime(2026, 10, 28, tzinfo=timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def pr(n, paths, au="amy", size=40, days=30, at="User", title="Change"):
    return {"n": n, "paths": paths, "au": au, "at": at, "add": size, "del": 0, "ti": title, "mg": iso(NOW - timedelta(days=days))}


def test_troubled_prs_are_the_reverted_and_those_in_a_small_failed_deployment():
    a, b, c, d = pr(1, ["api/x.py"]), pr(2, ["web/a.ts"]), pr(3, ["api/y.py"]), pr(4, ['Revert "Change"'], title='Revert "Change"')
    d["ti"] = "Revert #1"
    rows = [(a, {}, {"id": "d1"}), (b, {}, {"id": "d2"}), (c, {}, {"id": "d2"}), (d, {}, None)]
    incidents = [{"deployment": "d2"}]
    assert change_risk.troubled(rows, incidents) == {1, 2, 3}


def history():
    rows, bad = [], set()
    for i in range(60):
        risky = i % 3 == 0
        p = pr(i, ["payments/charge.py" if risky else "docs/guide.md"], au="amy" if i % 2 else "bob", days=200 - i * 3)
        rows.append((p, {}, None))
        if risky and i % 2 == 0:
            bad.add(i)
    return rows, bad


def test_risky_folders_raise_the_score_and_say_why():
    rows, bad = history()
    model = change_risk.fit([r[0] for r in rows], bad)
    hot = change_risk.score(pr(900, ["payments/refund.py"], au="newcomer"), model)
    cold = change_risk.score(pr(901, ["docs/faq.md"], au="amy"), model)
    assert hot["risk"] > cold["risk"]
    assert any("payments/" in r for r in hot["reasons"])
    assert 0 <= cold["risk"] <= 1 and cold["level"] in ("low", "medium", "high")


def test_too_little_trouble_in_history_means_no_score_rather_than_a_guess():
    rows, _bad = history()
    model = change_risk.fit([r[0] for r in rows], {1})
    assert model is None and change_risk.score(pr(1, ["a/b"]), None) is None


def test_the_backtest_trains_on_older_prs_and_scores_newer_ones():
    rows, bad = history()
    got = change_risk.backtest([r[0] for r in rows], bad)
    assert got["train"] + got["test"] == 60 and got["test_troubled"] >= 3
    assert got["auc"] > 0.7  # risky folders were really riskier here
    assert change_risk.backtest([r[0] for r in rows][:10], bad) is None


def test_a_first_change_in_a_folder_is_a_reason_when_newcomers_changes_went_wrong_here():
    rows, bad = [], set()
    for i in range(60):
        newcomer = i % 4 == 0
        rows.append(pr(i, ["core/engine.py"], au=f"new{i}" if newcomer else "amy", days=200 - i * 3))
        if newcomer:
            bad.add(i)
    model = change_risk.fit(rows, bad)
    got = change_risk.score(pr(900, ["core/engine.py"], au="stranger"), model)
    assert any("first change" in r for r in got["reasons"]) and got["level"] == "high"


def test_follow_up_fixes_mark_changes_a_fix_soon_touched_and_ignore_files_every_pr_touches():
    prs = [pr(1, ["core/a.py", "CHANGELOG.md"], days=30), pr(2, ["core/a.py"], days=25, title="Fix crash in a"),
           pr(3, ["web/b.ts", "CHANGELOG.md"], days=29), pr(4, ["CHANGELOG.md"], days=28, title="fix typo in changelog")]
    prs += [pr(10 + i, ["CHANGELOG.md", f"x/{i}.py"], days=60 + i) for i in range(6)]
    assert change_risk.follow_up_fixes(prs) == {1}


def test_scores_are_shown_only_where_the_repos_own_backtest_says_they_work():
    rows, bad = history()
    prs = [r[0] for r in rows]
    open_prs = [pr(900, ["payments/refund.py"]), pr(901, ["docs/faq.md"])]
    good = change_risk.assess(prs, bad, open_prs)
    assert good["backtest"]["auc"] >= change_risk.MIN_AUC and [s["pr"] for s in good["open"]] == [900, 901]
    noise = {p["n"] for p in prs if p["n"] % 5 == 0}  # trouble unrelated to anything the score sees
    weak = change_risk.assess(prs, noise, open_prs)
    assert weak["open"] is None and "not predictive" in weak["note"].lower()
