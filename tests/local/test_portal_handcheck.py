"""Fixes from the hand-check of 30 owner results and 20 rule results in astral-sh, pypa and charmbracelet."""
from datetime import datetime, timezone

from test_portal_m1 import fake
from test_portal_reviews import Fake, pr

from stackvitals.portal.scorecard import evaluate, load_rules

NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)


def test_suggestions_prefer_people_who_review_and_skip_placeholders():
    # pypa/advisory-database: "invalid-email-address" (GitHub's placeholder) was the top suggestion.
    from stackvitals.portal.inventory import review_stats
    from stackvitals.portal.owners import owner_status, suggest
    nodes = [pr(10 + i, 2, reviewer="maint" if i < 7 else "lead") for i in range(10)]
    assert review_stats(Fake(nodes), "acme/web", NOW)["reviewers"] == ["maint", "lead"]
    commits = [{"author": {"login": who}} for who in ["invalid-email-address"] * 9 + ["web-flow", "ghost", "amy"]]
    assert suggest(fake({"/repos/acme/web/commits": (200, commits)})("t", "acme/web"), "acme/web", NOW) == ["amy"]
    s = owner_status(fake({})("t", "acme/web"), "acme", {"name": "acme/web", "default_branch": "main"}, NOW, {},
                     reviewers=["maint", "lead"])
    assert s["suggested"] == ["maint", "lead"] and s["suggested_from"] == "recent reviews"


def test_a_codeowners_without_a_catch_all_line_is_weak_and_unseen_teams_are_said():
    # pypa/packaging.python.org names 5 paths; astral-sh/ruff's 11 teams were never visible to the token.
    from stackvitals.portal.owners import owner_status
    routes = {"/repos/acme/web/contents/CODEOWNERS": (200, "/docs/ @amy\n/src/api/ @acme/core\n")}
    s = owner_status(fake(routes)("t", "acme/web"), "acme", {"name": "acme/web", "default_branch": "main"}, NOW, {},
                     members_visible=False)
    assert s["status"] == "weak" and any("no catch-all" in r for r in s["reasons"])
    assert any("team members" in n for n in s["notes"]) and any("org membership" in n for n in s["notes"])
    routes = {"/repos/acme/web/contents/CODEOWNERS": (200, "* @amy\n")}
    ok = owner_status(fake(routes)("t", "acme/web"), "acme", {"name": "acme/web", "default_branch": "main"}, NOW, {},
                      members_visible=False)
    assert ok["status"] == "valid" and ok["file"] == "CODEOWNERS"


def rules(text):
    return load_rules(text)


def test_classic_branch_protection_makes_the_review_rule_unknown_not_failed():
    # pypa/installer: protected by classic branch protection, which the rules endpoint doesn't show.
    rs, ex = rules('[[rule]]\nid = "r"\ncheck = "branch_rule"\nrule = "pull_request"\nlevel = "bronze"\n')
    repo = {"name": "acme/x", "rules": [], "protected": True, "default_branch": "unstable/v1"}
    r = evaluate(repo, rs, ex, NOW, None)["results"][0]
    assert r["result"] == "not available" and "classic branch protection" in r["evidence"]
    r = evaluate({**repo, "protected": False}, rs, ex, NOW, None)["results"][0]
    assert r["result"] == "fail" and "unstable/v1" in r["evidence"]


def test_files_from_the_orgs_default_community_files_say_so():
    from stackvitals.portal.inventory import repo_files
    profile = {"files": {"readme": {"html_url": "https://github.com/acme/x/blob/main/README.md"},
                         "contributing": {"html_url": "https://github.com/acme/.github/blob/main/CONTRIBUTING.md"}}}
    docs = repo_files(fake({"/repos/acme/x/community/profile": (200, profile)})("t", "acme/x"), {"name": "acme/x"})
    assert docs["contributing"] is True and docs["org_defaults"] == ["contributing"]
    rs, ex = rules('[[rule]]\nid = "c"\ncheck = "files"\nfiles = ["contributing"]\nlevel = "bronze"\n')
    r = evaluate({"name": "acme/x", "docs": docs}, rs, ex, NOW, None)["results"][0]
    assert r["result"] == "pass" and "org default" in r["evidence"]


def test_security_policy_counts_a_real_policy_and_scorecard_evidence_carries_its_date():
    # pypa/gh-action-pypi-publish has .github/SECURITY.md but scores 4/10; the default asked for 10.
    from stackvitals.portal.scorecard import DEFAULT_RULES
    rs, ex = load_rules(DEFAULT_RULES)
    policy = next(r for r in rs if r["id"] == "security-policy")
    assert policy["min"] <= 4
    r = evaluate({"name": "acme/x", "scorecard": {"Security-Policy": 4}, "openssf": {"date": "2026-10-12"}},
                 [policy], ex, NOW, None)["results"][0]
    assert r["result"] == "pass" and "2026-10-12" in r["evidence"]


def test_a_missing_file_is_counted_once_and_the_orgs_github_repo_is_not_judged():
    from stackvitals.portal.catalog import build_catalog
    rs, ex = rules('[[rule]]\nid = "ov"\ncheck = "owners_valid"\nlevel = "silver"\n')
    r = evaluate({"name": "acme/x", "owners": {"status": "none"}}, rs, ex, NOW, None)["results"][0]
    assert r["result"] == "not available"  # the codeowners rule already reports the missing file
    repo = {"full_name": "acme/.github", "private": False, "archived": False, "fork": False, "default_branch": "main"}
    c = build_catalog(fake({"/orgs/acme/repos": (200, [repo])})("t", "acme/portal"), "acme", "public", NOW)
    assert "owners" not in c["repos"][0]
