"""Identity merges by confidence: a tracker assignee is matched to a GitHub login by an alias, by an email whose name part
is the login (counted), or by a name that only looks like the login (suggested as a ready-made alias, never counted)."""
from stackvitals.core import identity

LOGINS = {"kaushik-yadav", "bo", "ana-lee", "anal-ee"}


def test_alias_beats_everything_and_email_name_part_is_high():
    ident = {"aliases": {"jira:a1": "bo"}}
    assert identity.match(ident, "jira:a1", "ana-lee@acme.com", None, LOGINS) == ("bo", "alias")
    assert identity.match({}, "jira:a2", "Bo@acme.com", None, LOGINS) == ("bo", "high")
    assert identity.match({}, "jira:a2", "4411+kaushik-yadav@users.noreply.github.com", None, LOGINS) == ("kaushik-yadav", "high")


def test_a_name_that_only_looks_like_a_login_is_medium_and_must_be_unique():
    assert identity.match({}, "jira:a3", "kaushik.yadav@acme.com", None, LOGINS) == ("kaushik-yadav", "medium")
    assert identity.match({}, "linear:u1", None, "Kaushik Yadav", LOGINS) == ("kaushik-yadav", "medium")
    # ana-lee and anal-ee both read "analee": two candidates, so no guess.
    assert identity.match({}, "jira:a4", None, "Ana Lee", LOGINS) == (None, None)
    assert identity.match({}, "jira:a5", "someone@acme.com", "Someone Else", LOGINS) == (None, None)


def test_team_counts_take_aliases_and_high_matches_and_suggest_the_rest():
    ident = {"teams": {"web": ["bo", "kaushik-yadav"]}}
    done = {"cat": "DONE", "resolved": "2026-10-10T00:00:00Z"}
    issues = [{**done, "assignee": "jira:a2", "assignee_email": "bo@acme.com"},
              {**done, "assignee": "jira:a3", "assignee_email": "kaushik.yadav@acme.com"},
              {**done, "assignee": "jira:a3", "assignee_email": "kaushik.yadav@acme.com"},
              {**done, "assignee": "jira:a9"}]
    got = identity.issues_by_team(issues, ident, since="2026-10-01T00:00:00Z", logins=LOGINS)
    assert got["teams"] == {"web": {"done": 1}}
    assert (got["matched"], got["by_email"], got["unmatched"]) == (1, 1, 3)
    assert got["suggested"] == [{"ref": "jira:a3", "login": "kaushik-yadav", "issues": 2, "line": '"jira:a3" = "kaushik-yadav"'}]


def test_without_logins_the_old_shape_is_kept():
    issues = [{"cat": "DONE", "resolved": "2026-10-10T00:00:00Z", "assignee": "jira:a1"}]
    got = identity.issues_by_team(issues, {"aliases": {"jira:a1": "bo"}, "teams": {"web": ["bo"]}}, since="2026-10-01T00:00:00Z")
    assert got == {"teams": {"web": {"done": 1}}, "matched": 1, "unmatched": 0}
