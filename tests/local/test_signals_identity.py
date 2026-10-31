from mergescout.signals.identity import build_people, build_pr_class
from signals_data import make_con, pr


def people(con):
    return {r[0]: (r[1], r[2]) for r in con.execute("SELECT login, kind, reasons FROM people").fetchall()}


def classes(con):
    return dict(con.execute("SELECT number, author_class FROM pr_class").fetchall())


def test_identity_is_per_repo():
    con = make_con({"prs": [pr(1, "x", merged_by="emp", repo=1), pr(2, "emp", repo=2, merged_by="m2")]})
    build_people(con)
    build_pr_class(con)
    rows = dict(((r[0], r[1]), r[2]) for r in con.execute("SELECT repo_id, login, kind FROM people").fetchall())
    assert rows[(1, "emp")] == "insider" and rows[(2, "emp")] == "outsider"


def test_people_count_the_prs_they_wrote():
    con = make_con({"prs": [pr(1, "a", merged_by="m"), pr(2, "a", merged_by="m"), pr(3, "m", merged_by="m")],
                    "comments": [{"repo_id": 1, "number": 1, "comment_id": 1, "author_login": "a",
                                  "author_association": "NONE", "created_at": None}]})
    build_people(con)
    assert dict(con.execute("SELECT login, prs FROM people").fetchall()) == {"a": 2, "m": 1}
