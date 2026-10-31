from datetime import datetime, timedelta, timezone

from mergescout.signals.triage_math import FEATURES, fit
from stackvitals.flow.triage import features, triage

NOW = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)


def at(days):
    return (NOW - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def pr(n, au, assoc="CONTRIBUTOR", st="OPEN", created=2, merged=None, lines=40, issue=False):
    return {"t": "pr", "n": n, "st": st, "cr": at(created), "mg": at(merged) if merged is not None else None,
            "cl": at(merged if merged is not None else created - 1) if st != "OPEN" else None, "au": au, "at": "User",
            "as": assoc, "add": lines, "del": 0, "iss": issue, "rq": [], "ev": [], "cm": [], "paths": []}


def history():
    out = [pr(k, f"o{k}", "NONE", "MERGED", created=50 + k, merged=49 + k) for k in range(15)]
    out += [pr(100 + k, f"x{k}", "NONE", "CLOSED", created=60 + k) for k in range(5)]
    out += [pr(200, "ann", "CONTRIBUTOR", "MERGED", created=30, merged=29)]
    return out


def test_features_use_only_what_this_repo_knew_and_the_pr_itself():
    target = pr(300, "ann", lines=1500, issue=True)
    f = features(target, history(), now=NOW)
    assert f == {"history": "1-2", "size": "1000+", "issue": "yes", "repo_rate": "60-80%"}


def test_triage_scores_open_outside_prs_with_reasons_and_says_how_good_the_model_is():
    rows = [{"history": h, "size": s, "issue": "no", "repo_rate": "60-80%",
             "merged": (h == "3+") or (s == "<50" and k % 2 == 0)} for k in range(400)
            for h in ("new", "3+") for s in ("<50", "1000+")]
    model = fit(rows) | {"evaluation": {"test_prs": 17860, "brier": 0.189, "baseline_brier": 0.202}}
    data = {"open": [pr(300, "ann", lines=1500), pr(301, "maint", assoc="MEMBER")], "closed": history()}
    out = triage(data, model, NOW)
    assert [x["pr"] for x in out["prs"]] == [300]  # maintainers' own PRs are never scored
    one = out["prs"][0]
    assert 0 < one["chance"] < 1 and one["reasons"] and "never shown" in out["note"]
    assert out["model"]["checked_on_prs"] == 17860


def test_live_features_match_training_first_timer_from_history_and_deleted_users():
    from stackvitals.flow.triage import valid
    new = pr(300, "zed", assoc="CONTRIBUTOR")  # GitHub's label says contributor, but zed never opened a PR here
    back = pr(301, "ann", assoc="FIRST_TIME_CONTRIBUTOR")  # label says first time, but ann has PR 200 here
    assert features(new, history(), now=NOW)["history"] == "new"
    assert features(back, history(), now=NOW)["history"] == "1-2"
    ghost = pr(302, None) | {"au": None}
    assert features(ghost, history() + [pr(5, None, st="MERGED", created=40, merged=39) | {"au": None}], now=NOW)["history"] == "new"
    good = {"intercept": 0.1, "coef": {}, "prs": 5000, "features": FEATURES}
    assert valid(good | {"prs": 12}) is None and valid(good)
    # A model file built with other inputs would score with half its weights missing: refused.
    assert valid(good | {"features": {"here": ["0", "1-2", "3+"]}}) is None
