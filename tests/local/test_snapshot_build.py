import json
import sqlite3

from mergescout.signals.evidence import build_all
from mergescout.snapshot.build import build_snapshot
from signals_data import NOW, make_con, pr, t


def corpus():
    issue = lambda n, title, labels=("good first issue",), assignees=0, body="Steps to reproduce: run the loader.": {
        "repo_id": 1, "number": n, "title": title, "state": "OPEN", "labels": list(labels), "assignees": assignees,
        "linked_open_prs": 0, "body_excerpt": body, "created_at": t(20), "updated_at": t(2)}
    return make_con({
        "repo_meta": [{"repo_id": 1, "name": "octo/widgets", "stars": 900, "language": "Python",
                       "contributing_excerpt": "Sign the CLA", "pushed_at": t(1)}],
        "prs": [pr(i, f"o{i}", lines=20, files=2) for i in range(30)] + [pr(100, "lead", assoc="MEMBER")],
        "issues": [issue(1, "Add database retry to the ETL loader"), issue(2, "Assigned one", assignees=1),
                   issue(3, "Unlabelled but free", labels=()), issue(4, "Another unlabelled", labels=())]})


def built(tmp_path, **kw):
    con = corpus()
    build_all(con, NOW)
    path = tmp_path / "s.sqlite"
    counts = build_snapshot(con, path, NOW, **kw)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    return counts, db


def test_full_text_search_finds_words_and_stems(tmp_path):
    _, db = built(tmp_path)
    hits = db.execute("SELECT i.number FROM issues_fts f JOIN issues i ON i.rowid = f.rowid "
                      "WHERE issues_fts MATCH '\"databases\"'").fetchall()
    assert [h[0] for h in hits] == [1]


def test_caps_keep_beginner_issues_and_the_best_others(tmp_path):
    counts, db = built(tmp_path, per_repo_other=1)
    numbers = {r[0] for r in db.execute("SELECT number FROM issues")}
    assert {1, 2} <= numbers and len(numbers & {3, 4}) == 1
