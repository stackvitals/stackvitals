# Snapshot end to end: signal tables become one scored, searchable SQLite file, then a published release.
import json
import sqlite3
from datetime import datetime, timezone

import pytest

from mergescout.signals.evidence import build_all
from mergescout.snapshot.build import build_snapshot
from mergescout.snapshot.publish import MANIFEST, PACKED, SNAPSHOT, publish
from mergescout.tool.queries import Snapshot

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


def test_snapshot_has_scored_issues_repos_and_examples(tmp_path):
    counts, db = built(tmp_path)
    assert counts["issues"] == 4 and counts["repos"] == 1
    meta = dict(db.execute("SELECT key, value FROM meta").fetchall())
    assert meta["schema_version"] == "1.1" and meta["built_at"] == "2026-10-14T00:00:00Z"
    rows = {r["number"]: r for r in db.execute("SELECT * FROM issues")}
    assert rows[1]["score"] > 0 and rows[2]["score"] == 0 and rows[2]["available"] == 0
    assert json.loads(rows[1]["labels"]) == ["good first issue"] and rows[1]["language"] == "Python"
    # Score parts are numbers and notes live once per repo: per-issue text would not fit the 150 MB target.
    assert {"p_avail", "p_merge", "p_reply", "p_fixed", "p_quality", "mult"} <= set(rows[1].keys())
    assert "notes" not in rows[1].keys() and 0 < rows[1]["p_merge"] <= 1
    repo = db.execute("SELECT * FROM repos").fetchone()
    assert repo["name"] == "octo/widgets" and repo["merge_enough"] == 1 and repo["blocking_walls"] == 1
    assert any(n.startswith("not enough evidence for review time") for n in json.loads(repo["notes"]))
    assert db.execute("SELECT count(*) FROM outsider_prs").fetchone()[0] == 3


def test_issue_bodies_are_trimmed_for_size(tmp_path):
    con = corpus()
    con.execute("UPDATE issues SET body_excerpt = repeat('word ', 200) WHERE number = 1")
    build_all(con, NOW)
    build_snapshot(con, tmp_path / "s.sqlite", NOW)
    body = sqlite3.connect(tmp_path / "s.sqlite").execute("SELECT body FROM issues WHERE number = 1").fetchone()[0]
    assert len(body) == 300


def test_snapshot_stores_no_people_logins(tmp_path):
    _, db = built(tmp_path)
    for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'issues_fts%'"):
        cols = [c[1] for c in db.execute(f"PRAGMA table_info({table})")]
        assert not [c for c in cols if "login" in c or "author" in c], table


PUBLISHED_AT = datetime(2026, 10, 15, 5, 0, tzinfo=timezone.utc)


def tiny(out, issues=3):
    out.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(out / SNAPSHOT)
    db.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    db.executemany("INSERT INTO meta VALUES (?, ?)", [("schema_version", "1.0"), ("built_at", "2026-10-15T05:00:00Z"),
                                                    ("issues", str(issues)), ("repos", "1")])
    db.commit()
    db.close()


class Rel:
    def __init__(self, tags=()):
        self.releases = [{"id": i, "tag_name": t} for i, t in enumerate(tags)]
        self.files, self.deleted = {}, []

    def upload(self, tag, path, name=None):
        if not any(r["tag_name"] == tag for r in self.releases):
            self.releases.append({"id": len(self.releases) + 100, "tag_name": tag})
        self.files[(tag, name or path.name)] = path.read_bytes()

    def list_releases(self):
        return list(self.releases)

    def assets(self, release):
        return []

    def delete_release(self, release):
        self.deleted.append(release["tag_name"])
        self.releases.remove(release)


def test_publish_uploads_data_then_manifest_and_keeps_seven(tmp_path):
    tiny(tmp_path)
    rel = Rel([f"data-2026-10-0{d}" for d in range(1, 9)] + ["crawl-state"])
    assert publish(rel, tmp_path, PUBLISHED_AT, keep=7, log=lambda *a: None) == "data-2026-10-15"
    assert list(rel.files) == [("data-2026-10-15", PACKED), ("data-2026-10-15", MANIFEST)]
    assert sorted(rel.deleted) == ["data-2026-10-01", "data-2026-10-02"]
    assert any(r["tag_name"] == "crawl-state" for r in rel.releases)


def test_an_empty_snapshot_is_never_published(tmp_path):
    tiny(tmp_path, issues=0)
    rel = Rel()
    with pytest.raises(ValueError, match="empty"):
        publish(rel, tmp_path, PUBLISHED_AT, log=lambda *a: None)
    assert rel.files == {}


def test_issue_template_boilerplate_is_dropped_from_the_body(tmp_path):
    # Real issues often start with checklist text; the 300 characters should hold what the issue asks.
    con = corpus()
    body = ("I affirm:\nI have read and understood the Contributing Guide and the Code of Conduct.\n"
            "I have searched existing issues.\nMobs walk too slowly after the update.")
    con.execute("UPDATE issues SET body_excerpt = ? WHERE number = 1", [body])
    build_all(con, NOW)
    build_snapshot(con, tmp_path / "s.sqlite", NOW)
    body = sqlite3.connect(tmp_path / "s.sqlite").execute("SELECT body FROM issues WHERE number = 1").fetchone()[0]
    assert body == "Mobs walk too slowly after the update."


# 7. Two repo ids with the same name (rename in between crawls) do not break the build.
def test_repeated_repo_names_keep_one_repo(tmp_path):
    con = make_con({"repo_meta": [{"repo_id": 1, "name": "octo/widgets", "language": "Python"},
                                  {"repo_id": 2, "name": "OCTO/Widgets", "language": "Python"}],
                    "prs": [pr(1, "a")],
                    "issues": [{"repo_id": r, "number": 5, "title": "t", "state": "OPEN", "labels": ["good first issue"],
                                "assignees": 0, "created_at": t(5), "updated_at": t(1)} for r in (1, 2)]})
    build_all(con, NOW)
    build_snapshot(con, tmp_path / "s.sqlite", NOW)
    db = sqlite3.connect(tmp_path / "s.sqlite")
    assert db.execute("SELECT count(*) FROM repos").fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM issues WHERE repo_id NOT IN (SELECT repo_id FROM repos)").fetchone()[0] == 0


TODAY = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


# Publishing refuses a snapshot much smaller than the last one.
def test_a_much_smaller_snapshot_is_not_published(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    db = sqlite3.connect(out / SNAPSHOT)
    db.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    db.executemany("INSERT INTO meta VALUES (?, ?)", [("schema_version", "1.0"), ("built_at", "b"), ("issues", "300"),
                                                    ("repos", "10")])
    db.commit()
    db.close()

    class Rel:
        def __init__(self):
            self.files = {("data-2026-10-15", MANIFEST): json.dumps({"issues": 1000}).encode()}

        def list_releases(self):
            return [{"id": t, "tag_name": t} for t in sorted({t for t, _ in self.files})]

        def assets(self, release):
            return [{"id": (t, n), "name": n} for t, n in self.files if t == release["id"]]

        def download_asset(self, asset, dest):
            dest.write_bytes(self.files[asset["id"]])

        def upload(self, tag, path, name=None):
            self.files[(tag, name or path.name)] = path.read_bytes()

        def delete_release(self, release):
            pass
    rel = Rel()
    with pytest.raises(ValueError, match="shrank"):
        publish(rel, out, TODAY, log=lambda *a: None)
    assert (("data-2026-10-16", PACKED)) not in rel.files
    assert publish(rel, out, TODAY, force=True, log=lambda *a: None) == "data-2026-10-16"


# 7 + 8 + 9. Real beginner labels, no bot-made issues, discussions and very old issues rank low.
def test_snapshot_knows_beginner_labels_and_drops_bot_issues(tmp_path):
    issue = lambda n, title, labels, author="human", created=20: {
        "repo_id": 1, "number": n, "title": title, "state": "OPEN", "labels": labels, "assignees": 0,
        "author_login": author, "body_excerpt": "Steps to reproduce: run it.", "created_at": t(created),
        "updated_at": t(2)}
    con = make_con({"repo_meta": [{"repo_id": 1, "name": "octo/widgets", "language": "Python"}],
                    "prs": [pr(i, f"o{i}") for i in range(25)] + [pr(99, "renovate[bot]", typ="Bot")],
                    "issues": [issue(1, "Fix the parser", ["good first issue"]),
                               issue(2, "Improve caching", ["help wanted"]),
                               issue(3, "Dependency Dashboard", ["good first issue"], author="renovate[bot]"),
                               issue(4, "[RFC] Rework the plugin system", ["good first issue"]),
                               issue(5, "Fix the old parser", ["good first issue"], created=900),
                               # Bots also mirror real tasks (stdlib-bot, MelvinBot); a beginner label keeps them.
                               issue(6, "Fix JavaScript lint errors", ["good first issue"], author="stdlib-bot"),
                               issue(7, "Flaky test: TestStartDiskQuota", [], author="ti-chi-bot"),
                               issue(8, "Support launch containers", [], author="adamrtalbot"),
                               issue(9, "Fix the docs link", ["good first issue", "needs triage"]),
                               # Review: people also file issues about the dashboard feature itself.
                               issue(10, "Dependency Dashboard: group by manager", [])]})
    build_all(con, NOW)
    build_snapshot(con, tmp_path / "s.sqlite", NOW)
    db = sqlite3.connect(tmp_path / "s.sqlite")
    score = dict(db.execute("SELECT number, score FROM issues").fetchall())
    assert sorted(score) == [1, 2, 4, 5, 6, 8, 9, 10]
    assert score[4] < score[1] / 2 and score[5] < score[1] and 0 < score[9] < score[1]
    assert dict(db.execute("SELECT number, beginner FROM issues").fetchall()) == {1: 1, 2: 0, 4: 1, 5: 1, 6: 1, 8: 0,
                                                                                  9: 1, 10: 0}
    snap = Snapshot(tmp_path / "s.sqlite")
    assert snap.find_issues(beginner_labels_only=True)["results"][0]["level"] == "beginner label"
    assert {r["level"] for r in snap.find_issues(language="Python", topic="caching")["results"]} == {"help wanted"}
    assert "needs triage" in snap.find_issues(topic="docs link")["results"][0]["warning"]
