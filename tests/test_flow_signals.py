# Signals end to end on small datasets: one test per trial error in the plan, plus rulings found on real data.
import json
import tarfile
from datetime import datetime, timedelta, timezone

import duckdb
import httpx
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from mergescout.crawl.writer import SCHEMAS, BatchWriter
from mergescout.signals.__main__ import main
from mergescout.signals.evidence import build_all
from mergescout.signals.identity import build_people, build_pr_class
from mergescout.signals.issues import build_issue_signals
from mergescout.signals.labels import build_label_trust
from mergescout.signals.repo_stats import build_repo_stats
from mergescout.signals.silver import load_silver
from mergescout.signals.walls import BLOCKING, find_walls
from mergescout.tool.live import GitHubLive
from mergescout.tool.queries import fts_query

from signals_data import NOW, make_con, pr, t


T = datetime(2026, 10, 1, tzinfo=timezone.utc)


def test_newest_row_per_key_wins(tmp_path):
    old = BatchWriter(tmp_path, "r1", now=lambda: T)
    old.add("prs", [{"repo_id": 1, "number": 5, "state": "OPEN"}, {"repo_id": 1, "number": 6, "state": "OPEN"}])
    old.flush()
    new = BatchWriter(tmp_path, "r2", now=lambda: T + timedelta(days=7))
    new.add("prs", [{"repo_id": 1, "number": 5, "state": "MERGED"}])
    new.flush()
    con = duckdb.connect()
    counts = load_silver(con, [tmp_path])
    assert counts["prs"] == 2
    assert con.execute("SELECT state FROM prs WHERE number = 5").fetchone()[0] == "MERGED"


def test_old_batches_without_new_columns_load(tmp_path):
    old_schema = pa.schema([f for f in SCHEMAS["issues"] if f.name not in ("fetched_at", "linked_closed_prs")])
    (tmp_path / "crawl" / "issues").mkdir(parents=True)
    pq.write_table(pa.Table.from_pylist([{"repo_id": 1, "number": 2, "state": "OPEN", "run_id": "a"}],
                                        schema=old_schema), tmp_path / "crawl" / "issues" / "run=a-000.parquet")
    con = duckdb.connect()
    counts = load_silver(con, [tmp_path, tmp_path / "missing-root"])
    assert counts["issues"] == 1 and counts["closed_issues"] == 0
    assert con.execute("SELECT linked_closed_prs, fetched_at FROM issues").fetchone() == (None, None)
    cols = [r[0] for r in con.execute("DESCRIBE closed_issues").fetchall()]
    assert "fix_author" in cols and "fetched_at" in cols


def people(con):
    return {r[0]: (r[1], r[2]) for r in con.execute("SELECT login, kind, reasons FROM people").fetchall()}


def classes(con):
    return dict(con.execute("SELECT number, author_class FROM pr_class").fetchall())


def test_trial_error_1_bots_and_ai_agents_are_not_outsiders():
    con = make_con({"prs": [pr(1, "dependabot[bot]", typ="Bot"), pr(2, "miss-islington"),
                            pr(3, "newbie", ai="codex"), pr(4, "newbie2")]})
    build_people(con)
    build_pr_class(con)
    assert people(con)["miss-islington"][0] == "bot" and people(con)["dependabot[bot]"][0] == "bot"
    assert classes(con) == {1: "bot", 2: "bot", 3: "ai", 4: "outsider"}


def test_trial_error_2_unlisted_employees_found_by_behaviour():
    con = make_con({"prs": [pr(1, "x", merged_by="emp"), pr(2, "emp", assoc="CONTRIBUTOR", merged_by="emp"),
                            pr(3, "reviewer", assoc="CONTRIBUTOR", state="OPEN")],
                    "comments": [{"repo_id": 1, "number": 9, "comment_id": 1, "author_login": "member",
                                  "author_association": "MEMBER", "created_at": None}]})
    build_people(con)
    p = people(con)
    assert p["emp"][0] == "insider" and "merges others" in p["emp"][1] and "merges own" in p["emp"][1]
    assert p["member"][0] == "insider" and p["reviewer"][0] == "outsider"


def test_coding_agent_accounts_count_as_ai_not_plain_bots():
    con = make_con({"prs": [pr(1, "copilot-swe-agent", typ="Bot", ai="bot"),
                            pr(2, "devin-ai-integration[bot]", typ="Bot"),
                            pr(3, "renovate[bot]", typ="Bot", ai="bot")]})
    build_people(con)
    build_pr_class(con)
    assert classes(con) == {1: "ai", 2: "ai", 3: "bot"}


def stats(prs):
    con = make_con({"prs": prs})
    build_people(con)
    build_pr_class(con)
    build_repo_stats(con, NOW)
    cols = [d[0] for d in con.execute("SELECT * FROM repo_stats").description]
    return dict(zip(cols, con.execute("SELECT * FROM repo_stats").fetchone()))


def test_trial_error_3_small_samples_are_flagged_not_trusted():
    s = stats([pr(i, f"o{i}") for i in range(7)])
    assert (s["merged"], s["merge_rate"], s["merge_enough"]) == (7, 1.0, False)
    assert s["merge_low"] == pytest.approx(0.646, abs=0.001)
    big = stats([pr(i, f"o{i}", state="MERGED" if i % 2 else "CLOSED") for i in range(40)])
    assert big["merge_enough"] and big["merge_rate"] == 0.5


def test_bots_ai_insiders_and_unknown_are_excluded():
    s = stats([pr(1, "dependabot[bot]", typ="Bot"), pr(2, "o", ai="claude"), pr(3, "maint", assoc="MEMBER"),
               pr(4, None), pr(5, "real", state="CLOSED")])
    assert (s["outsider_prs"], s["merged"], s["closed"]) == (1, 0, 1)
    assert (s["bot_prs"], s["ai_prs"], s["insider_prs"]) == (1, 1, 1)


def test_truncated_window_is_reported():
    full = stats([pr(i, f"o{i}", created=i) for i in range(300)])
    assert not full["window_complete"] and full["window_days"] == 299
    short = stats([pr(1, "o", created=5)])
    assert short["window_complete"] and short["window_days"] == 365


def test_review_time_counts_only_maintainer_reviews():
    s = stats([pr(1, "a", review_by="coderabbitai[bot]", review_assoc="NONE", review_after_h=0.1),
               pr(2, "b", review_by="maint", review_assoc="MEMBER", review_after_h=12),
               pr(3, "c", review_by="passerby", review_assoc="NONE", review_after_h=1)])
    assert s["reviewed"] == 1 and s["median_review_hours"] == pytest.approx(12)


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


def test_fresh_outsider_claim_blocks_and_old_one_expires():
    s = signals({"issues": [issue(1), issue(2)],
                 "comments": [comment(1, "eager", "Hi! Can I work on this?", 3),
                              comment(2, "eager", "I'd like to work on this", 20)]})
    assert s[1]["available"] is False and "claimed recently" in s[1]["blocked_by"] and s[1]["claimers"] == 1
    assert s[2]["available"] is True


def test_assignee_open_pr_and_maintainer_wait_block():
    s = signals({"issues": [issue(1, assignees=1), issue(2, open_prs=1), issue(3)],
                 "comments": [comment(3, "maint", "Please wait, this needs design discussion first", 2,
                                      assoc="MEMBER")]})
    assert [s[n]["available"] for n in (1, 2, 3)] == [False, False, False]
    assert s[3]["blocked_by"] == "maintainer asked to wait"


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


def test_trial_error_4_label_that_insiders_actually_fix_is_flagged():
    prs = [pr(100 + i, "maint", assoc="MEMBER", merged_by="maint", lines=400, files=9) for i in range(9)]
    prs.append(pr(200, "newbie", lines=12, files=1))
    rows = [closed(i, fix=100 + i, fix_author="maint", assoc="MEMBER") for i in range(9)]
    rows.append(closed(50, fix=200, fix_author="newbie"))
    lt = trust({"prs": prs, "closed_issues": rows})["good first issue"]
    assert (lt["closed_n"], lt["insider_fixes"], lt["outsider_fixes"]) == (10, 9, 1)
    assert lt["outsider_share"] == 0.1 and lt["enough"] and lt["median_fix_lines"] == 400


def test_closed_issues_seen_only_through_refreshes_count_once():
    # Refreshes bring closed issues as issue rows; rows from crawlers that did not record fixes are left out.
    prs = [pr(400, "newbie"), pr(401, "maint", assoc="MEMBER")]
    refreshed = {"repo_id": 1, "number": 7, "state": "CLOSED", "state_reason": "COMPLETED",
                 "labels": ["good first issue"], "created_at": t(60), "closed_at": t(5), "linked_closed_prs": 0,
                 "fix_pr": 400, "fix_pr_state": "MERGED", "fix_author": "newbie", "fix_association": "NONE"}
    old = {"repo_id": 1, "number": 8, "state": "CLOSED", "labels": ["good first issue"], "created_at": t(60)}
    both = {**refreshed, "number": 9, "fix_pr": 401, "fix_author": "maint", "fix_association": "MEMBER"}
    lt = trust({"prs": prs, "issues": [refreshed, old, both],
                "closed_issues": [closed(9, fix=401, fix_author="maint", assoc="MEMBER")]})["good first issue"]
    assert (lt["closed_n"], lt["outsider_fixes"], lt["insider_fixes"], lt["other"]) == (2, 1, 1, 0)


def test_share_counts_only_fixes_with_a_known_author():
    # Repos that merge into release branches (symfony) close most issues without a linked PR.
    prs = [pr(500 + i, "newbie" if i < 5 else "maint", assoc="NONE" if i < 5 else "MEMBER") for i in range(10)]
    rows = [closed(i, fix=500 + i, fix_author="newbie" if i < 5 else "maint", assoc="NONE" if i < 5 else "MEMBER")
            for i in range(10)]
    rows += [closed(100 + i) for i in range(30)]
    lt = trust({"prs": prs, "closed_issues": rows})["good first issue"]
    assert (lt["closed_n"], lt["known_fixes"], lt["other"]) == (40, 10, 30)
    assert lt["outsider_share"] == 0.5 and lt["enough"]


def walls(**meta):
    return {w for w, _ in find_walls({"has_issues": True, "ai_policy_sha": None, "contributing_excerpt": "",
                                      "readme_excerpt": "", **meta})}


def test_real_text_that_is_not_a_wall():
    # Found on 80 live repos: license headers, product READMEs and welcoming AI rules are not walls.
    assert walls(contributing_excerpt="Licensed to the Apache Software Foundation (ASF) under one or more "
                                      "contributor license agreements.") == set()
    assert walls(contributing_excerpt="<!--\nLicensed to the ASF under one or more\n"
                                      "contributor license agreements. -->") == set()
    assert walls(contributing_excerpt="Licensed to the ASF under one or more\n# contributor license agreements.") == set()
    assert walls(readme_excerpt="An e-commerce template using Next.js and AI generated content.") == set()
    # Found on the 2,545 crawled repos: a banner image, a product pitch and the "major changes" README template.
    assert walls(readme_excerpt="![The AI Alliance banner](https://the-ai-alliance.github.io/logo.png)") == set()
    assert walls(readme_excerpt="Use AI on the documents you're not allowed to paste into ChatGPT.") == set()
    assert walls(readme_excerpt="Pull requests are welcome. For major changes, please open an issue first to "
                                "discuss what you would like to change.") == set()
    assert walls(contributing_excerpt="AI and translation tools may make mistakes; a human review is required.") == set()
    assert walls(contributing_excerpt="## Coding with AI We accept the use of AI-powered tools (GitHub Copilot, "
                                      "ChatGPT). Please mention it in your PR description.") == {"ai_policy"}
    assert walls(contributing_excerpt="If you're an AI agent, read the AI Guidelines below.") == {"ai_policy"}
    assert walls(contributing_excerpt="We do not accept AI-generated pull requests.") == {"ai_ban"}
    # Found in Phase 3 on a repo that merges 94% of outsider PRs: a licence rule, not a ban on outside PRs.
    assert walls(contributing_excerpt="We do not accept contributions that use other more restrictive licenses.") == set()
    assert walls(readme_excerpt="We are not accepting pull requests at this time.") == {"no_outside_prs"}


def test_only_real_walls_block():
    # AI rules such as "say when you used AI" are shown as rules, never as walls that hide an issue.
    assert walls(contributing_excerpt="Use of generative AI must be declared.") == {"ai_policy"}
    assert "ai_policy" not in BLOCKING
    assert {"cla", "dco", "issue_first", "ai_ban", "no_outside_prs", "issues_disabled"} <= BLOCKING


def test_every_candidate_has_an_honest_evidence_record():
    con = make_con({
        "repo_meta": [{"repo_id": 1, "name": "o/r", "has_issues": True, "contributing_excerpt": "Sign the CLA"}],
        "prs": [pr(i, f"o{i}") for i in range(7)] + [pr(50, "dependabot[bot]", typ="Bot")],
        "issues": [{"repo_id": 1, "number": 5, "title": "Fix typo", "state": "OPEN", "labels": ["good first issue"],
                    "assignees": 0, "linked_open_prs": 0, "created_at": t(10), "updated_at": t(1)},
                   {"repo_id": 1, "number": 6, "title": "Assigned", "state": "OPEN", "labels": ["bug"],
                    "assignees": 1, "created_at": t(10)}]})
    # Times are written in UTC whatever the machine's time zone (a laptop in India wrote +05:30 before).
    con.execute("SET TimeZone = 'Asia/Kolkata'")
    con.execute("INSERT INTO closed_issues BY NAME SELECT 1 AS repo_id, 40 AS number, ['good first issue'] AS labels, "
                "'COMPLETED' AS state_reason, $closed AS closed_at, 0 AS fix_pr, 'MERGED' AS fix_pr_state, "
                "'o0' AS fix_author, 'NONE' AS fix_association, $closed AS fetched_at", {"closed": t(20)})
    counts = build_all(con, NOW)
    assert counts["candidates"] == 1
    ev = json.loads(con.execute("SELECT evidence_json FROM candidates").fetchone()[0])
    assert ev["version"] == 1 and ev["availability"]["available"] is True
    assert ev["source"]["fetched_at"] == "2026-10-14T00:00:00Z"
    om = ev["repo"]["outsider_merge"]
    assert (om["merged"], om["decided"], om["enough"]) == (7, 7, False)
    assert ev["repo"]["excluded"]["bot_prs"] == 1
    assert "not enough evidence for outsider merge rate (7 decided PRs; need 20)" in ev["notes"]
    assert ev["walls"] == [{"wall": "cla", "blocking": True, "evidence": "Sign the CLA"}]
    # Every shown rate carries its counts, range and window, and thin evidence says so in plain words.
    lab = ev["labels"][0]
    assert (lab["label"], lab["closed_n"], lab["known_fixes"], lab["outsider_fixes"]) == ("good first issue", 1, 1, 1)
    assert {"low", "high"} <= set(lab) and lab["window_days"] == 365
    assert "not enough evidence for review time (0 maintainer reviews; need 5)" in ev["notes"]
    assert ("not enough evidence for label trust on 'good first issue' (1 fixes with a known author; need 10)"
            in ev["notes"])


def test_build_writes_parquet_outputs_and_a_bundle(monkeypatch, tmp_path):
    monkeypatch.setenv("MS_DATA_DIR", str(tmp_path))
    w = BatchWriter(tmp_path, "r1", now=lambda: NOW)
    w.add("prs", [pr(1, "a")])
    w.add("issues", [{"repo_id": 1, "number": 2, "state": "OPEN", "labels": ["help wanted"], "assignees": 0}])
    w.add("repo_meta", [{"repo_id": 1, "name": "o/r"}])
    w.flush()
    out = tmp_path / "out"
    assert main(["build", "--out", str(out)]) == 0
    assert pq.read_table(out / "candidates.parquet").num_rows == 1
    names = tarfile.open(out / "signals.tar").getnames()
    assert {"people.parquet", "repo_stats.parquet", "candidates.parquet"} <= set(names)


def test_null_and_ghost_authors_are_unknown():
    con = make_con({"prs": [pr(1, None), pr(2, "ghost"), pr(3, "real")]})
    build_people(con)
    build_pr_class(con)
    assert set(people(con)) == {"real", "maint"}
    assert classes(con) == {1: "unknown", 2: "unknown", 3: "outsider"}


def test_insider_bot_and_old_claims_do_not_block():
    s = signals({"issues": [issue(1)],
                 "comments": [comment(1, "maint", "I'll take this one", 1, assoc="MEMBER"),
                              comment(1, "stale", "Can I work on this? (bot template)", 1)]})
    assert s[1]["available"] is True


def test_label_spellings_are_normalized():
    lt = trust({"closed_issues": [closed(1, label="Good-First-Issue :wave:"), closed(2, label="good first issue"),
                                  closed(3, label="bug")],
                "issues": [{"repo_id": 1, "number": 9, "state": "OPEN", "labels": ["Good First Issue"],
                            "created_at": t(400)}]})
    assert set(lt) == {"good first issue"}
    assert lt["good first issue"]["closed_n"] == 2 and lt["good first issue"]["open_stale"] == 1


def test_refreshed_old_prs_do_not_stretch_the_covered_window():
    # A busy repo: its 300 newest PRs span 3 days; refreshes later bring back PRs created long ago.
    prs = [pr(i, f"o{i}", created=i / 100) for i in range(300)]
    prs += [pr(900, "late", created=200), pr(901, "older", created=700)]
    s = stats(prs)
    assert (s["window_complete"], s["window_days"], s["outsider_prs"]) == (False, 3, 300)


def test_a_maintainer_seen_only_behind_a_review_bot_still_counts():
    p = {**pr(1, "a", review_by="coderabbitai", review_assoc="NONE", review_after_h=0.1, merged_by="lead"),
         "first_human_review_by": "reviewer", "first_human_review_association": "MEMBER",
         "first_human_review_at": t(30) + timedelta(hours=6)}
    s = stats([p])
    assert s["reviewed"] == 1 and s["median_review_hours"] == pytest.approx(6)


def test_deleted_users_and_comment_bots_do_not_claim_or_count_as_interest():
    s = signals({"issues": [issue(1)],
                 "comments": [comment(1, "ghost", "Can I work on this?", 2),
                              comment(1, "github-actions", "Can I work on this? Run the template.", 2),
                              comment(1, "gopherbot", "I'd like to work on this", 1)]})
    assert s[1]["available"] is True and s[1]["claimers"] == 0 and s[1]["interest"] == 0


def test_deleted_or_moved_issues_are_not_candidates():
    s = signals({"issues": [issue(1), issue(2)],
                 "issue_events": [{"repo_id": 1, "number": 2, "event": "gone", "observed_at": "2026-10-14"}]})
    assert set(s) == {1}


def test_label_trust_counts_only_the_last_year():
    rows = [{**closed(i), "closed_at": t(800)} for i in range(12)]
    assert "good first issue" not in trust({"closed_issues": rows})


def test_build_refuses_to_publish_an_empty_bundle(monkeypatch, tmp_path):
    # A wrong store repo or token finds no crawl data; publishing that would replace the good bundle.
    monkeypatch.setenv("MS_DATA_DIR", str(tmp_path))
    assert main(["build", "--out", str(tmp_path / "out")]) == 1
    assert not (tmp_path / "out" / "signals.tar").exists()


def test_owner_files_and_comment_bot_types_mark_people():
    # The Phase 2 hand-check missed maintainers who are only listed in owner files.
    con = make_con({"prs": [pr(1, "x", merged_by="lead")],
                    "repo_meta": [{"repo_id": 1, "name": "o/r", "owner_logins": ["quietmaintainer"]}],
                    "comments": [{"repo_id": 1, "number": 9, "comment_id": 1, "author_login": "QuietMaintainer",
                                  "author_association": "CONTRIBUTOR", "created_at": None},
                                 {"repo_id": 1, "number": 9, "comment_id": 2, "author_login": "helper",
                                  "author_type": "Bot", "author_association": "NONE", "created_at": None}]})
    build_people(con)
    p = people(con)
    assert p["QuietMaintainer"][0] == "insider" and "in owner files" in p["QuietMaintainer"][1]
    assert p["helper"][0] == "bot"


# 6. Real bans on outside PRs stay walls.
def test_no_outside_prs_still_catches_to_and_for():
    from mergescout.signals.walls import find_walls
    for text in ("We are not accepting contributions to this repository at this time.",
                 "We are no longer accepting pull requests to this repo."):
        assert {w for w, _ in find_walls({"readme_excerpt": text})} == {"no_outside_prs"}


# Signals polish.
def test_bare_agent_names_count_as_ai_only_for_bot_accounts():
    con = make_con({"prs": [pr(1, "claude"), pr(2, "claude[bot]", typ="Bot"), pr(3, "Copilot", typ="Bot")]})
    build_people(con)
    build_pr_class(con)
    classes = dict(con.execute("SELECT number, author_class FROM pr_class").fetchall())
    assert classes == {1: "outsider", 2: "ai", 3: "ai"}


def test_evidence_times_use_z_and_the_configured_pr_cap():
    con = make_con({"repo_meta": [{"repo_id": 1, "name": "o/r"}],
                    "prs": [pr(i, f"o{i}", created=i / 10) for i in range(300)],
                    "issues": [{"repo_id": 1, "number": 5, "title": "x", "state": "OPEN", "labels": ["good first issue"],
                                "assignees": 0, "created_at": t(3), "updated_at": t(1)}]})
    build_all(con, NOW)
    ev = json.loads(con.execute("SELECT evidence_json FROM candidates").fetchone()[0])
    assert ev["computed_at"] == "2026-10-14T00:00:00Z"
    assert any(n.startswith("PR history covers only the last 30 days (newest 300 PRs)") for n in ev["notes"])


LIVE_NOW = datetime.now(timezone.utc)


def iso(days_ago):
    return (LIVE_NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


# 1. A wall mentioned only as a possibility is not a wall.
def test_hypothetical_walls_are_ignored():
    text = ("## Licence and CLA Contributions are licensed under Apache 2.0. A lighter alternative exists, should the "
            "CLA prove heavy for what it buys: the DCO (Developer Certificate of Origin), a Signed-off-by: line.")
    assert {w for w, _ in find_walls({"contributing_excerpt": text})} == {"cla"}
    assert {w for w, _ in find_walls({"contributing_excerpt": "All commits need a Signed-off-by line (DCO)."})} == {"dco"}
    # Review: list items are separate sentences, and "instead of" / "not optional" state real rules.
    real = {"- You must sign the [CLA](url)\n- Optionally, add a changelog entry": "cla",
            "Please open an issue first instead of sending a PR straight away.": "issue_first",
            "All commits need Signed-off-by (DCO)\n\n## Style\nRun black instead of yapf": "dco",
            "We do not accept AI-generated code; this is not optional": "ai_ban"}
    for text, wall in real.items():
        assert wall in {w for w, _ in find_walls({"contributing_excerpt": text})}, text


def gql_issue(**over):
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


# 6. Labels that say "not ready" make an issue unavailable.
def test_not_ready_labels_block():
    con = make_con({"prs": [pr(1, "x", merged_by="lead")],
                    "issues": [{"repo_id": 1, "number": n, "title": "t", "state": "OPEN", "labels": labels,
                                "assignees": 0, "created_at": t(10), "updated_at": t(1)}
                               for n, labels in ((1, ["Triage needed"]), (2, ["good first issue", "status: blocked"]),
                                                 (3, ["good first issue"]),
                                                 # Real repos (Ray, Nextcloud) auto-add "triage"; a beginner label
                                                 # added by a maintainer still invites outsiders.
                                                 (4, ["Good First Issue", "Triage needed"]))]})
    build_people(con)
    build_issue_signals(con, NOW)
    rows = dict(con.execute("SELECT number, available FROM issue_signals").fetchall())
    assert rows == {1: False, 2: False, 3: True, 4: True}
    s = live_answer(gql_issue(labels={"nodes": [{"name": "needs triage"}]})).issue_status("o", "r", 1)
    assert s["available"] is False and "label says not settled yet (needs triage)" in s["reasons"]
    # Review: golang keeps "Proposal" next to "Proposal-Accepted" and "help wanted" on real tasks.
    s = live_answer(gql_issue(labels={"nodes": [{"name": n} for n in ("Proposal", "Proposal-Accepted",
                                                                       "help wanted")]})).issue_status("o", "r", 1)
    assert s["available"] is True
    s = live_answer(gql_issue(labels={"nodes": [{"name": "help wanted"}, {"name": "status: blocked"}]})).issue_status(
        "o", "r", 1)
    assert s["available"] is False and "label says not ready (status: blocked)" in s["reasons"]
    s = live_answer(gql_issue(labels={"nodes": [{"name": "good first issue"}, {"name": "needs triage"}]})).issue_status(
        "o", "r", 1)
    assert s["available"] is True and "needs triage" in s["note"]


# Real labels (2026-10-16): these say the opposite of "not ready" or name a topic, so they must not block.
def test_ready_labels_that_look_like_waiting_do_not_block():
    labels = [["triage accepted"], ["never stale"], ["question bank"], ["stale"], ["Triage: confirmed"],
              ["kind/question"], ["0 - needs triage"], ["needs more info"], ["awaiting response"], ["duplicate"],
              ["triage needs pr"], ["triage needs info"],
              # Real labels saying someone is already on it; "s: unassigned" and "unresolved" mean the opposite.
              ["work in progress"], ["Status: In Progress"], ["claimed"], ["gssoc-assigned"], ["wait for review"],
              ["has PR"], ["fixed"], ["s: unassigned"], ["resolution: unresolved"]]
    con = make_con({"prs": [pr(1, "x", merged_by="lead")],
                    "issues": [{"repo_id": 1, "number": n, "title": "t", "state": "OPEN", "labels": ls,
                                "assignees": 0, "created_at": t(10), "updated_at": t(1)}
                               for n, ls in enumerate(labels, 1)]})
    build_people(con)
    build_issue_signals(con, NOW)
    rows = dict(con.execute("SELECT number, available FROM issue_signals").fetchall())
    assert [n for n, ok in sorted(rows.items()) if ok] == [1, 2, 3, 4, 5, 11, 20, 21]


# Real data (2026-10-16): CI accounts opened 460+ failing-test issues and were counted as maintainers.
def test_ci_accounts_are_bots_and_loose_synonyms_are_gone():
    con = make_con({"prs": [pr(1, "kibanamachine", assoc="MEMBER"), pr(2, "elasticsearchmachine", assoc="MEMBER")]})
    build_people(con)
    assert {k for (k,) in con.execute("SELECT kind FROM people WHERE login LIKE '%machine'").fetchall()} == {"bot"}
    assert '"cache"' not in fts_query("performance", synonyms=True) and '"session"' not in fts_query("auth", True)
