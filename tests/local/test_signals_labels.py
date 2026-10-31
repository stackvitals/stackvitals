from mergescout.signals.identity import build_people
from mergescout.signals.labels import build_label_trust
from signals_data import NOW, make_con, pr, t


def closed(number, label="good first issue", reason="COMPLETED", fix=None, fix_author=None, fix_state="MERGED",
           assoc="NONE"):
    return {"repo_id": 1, "number": number, "labels": [label], "state_reason": reason, "created_at": t(100),
            "closed_at": t(50), "fix_pr": fix, "fix_pr_state": fix_state if fix else None, "fix_author": fix_author,
            "fix_association": assoc if fix else None}


def trust(tables):
    con = make_con(tables)
    build_people(con)
    build_label_trust(con, NOW)
    cols = [d[0] for d in con.execute("SELECT * FROM label_trust").description]
    return {r[1]: dict(zip(cols, r)) for r in con.execute("SELECT * FROM label_trust").fetchall()}


def test_not_planned_duplicates_ai_and_bots_are_separated():
    prs = [pr(300, "o", ai="codex"), pr(301, "dependabot[bot]", typ="Bot")]
    lt = trust({"prs": prs, "closed_issues": [
        closed(1, reason="NOT_PLANNED"), closed(2, reason="DUPLICATE"), closed(3, fix=300, fix_author="o"),
        closed(4, fix=301, fix_author="dependabot[bot]")]})["good first issue"]
    assert (lt["not_planned"], lt["duplicates"], lt["ai_fixes"], lt["bot_fixes"], lt["enough"]) == (1, 1, 1, 1, False)
