"""One rule for who is a person, a bot, an agent, an insider or an outsider, shared by every module and equal to the crawl's."""
import duckdb
import pytest

from stackvitals.core.actors import INSIDER_ASSOC, People, kind_of


def pr(n, au, assoc="CONTRIBUTOR", at="User", st="MERGED", merged_by=None, ev=(), cm=()):
    events = list(ev)
    if merged_by:
        events.append(["merged", f"2026-10-{n:02d}T00:00:00Z", merged_by])
    return {"t": "pr", "n": n, "au": au, "at": at, "as": assoc, "st": st, "cr": f"2026-09-{n:02d}T00:00:00Z",
            "mg": f"2026-10-{n:02d}T00:00:00Z" if st == "MERGED" else None, "ev": events, "cm": list(cm)}


def test_kind_of_follows_the_crawls_bot_and_agent_rules():
    assert kind_of("alice", "User") == "person"
    assert kind_of("dependabot[bot]") == "bot"
    assert kind_of("renovate", "Bot") == "bot"
    assert kind_of("bors", "User") == "bot"  # a known bot typed as a user
    assert kind_of("my-project-ci") == "bot"  # the name pattern comments carry
    assert kind_of("adamrtalbot", "User") == "person"  # surnames ending in bot are people
    assert kind_of("copilot-swe-agent[bot]") == "agent"
    assert kind_of("devin-ai-integration", "User") == "agent"
    assert kind_of("codex", "User") == "person"  # a plain word is an agent only when the account is a bot
    assert kind_of("codex[bot]") == "agent"
    assert kind_of("Claude", "Bot") == "agent"
    assert kind_of("ghost") == "unknown" and kind_of(None) == "unknown"


def test_people_find_insiders_by_what_they_do_not_only_by_the_label():
    prs = [pr(1, "lead", merged_by="lead"),  # merges own work: has write access
           pr(2, "newcomer", merged_by="quietlead"),  # quietlead shows as nobody's label but merges others
           pr(3, "member", assoc="MEMBER"),
           pr(4, "drive-by", st="CLOSED"),
           pr(5, "robot[bot]", at="Bot", merged_by="mergify[bot]"),
           pr(6, "visitor", ev=[["review", "2026-09-07T00:00:00Z", "reviewer", "APPROVED", "COLLABORATOR", "User", False]],
              cm=[["2026-09-08T00:00:00Z", "owner-commenter", "OWNER", "User", True]])]
    issues = [{"t": "issue", "n": 9, "au": "triager", "as": "MEMBER", "at": "User", "cm": []}]
    people = People(prs, issues, owner_logins=["Listed-In-Codeowners"])
    assert people.role("lead") == "insider" and "merges own" in people.reasons("lead")
    assert people.role("quietlead") == "insider" and "merges others" in people.reasons("quietlead")
    assert people.role("member") == "insider" and "listed role" in people.reasons("member")
    assert people.role("reviewer") == "insider" and people.role("owner-commenter") == "insider"
    assert people.role("triager") == "insider"
    assert people.role("listed-in-codeowners") == "insider" and "in owner files" in people.reasons("listed-in-codeowners")
    assert people.role("newcomer") == "outsider" and people.role("drive-by") == "outsider" and people.role("visitor") == "outsider"
    # Bots are bots even when they merge, and someone never seen is an outsider with no reasons.
    assert people.role("mergify[bot]") == "bot" and people.role("robot[bot]") == "bot"
    assert people.role("stranger") == "outsider" and people.reasons("stranger") == ""
    # Names keep the case they were seen with; lookups never depend on case (GitHub logins don't).
    assert people.insiders() == {"lead", "quietlead", "member", "reviewer", "owner-commenter", "triager", "Listed-In-Codeowners"}
    assert people.is_insider("LEAD") and people.is_insider("listed-in-codeowners") and not people.is_insider("Newcomer")


def test_outside_prs_are_by_people_who_are_not_insiders_bots_or_agents():
    prs = [pr(1, "lead", merged_by="lead"), pr(2, "newcomer"), pr(3, "dependabot[bot]", at="Bot"),
           pr(4, "copilot-swe-agent[bot]", at="Bot"), pr(5, "ghost")]
    people = People(prs)
    assert [p["n"] for p in prs if people.is_outside(p)] == [2]
    assert people.actor("copilot-swe-agent[bot]").kind == "agent"
    assert people.actor("newcomer").role == "outsider" and people.actor("newcomer").kind == "person"
    assert people.actor("lead").reasons == ("merges own",)
    assert INSIDER_ASSOC == frozenset({"OWNER", "MEMBER", "COLLABORATOR"})


def test_the_python_rule_gives_the_same_kinds_as_the_crawls_sql():
    # The crawl's build_people runs in DuckDB over its tables; the same records through both must agree on every login.
    from mergescout.signals.identity import build_people
    rows = [("lead", "CONTRIBUTOR", "User", "MERGED", "lead"), ("newcomer", "NONE", "User", "MERGED", "quietlead"),
            ("member", "MEMBER", "User", "OPEN", None), ("drive-by", "CONTRIBUTOR", "User", "CLOSED", None),
            ("robot[bot]", "NONE", "Bot", "MERGED", "mergify[bot]"), ("bors", "CONTRIBUTOR", "User", "MERGED", "lead"),
            ("visitor", "NONE", "User", "OPEN", None), ("adamrtalbot", "CONTRIBUTOR", "User", "CLOSED", None),
            ("some-ci", "NONE", "User", "CLOSED", None)]
    con = duckdb.connect()
    con.execute("CREATE TABLE prs (repo_id INT, author_login TEXT, author_association TEXT, author_type TEXT, state TEXT, "
                "merged_by TEXT, first_review_by TEXT, first_review_association TEXT, first_human_review_by TEXT, "
                "first_human_review_association TEXT)")
    con.executemany("INSERT INTO prs VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [(au, assoc, typ, st, mb, "reviewer" if au == "visitor" else None, "COLLABORATOR" if au == "visitor" else None,
                      None, None) for au, assoc, typ, st, mb in rows])
    con.execute("CREATE TABLE issues (repo_id INT, author_login TEXT, author_association TEXT)")
    con.execute("INSERT INTO issues VALUES (1, 'triager', 'MEMBER')")
    con.execute("CREATE TABLE closed_issues (repo_id INT, author_login TEXT, author_association TEXT)")
    con.execute("CREATE TABLE comments (repo_id INT, author_login TEXT, author_association TEXT, author_type TEXT)")
    con.execute("INSERT INTO comments VALUES (1, 'owner-commenter', 'OWNER', 'User')")
    con.execute("CREATE TABLE repo_meta (repo_id INT, owner_logins TEXT[])")
    con.execute("INSERT INTO repo_meta VALUES (1, ['Listed-In-Codeowners'])")
    build_people(con)
    sql = {login: kind for login, kind in con.execute("SELECT login, kind FROM people").fetchall()}
    prs = [pr(i + 1, au, assoc, typ, st, mb,
              ev=[["review", "2026-09-07T00:00:00Z", "reviewer", "APPROVED", "COLLABORATOR", "User", False]] if au == "visitor" else (),
              cm=[["2026-09-08T00:00:00Z", "owner-commenter", "OWNER", "User", True]] if au == "visitor" else ())
           for i, (au, assoc, typ, st, mb) in enumerate(rows)]
    issues = [{"t": "issue", "n": 9, "au": "triager", "as": "MEMBER", "at": "User", "cm": []}]
    people = People(prs, issues, owner_logins=["Listed-In-Codeowners"])
    ours = {login: people.role(login) for login in sql}
    assert ours == sql
    assert set(sql) >= {"lead", "quietlead", "member", "robot[bot]", "mergify[bot]", "bors", "reviewer", "owner-commenter",
                        "triager", "some-ci", "adamrtalbot"}
