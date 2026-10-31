import json
from datetime import datetime, timezone

import httpx

from stackvitals.ci.api import ActionsAPI

NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)


def fake(routes: dict, calls: list | None = None):
    """A GitHub that answers by exact path (status, body); anything else is 404."""
    def handler(request):
        path = request.url.path
        if calls is not None:
            calls.append(path)
        status, body = routes.get(path, (404, {"message": "Not Found"}))
        if isinstance(body, (bytes, str)):
            return httpx.Response(status, content=body if isinstance(body, bytes) else body.encode())
        return httpx.Response(status, json=body)
    return lambda token, repo, **kw: ActionsAPI(token, repo, client=httpx.Client(transport=httpx.MockTransport(handler)),
                                                sleep=lambda s: None, **kw)


def test_codeowners_rules_keep_users_teams_and_emails_apart():
    from stackvitals.portal.owners import parse_codeowners
    text = "# owners\n*       @acme/core @amy\n/docs/  docs@acme.org\n\n*.py @bob   # python\n"
    assert parse_codeowners(text) == [("*", ["@acme/core", "@amy"]), ("/docs/", ["docs@acme.org"]), ("*.py", ["@bob"])]


def owner_routes(codeowners_at=".github/CODEOWNERS", errors=(), team_members=("amy",), members=("amy", "bob")):
    routes = {f"/repos/acme/api/contents/{codeowners_at}": (200, "* @acme/core @bob @gone\n"),
              "/repos/acme/api/codeowners/errors": (200, {"errors": [{"kind": "Unknown owner", "line": 1} for _ in errors]}),
              "/orgs/acme/teams/core/members": (200, [{"login": m} for m in team_members])}
    for m in members:
        routes[f"/orgs/acme/members/{m}"] = (204, b"")
        routes["/repos/acme/api/commits"] = (200, [{"author": {"login": "bob"}}])
    return routes


def test_owners_are_checked_not_just_read():
    # Paid portals trust the declared owners; here a departed user and an empty team make the status weak, with reasons.
    from stackvitals.portal.owners import owner_status
    api = fake(owner_routes())("t", "acme/api")
    s = owner_status(api, "acme", {"name": "acme/api", "default_branch": "main"}, NOW, {})
    assert s["status"] == "weak" and s["file"] == ".github/CODEOWNERS"
    assert any("gone" in r and "not a member" in r for r in s["reasons"]) and s["teams"] == {"acme/core": 1}
    good = fake(owner_routes(members=("amy", "bob", "gone")))("t", "acme/api")
    assert owner_status(good, "acme", {"name": "acme/api", "default_branch": "main"}, NOW, {})["status"] == "valid"


def test_a_repo_without_codeowners_gets_suggestions_marked_as_suggestions():
    from stackvitals.portal.owners import owner_status
    routes = {"/repos/acme/api/commits": (200, [{"author": {"login": "amy"}}] * 3 + [{"author": {"login": "bob"}}]
                                          + [{"author": {"login": "dependabot[bot]"}}] * 9)}
    s = owner_status(fake(routes)("t", "acme/api"), "acme", {"name": "acme/api", "default_branch": "main"}, NOW, {})
    assert s["status"] == "none" and s["suggested"] == ["amy", "bob"]


def test_reads_github_refuses_are_not_available_never_failures():
    from stackvitals.portal.github import NA, read
    api = fake({"/orgs/acme/teams/core/members": (403, {"message": "Resource not accessible by integration"})})("t", "acme/api")
    assert read(api, "/orgs/acme/teams/core/members") is NA and read(api, "/nothing/here") is NA


def test_the_repo_list_comes_from_the_installation_in_private_mode_and_public_repos_otherwise():
    from stackvitals.portal.inventory import list_repos
    repo = lambda n, private=False: {"full_name": f"acme/{n}", "name": n, "private": private, "archived": False, "fork": False,  # noqa: E731
                                     "language": "Python", "pushed_at": "2026-10-01T00:00:00Z", "default_branch": "main", "topics": []}
    routes = {"/installation/repositories": (200, {"total_count": 2, "repositories": [repo("api", True), repo("web")]}),
              "/orgs/acme/repos": (200, [repo("web")])}
    api = fake(routes)("t", "acme/portal")
    assert [r["name"] for r in list_repos(api, "acme", "private")] == ["acme/api", "acme/web"]
    assert [r["name"] for r in list_repos(api, "acme", "public")] == ["acme/web"]


def test_module_facts_come_from_each_repos_data_branch_when_it_exists():
    from stackvitals.portal.inventory import module_facts
    routes = {"/repos/acme/api/branches/stackvitals-data": (200, {"name": "stackvitals-data"}),
              "/repos/acme/api/contents/docs/badge.json": (200, json.dumps({"label": "CI first try", "message": "82%"})),
              "/repos/acme/api/contents/docs/community-score.json": (200, json.dumps({"message": "64/100"}))}
    facts = module_facts(fake(routes)("t", "acme/api"), "acme/api")
    assert facts == {"ci_first_try": "82%", "flow": None, "community_score": "64/100"}
    assert module_facts(fake({})("t", "acme/web"), "acme/web") is None  # no data branch: the suite isn't installed there


def test_private_repos_never_reach_a_public_page():
    from stackvitals.portal.pages import publishable
    repos = [{"name": "acme/api", "private": True}, {"name": "acme/web", "private": False}]
    assert [r["name"] for r in publishable(repos, destination_private=False)] == ["acme/web"]
    assert len(publishable(repos, destination_private=True)) == 2
