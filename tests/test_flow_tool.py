# The user tool end to end: a verified local copy of the snapshot, answers from it and live checks on GitHub.
import json
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

import anyio
import httpx
import pytest
from mcp import Client

from mergescout.mcp_server import TOOL_NAMES, App, build_server
from mergescout.snapshot.publish import MANIFEST, PACKED, SNAPSHOT, pack
from mergescout.tool.action_pack import build_action_pack
from mergescout.tool.live import GitHubLive, LiveError, classify_comments
from mergescout.tool.queries import Snapshot, fts_query
from mergescout.tool.refs import parse_ref
from mergescout.tool.store import SnapshotStore
from mergescout.tool.tracking import Tracker

from tool_data import ISSUE, REPO, make_snapshot


def published(tmp_path, version="1.0", built="2026-10-15T05:00:00Z"):
    out = tmp_path / f"pub-{version}-{built[:10]}"
    out.mkdir()
    db = sqlite3.connect(out / SNAPSHOT)
    db.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    db.executemany("INSERT INTO meta VALUES (?, ?)", [("schema_version", version), ("built_at", built),
                                                    ("issues", "1"), ("repos", "1")])
    db.commit()
    db.close()
    pack(out)
    return out


class Rel:
    def __init__(self, *dirs, fail=False):
        self.dirs, self.fail = {f"data-{d.name[-10:]}": d for d in dirs}, fail

    def list_releases(self):
        if self.fail:
            raise httpx.ConnectError("offline")
        return [{"id": t, "tag_name": t} for t in self.dirs]

    def assets(self, release):
        return [{"id": (release["id"], n), "name": n} for n in (PACKED, MANIFEST)]

    def download_asset(self, asset, dest):
        tag, name = asset["id"]
        dest.write_bytes((self.dirs[tag] / name).read_bytes())


def test_newer_schema_or_bad_checksum_is_refused(tmp_path):
    good = published(tmp_path)
    store = SnapshotStore(tmp_path / "home", Rel(good))
    store.update()
    newer = published(tmp_path, version="2.0", built="2026-10-16T05:00:00Z")
    assert "newer mergescout" in SnapshotStore(store.root, Rel(newer)).update()
    broken = published(tmp_path, built="2026-10-17T05:00:00Z")
    (broken / PACKED).write_bytes(b"not zstd")
    assert "checksum" in SnapshotStore(store.root, Rel(broken)).update()
    assert json.loads((store.root / MANIFEST).read_text())["built_at"] == "2026-10-15T05:00:00Z"


def test_failed_updates_keep_the_last_good_file(tmp_path):
    store = SnapshotStore(tmp_path / "home", Rel(published(tmp_path)))
    store.update()
    offline = SnapshotStore(store.root, Rel(fail=True))
    notes = []
    assert offline.ensure(max_age_hours=0, log=notes.append) == store.path
    assert notes and "could not check" in notes[0]
    empty = SnapshotStore(tmp_path / "new-home", Rel(fail=True))
    assert empty.ensure(log=lambda *a: None) is None


THIN = {**REPO, "repo_id": 2, "name": "tiny/thing", "merge_enough": 0, "merged": 3, "closed": 1, "merge_rate": 0.75,
        "merge_low": 0.3, "merge_high": 0.95, "review_enough": 0, "insiders": 1, "blocking_walls": 1,
        "walls_json": '[{"wall": "cla", "blocking": true, "evidence": "Sign the CLA"}]', "language": "Rust"}


@pytest.fixture
def snap(tmp_path):
    issues = [ISSUE, {**ISSUE, "number": 8, "title": "Fix login page typo", "body": "Typo on the login page.",
                      "labels": "[]", "opportunity": 0, "beginner": 0, "score": 0.4, "rank_score": 0.3},
              {**ISSUE, "number": 9, "title": "Taken one", "available": 0, "score": 0, "rank_score": 0,
               "blocked_by": "assigned"},
              {**ISSUE, "repo_id": 2, "number": 1, "title": "Database pool for the ETL job", "language": "Rust",
               "score": 0.5, "rank_score": 0.5}]
    return Snapshot(make_snapshot(tmp_path / "s.sqlite", repos=(REPO, THIN), issues=issues))


def test_find_issues_ranks_free_issues_with_evidence(snap):
    out = snap.find_issues(language="python")
    assert [r["issue"] for r in out["results"]] == ["octo/widgets#7", "octo/widgets#8"]
    first = out["results"][0]
    assert first["url"] == "https://github.com/octo/widgets/issues/7"
    assert first["outsider_merge"] == "82% of outsider PRs merged (45 of 55, likely 69-90%) over the last 365 days"
    assert out["snapshot"] == "2026-10-14T05:00:00Z" and "check_issue" in out["note"]
    assert [r["issue"] for r in snap.find_issues(beginner_labels_only=True)["results"]] == ["octo/widgets#7",
                                                                                           "tiny/thing#1"]


def test_one_repo_cannot_fill_the_list(tmp_path):
    issues = [{**ISSUE, "number": n, "rank_score": 1 - n / 100} for n in range(1, 6)]
    snap = Snapshot(make_snapshot(tmp_path / "s.sqlite", issues=issues))
    assert [r["issue"] for r in snap.find_issues()["results"]] == ["octo/widgets#1", "octo/widgets#2"]


def test_topic_text_with_search_syntax_is_plain_words(snap):
    for text in ['"database', "etl: AND NOT", "data* NEAR(x y)", "-loader", ""]:
        snap.find_issues(topic=text)
    assert fts_query('etl: AND "db') == '"etl" OR "db"'


def test_issue_refs_in_any_form_resolve(snap):
    for text in ("octo/widgets#7", "https://github.com/octo/widgets/issues/7", "OCTO/Widgets#7",
                 "github.com/octo/widgets/issues/7/"):
        ref = parse_ref(text)
        assert snap.issue(ref.repo, ref.number)["title"] == ISSUE["title"]
    with pytest.raises(ValueError, match="owner/name#number"):
        parse_ref("widgets")


NOW = datetime.now(timezone.utc)


def iso(days_ago):
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def gql_issue(**over):
    issue = {"title": "T", "state": "OPEN", "stateReason": None, "updatedAt": iso(1),
             "assignees": {"totalCount": 0}, "labels": {"nodes": [{"name": "good first issue"}]},
             "closedByPullRequestsReferences": {"nodes": []}, "comments": {"nodes": []}}
    issue.update(over)
    return {"data": {"rateLimit": {"cost": 1, "remaining": 4999, "resetAt": iso(0)},
                     "repository": {"issue": issue}}}


def live_with(payload=None, token="tok", rest=None):
    def handler(req):
        if req.url.path == "/graphql":
            return httpx.Response(200, json=payload)
        return rest(req)
    return GitHubLive(token, client=httpx.Client(transport=httpx.MockTransport(handler)))


def comment(login, body, days, assoc="NONE", typ="User"):
    return {"createdAt": iso(days), "authorAssociation": assoc, "author": {"__typename": typ, "login": login},
            "bodyText": body}


def test_assignee_open_pr_fresh_claim_and_wait_block():
    cases = [gql_issue(assignees={"totalCount": 1}),
             gql_issue(closedByPullRequestsReferences={"nodes": [{"number": 5, "state": "OPEN"}]}),
             gql_issue(comments={"nodes": [comment("eager", "Can I work on this?", 2)]}),
             gql_issue(comments={"nodes": [comment("lead", "Please wait, needs design", 1, assoc="MEMBER")]})]
    reasons = [live_with(c).issue_status("o", "r", 1)["reasons"] for c in cases]
    assert reasons == [["assigned"], ["open PR"], ["claimed recently"], ["maintainer asked to wait"]]


def test_without_a_token_linked_prs_are_unknown_not_zero():
    def rest(req):
        if req.url.path.endswith("/comments"):
            return httpx.Response(200, json=[{"created_at": iso(1), "author_association": "NONE",
                                              "user": {"login": "x", "type": "User"}, "body": "nice"}])
        return httpx.Response(200, json={"title": "T", "state": "open", "assignees": [], "labels": [],
                                         "updated_at": iso(1), "comments": 1})
    s = live_with(token=None, rest=rest).issue_status("o", "r", 1)
    assert s["linked_open_prs"] is None and s["source"] == "github rest"
    assert s["available"] is True and "linked PRs unknown without a token" in s["note"]


WALLED = {**REPO, "walls_json": '[{"wall": "cla", "blocking": true, "evidence": "Sign the CLA here"},'
                                ' {"wall": "ai_policy", "blocking": false, "evidence": "Disclose AI use in the PR"}]',
          "labels_json": '[{"label": "good first issue", "enough": true, "median_fix_lines": 24, "median_fix_files": 2}]'}


def test_pack_has_examples_checklist_level_and_steps(tmp_path):
    examples = [{"repo_id": 1, "number": n, "merged_at": f"2026-10-0{n}T00:00:00Z", "lines": 30, "files": 2,
                 "days_to_merge": 1.5} for n in (1, 2, 3)]
    snap = Snapshot(make_snapshot(tmp_path / "s.sqlite", repos=(WALLED,), examples=examples))
    pack = build_action_pack(snap, parse_ref("octo/widgets#7"))
    assert pack["issue"]["url"] == "https://github.com/octo/widgets/issues/7" and "flaky database" in pack["issue"]["asks"]
    assert [e["url"] for e in pack["accepted_examples"]][0] == "https://github.com/octo/widgets/pull/3"
    assert any("CLA" in c for c in pack["policy_checklist"]) and any("AI" in c for c in pack["policy_checklist"])
    assert "24 lines" in pack["level"]
    assert pack["status"]["source"] == "snapshot" and "check_issue" in pack["status"]["note"]
    assert any("own words" in s for s in pack["next_steps"]) and pack["draft_comment"].startswith("Hi")


class NoRel:
    def list_releases(self):
        raise OSError("offline")


class Live:
    def issue_status(self, owner, name, number):
        return {"state": "OPEN", "assignees": 0, "linked_open_prs": 0, "claims": [], "waits": [], "available": True,
                "reasons": [], "source": "fake"}

    def fresh_issues(self, language, since, limit=20):
        return [{"repo": "octo/widgets", "number": 99, "title": "Fresh", "labels": [], "created_at": "x",
                 "url": "u", "fresh": True}]


def ready_app(tmp_path):
    make_snapshot(tmp_path / "mergescout.sqlite")
    (tmp_path / MANIFEST).write_text(json.dumps({"sha256": "x", "built_at": "2026-10-14T05:00:00Z",
                                                 "checked_at": "2999-01-01T00:00:00Z"}))
    return App(root=tmp_path, releases=NoRel(), live=Live(), log=lambda *a: None)


def call(server, name, args):
    async def run():
        async with Client(server) as c:
            r = await c.call_tool(name, args)
            return json.loads(r.content[0].text)
    return anyio.run(run)


def test_server_offers_nine_tools_and_stats(tmp_path):
    server = build_server(ready_app(tmp_path))

    async def run():
        async with Client(server) as c:
            names = {t.name for t in (await c.list_tools()).tools}
            stats = json.loads((await c.read_resource("corpus://stats")).contents[0].text)
            return names, stats
    names, stats = anyio.run(run)
    assert names == set(TOOL_NAMES) and len(names) == 9 and stats["issues"] == 1


def test_tools_explain_a_missing_snapshot(tmp_path):
    server = build_server(App(root=tmp_path, releases=NoRel(), live=Live(), log=lambda *a: None))
    out = call(server, "find_issues", {})
    assert "MERGESCOUT_TOKEN" in out["error"]


def test_the_user_tool_never_needs_pipeline_packages():
    code = ("import sys\nfor m in ('pyarrow', 'duckdb', 'orjson', 'pytz'): sys.modules[m] = None\n"
            "import mergescout.cli, mergescout.mcp_server\nprint('ok')")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr


class BlindLive(Live):
    def issue_status(self, owner, name, number):
        return {**super().issue_status(owner, name, number), "linked_open_prs": None, "source": "github rest"}


def test_without_a_token_the_snapshot_s_open_pr_still_counts(tmp_path):
    # Live REST calls cannot see linked PRs; the snapshot's last-known open PR must not be dropped.
    make_snapshot(tmp_path / "mergescout.sqlite", issues=({**ISSUE, "linked_open_prs": 1},))
    (tmp_path / MANIFEST).write_text(json.dumps({"sha256": "x", "built_at": "2026-10-14T05:00:00Z",
                                                 "checked_at": "2999-01-01T00:00:00Z"}))
    server = build_server(App(root=tmp_path, releases=NoRel(), live=BlindLive(), log=lambda *a: None))
    status = call(server, "check_issue", {"issue": "octo/widgets#7"})
    assert status["available"] is False and any("snapshot" in r for r in status["reasons"])


class OkLive:
    def issue_status(self, owner, name, number):
        return {"state": "OPEN", "assignees": 0, "linked_open_prs": 0, "claims": [], "waits": [], "available": True,
                "reasons": [], "source": "fake"}

    def fresh_issues(self, language, since, limit=20):
        return []


class DownLive(OkLive):
    def issue_status(self, owner, name, number):
        raise httpx.ConnectError("no network")

    def fresh_issues(self, language, since, limit=20):
        raise httpx.ConnectError("no network")


def ready(tmp_path, live=None, issues=(ISSUE,), repos=(REPO,)):
    make_snapshot(tmp_path / SNAPSHOT, repos=repos, issues=issues)
    (tmp_path / MANIFEST).write_text(json.dumps({"sha256": "x", "built_at": "2026-10-14T05:00:00Z",
                                                 "checked_at": "2999-01-01T00:00:00Z"}))
    return App(root=tmp_path, releases=NoRel(), live=live or OkLive(), log=lambda *a: None)


def call_app(app, name, args):
    async def run():
        async with Client(build_server(app)) as c:
            return json.loads((await c.call_tool(name, args)).content[0].text)
    return anyio.run(run)


# 1. Network trouble becomes a plain answer, never a traceback.
def test_offline_live_checks_fall_back_to_the_snapshot(tmp_path):
    app = ready(tmp_path, live=DownLive())
    assert "network" in call_app(app, "check_issue", {"issue": "octo/widgets#7"})["error"].lower()
    pack = call_app(app, "action_pack", {"issue": "octo/widgets#7"})
    assert pack["status"]["source"] == "snapshot" and "live check failed" in pack["status"]["note"]
    found = call_app(app, "find_issues", {"fresh": True})
    assert found["results"] and "fresh" in found["fresh_note"]


# 3. Damaged local files never lock the user out.
def test_a_damaged_manifest_counts_as_missing(tmp_path):
    make_snapshot(tmp_path / SNAPSHOT)
    (tmp_path / MANIFEST).write_text("{")
    assert SnapshotStore(tmp_path, NoRel()).ensure(log=lambda *a: None) == tmp_path / SNAPSHOT


# 4. Parallel first calls download once.
def test_parallel_first_calls_check_for_a_snapshot_once(tmp_path):
    app = ready(tmp_path)
    calls = []

    class Slow:
        path = tmp_path / SNAPSHOT

        def ensure(self, log=None):
            calls.append(1)
            time.sleep(0.2)
            return self.path
    app.store = Slow()
    threads = [threading.Thread(target=app.snapshot) for _ in range(3)]
    [th.start() for th in threads]
    [th.join() for th in threads]
    assert len(calls) == 1


# 5. One broken tracked issue does not break the rest, and tracking can stop.
def test_tracking_survives_one_failing_issue_and_can_stop(tmp_path):
    class Mixed(OkLive):
        def issue_status(self, owner, name, number):
            if number == 1:
                raise LiveError("GitHub says this issue or repo does not exist (or is private).")
            return super().issue_status(owner, name, number)
    t_ = Tracker(tmp_path)
    t_.track("o/r#1", OkLive().issue_status("o", "r", 1))
    t_.track("o/r#2", OkLive().issue_status("o", "r", 2))
    changes = t_.updates(Mixed())
    assert changes == [{"issue": "o/r#1", "error": "GitHub says this issue or repo does not exist (or is private)."}]
    app = ready(tmp_path)
    assert call_app(app, "track", {"issue": "o/r#1", "untrack": True})["tracked"] == ["o/r#2"]


# 8. A refused update is remembered for a day instead of re-downloading on every start.
def test_refused_updates_are_not_retried_on_every_start(tmp_path):
    out = tmp_path / "pub-2026-10-16"
    out.mkdir()
    db = sqlite3.connect(out / SNAPSHOT)
    db.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    db.executemany("INSERT INTO meta VALUES (?, ?)", [("schema_version", "2.0"), ("built_at", "b"), ("issues", "1"),
                                                    ("repos", "1")])
    db.commit()
    db.close()
    pack(out)

    class Rel:
        listed = 0

        def list_releases(self):
            Rel.listed += 1
            return [{"id": 1, "tag_name": "data-2026-10-16"}]

        def assets(self, release):
            return [{"id": n, "name": n} for n in (PACKED, MANIFEST)]

        def download_asset(self, asset, dest):
            dest.write_bytes((out / asset["name"]).read_bytes())
    home = tmp_path / "home"
    home.mkdir()
    make_snapshot(home / SNAPSHOT)
    (home / MANIFEST).write_text(json.dumps({"sha256": "old", "built_at": "a", "checked_at": "2000-01-01T00:00:00Z"}))
    store = SnapshotStore(home, Rel())
    store.ensure(log=lambda *a: None)
    store.ensure(log=lambda *a: None)
    assert Rel.listed == 1


TODAY = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


# Tool polish.
def test_one_dominant_repo_still_fills_the_list_with_others(tmp_path):
    issues = [{**ISSUE, "number": n, "rank_score": 1 - n / 1000} for n in range(1, 60)]
    issues += [{**ISSUE, "repo_id": 2, "number": n, "rank_score": 0.1 - n / 1000} for n in (1, 2)]
    snap = Snapshot(make_snapshot(tmp_path / "s.sqlite", repos=(REPO, {**REPO, "repo_id": 2, "name": "o/other"}),
                                  issues=issues))
    assert [r["issue"] for r in snap.find_issues(limit=10)["results"]] == ["octo/widgets#1", "octo/widgets#2",
                                                                           "o/other#1", "o/other#2"]


def test_pasted_links_and_spaced_refs_resolve():
    for text in ("https://github.com/octo/widgets/issues/7#issuecomment-123", "https://github.com/octo/widgets/issues/7?q=1",
                 "octo/widgets #7", "https://github.com/octo/widgets/issues/7/"):
        ref = parse_ref(text)
        assert (ref.owner, ref.name, ref.number) == ("octo", "widgets", 7), text


def test_tracking_ignores_letter_case(tmp_path):
    tr = Tracker(tmp_path)
    tr.track("Octo/Widgets#7", {"state": "OPEN"})
    tr.track("octo/widgets#7", {"state": "OPEN"})
    assert list(tr.tracked()) == ["octo/widgets#7"]


def test_snapshot_opens_from_folders_with_unusual_characters(tmp_path):
    folder = tmp_path / "data #1 100%"
    folder.mkdir()
    assert Snapshot(make_snapshot(folder / "s.sqlite")).stats()["issues"] == 1


def test_fresh_lane_quotes_languages_and_returns_at_most_the_limit(tmp_path):
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(200, json={"items": [{"repository_url": "https://api.github.com/repos/octo/widgets",
                                                    "number": n, "title": "x", "labels": [], "created_at": "c",
                                                    "html_url": "u"} for n in range(9)]})
    live = GitHubLive(None, client=httpx.Client(transport=httpx.MockTransport(handler)))
    live.fresh_issues("Jupyter Notebook", TODAY)
    assert 'language:"Jupyter Notebook"' in seen[0].url.params["q"]
    make_snapshot(tmp_path / SNAPSHOT)
    (tmp_path / MANIFEST).write_text(json.dumps({"sha256": "x", "built_at": "2026-10-14T05:00:00Z",
                                                 "checked_at": "2999-01-01T00:00:00Z"}))

    class NoRel:
        def list_releases(self):
            raise OSError("offline")
    server = build_server(App(root=tmp_path, releases=NoRel(), live=live, log=lambda *a: None))

    async def run():
        async with Client(server) as c:
            return json.loads((await c.call_tool("find_issues", {"fresh": True, "limit": 3})).content[0].text)
    assert len(anyio.run(run)["fresh"]) == 3


def issue_node(**over):
    issue = {"title": "T", "state": "OPEN", "stateReason": None, "updatedAt": iso(1), "assignees": {"totalCount": 0},
             "labels": {"nodes": [{"name": "good first issue"}]}, "closedByPullRequestsReferences": {"nodes": []},
             "timelineItems": {"nodes": []}, "comments": {"nodes": []}}
    issue.update(over)
    return issue


def live_answer(*issues):
    data = {"rateLimit": {"cost": 1, "remaining": 4999, "resetAt": iso(0)}}
    data.update({f"i{n}": {"issue": i} for n, i in enumerate(issues)})
    data["repository"] = {"issue": issues[0]} if issues else None

    def handler(req):
        return httpx.Response(200, json={"data": data})
    return GitHubLive("tok", client=httpx.Client(transport=httpx.MockTransport(handler)))


# Real comment (symfony#66111, 2026-10-10) the claim rule missed.
def test_claims_without_a_leading_i_and_pr_promises_count():
    texts = ["Hi, I'm a native Urdu speaker and would like to work on this. I'll open a PR against the 6.4 branch.",
             "I will submit a pull request for this tonight", "Would you like to work on this?",
             # Review: no subject or no word boundary made these false claims.
             "users would like to pick their own theme", "anyone who would like to work on this is welcome",
             "we would love to take a PR", "I'll create a project to reproduce", "I'll open a proposal"]
    found = [bool(classify_comments([{"login": "u", "type": "User", "association": "NONE", "body": x,
                                      "created_at": iso(1)}], NOW)[0]) for x in texts]
    assert found == [True, True, False, False, False, False, False, False]


def test_open_prs_that_only_mention_the_issue_count_as_taken():
    xref = {"nodes": [{"__typename": "CrossReferencedEvent", "source": {"__typename": "PullRequest", "number": 9,
                                                                         "state": "OPEN", "repository": {"nameWithOwner": "o/r"}}}]}
    s = live_answer(issue_node(timelineItems=xref)).issue_status("o", "r", 1)
    assert s["available"] is False and "open PR mentions it (#9)" in s["reasons"]


# Real queries (2026-10-16): topic words in the title rank first, synonyms count, and the shown score sorts the list.
def test_title_matches_rank_first_with_synonyms(tmp_path):
    issues = [{**ISSUE, "number": 1, "title": "Fix login page", "body": "The database is fine here.", "rank_score": 0.9},
              {**ISSUE, "number": 2, "title": "Database pool leaks", "body": "x", "rank_score": 0.5},
              {**ISSUE, "repo_id": 2, "number": 3, "title": "SQLite lock on startup", "body": "y", "rank_score": 0.4}]
    snap = Snapshot(make_snapshot(tmp_path / "s.sqlite", repos=(REPO, {**REPO, "repo_id": 2, "name": "o/two"}),
                                  issues=issues))
    rows = snap.find_issues(topic="databases")["results"]
    assert [(r["issue"], r["matched"]) for r in rows] == [("octo/widgets#2", "title or label"),
                                                          ("o/two#3", "title or label"), ("octo/widgets#1", "text")]
    assert [r["score"] for r in snap.find_issues()["results"]] == [0.9, 0.5, 0.4]
    # Review: min_score filters on the shown score; only plural s is cut for synonyms; _ and + do not crash.
    assert [r["score"] for r in snap.find_issues(min_score=0.45)["results"]] == [0.9, 0.5]
    assert '"readme"' not in fts_query("docx", True) and '"pytest"' in fts_query("tests", True)
    assert snap.find_issues(topic="snake_case a+b")["results"] == []


# Users keep yesterday's file until the new one downloads; schema 1.0 has no beginner or kind column.
def test_old_snapshot_files_without_new_columns_still_work(tmp_path):
    path = make_snapshot(tmp_path / "s.sqlite")
    db = sqlite3.connect(path)
    db.execute("ALTER TABLE issues DROP COLUMN beginner")
    db.execute("ALTER TABLE issues DROP COLUMN kind")
    db.commit()
    db.close()
    assert Snapshot(path).find_issues(beginner_labels_only=True)["results"][0]["issue"] == "octo/widgets#7"


# Real queries (2026-10-16): 7 of 60 results were taken within a day; with a token they are checked in one call.
def test_find_issues_drops_issues_taken_since_the_snapshot(tmp_path):
    issues = [{**ISSUE, "number": n, "rank_score": 1 - n / 10} for n in (1, 2)]
    issues += [{**ISSUE, "repo_id": 2, "number": 3, "rank_score": 0.5}]
    make_snapshot(tmp_path / SNAPSHOT, repos=(REPO, {**REPO, "repo_id": 2, "name": "o/two"}), issues=issues)
    (tmp_path / MANIFEST).write_text(json.dumps({"sha256": "x", "built_at": "2026-10-14T05:00:00Z",
                                                 "checked_at": "2999-01-01T00:00:00Z"}))
    live = live_answer(issue_node(assignees={"totalCount": 1}), issue_node(), issue_node())

    class NoRel:
        def list_releases(self):
            raise OSError("offline")
    server = build_server(App(root=tmp_path, releases=NoRel(), live=live, log=lambda *a: None))

    async def run():
        async with Client(server) as c:
            return json.loads((await c.call_tool("find_issues", {"limit": 2})).content[0].text)
    out = anyio.run(run)
    assert [r["issue"] for r in out["results"]] == ["octo/widgets#2", "o/two#3"]
    assert all(r["checked_live"] for r in out["results"]) and "live" in out["note"]

    class Broken(GitHubLive):
        def issue_statuses(self, keys):
            raise TypeError("odd answer")
    server = build_server(App(root=tmp_path, releases=NoRel(), live=Broken("tok"), log=lambda *a: None))
    out = anyio.run(run)
    assert len(out["results"]) == 2 and "Live check failed" in out["note"]


def test_the_snapshot_reader_takes_the_same_tokens_as_the_suite(monkeypatch):
    # Real data (2026-10-21): with only GH_TOKEN set it fell back to a six-day-old snapshot.
    from mergescout.tool.store import data_token
    for name in ("MERGESCOUT_TOKEN", "STACKVITALS_TOKEN", "GITHUB_TOKEN", "GH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GH_TOKEN", "gh")
    assert data_token() == "gh"
