from mergescout.signals.identity import build_people
from mergescout.signals.issues import build_issue_signals
from signals_data import NOW, make_con, pr, t


def issue(number, labels=("good first issue",), assignees=0, open_prs=0, closed_prs=0, state="OPEN"):
    return {"repo_id": 1, "number": number, "title": f"i{number}", "state": state, "labels": list(labels),
            "assignees": assignees, "linked_open_prs": open_prs, "linked_closed_prs": closed_prs,
            "created_at": t(60), "updated_at": t(1)}


def comment(number, login, body, days_ago, assoc="NONE", cid=None):
    return {"repo_id": 1, "number": number, "comment_id": cid or hash((number, login, days_ago)) % 10**9,
            "author_login": login, "author_association": assoc, "body_excerpt": body, "created_at": t(days_ago)}


def signals(tables):
    con = make_con({"prs": [pr(99, "x", merged_by="maint")], **tables})
    build_people(con)
    build_issue_signals(con, NOW)
    return {r[0]: dict(zip(["available", "blocked_by", "claimers", "interest", "dead_ends", "opportunity"], r[1:]))
            for r in con.execute("SELECT number, available, blocked_by, claimers, interest_30d, dead_ends, opportunity "
                                 "FROM issue_signals").fetchall()}


def test_dead_ends_interest_and_opportunity_flags():
    s = signals({"issues": [issue(1, closed_prs=2), issue(2, labels=("Good-First-Issue",)), issue(3, labels=("bug",)),
                            issue(4, state="CLOSED")],
                 "comments": [comment(1, "u1", "any update?", 5), comment(1, "u2", "same here", 6),
                              comment(1, "u3", "old", 40)]})
    assert set(s) == {1, 2, 3}
    assert (s[1]["dead_ends"], s[1]["interest"]) == (2, 2)
    assert s[2]["opportunity"] and not s[3]["opportunity"]
