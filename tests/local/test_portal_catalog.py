import json
import subprocess
from datetime import datetime, timedelta, timezone

import pytest
from test_portal_m1 import NOW, fake


@pytest.fixture(autouse=True)
def _offline(monkeypatch, tmp_path):
    # Unit tests never go to the network: no GraphQL, no OpenSSF, no benchmark downloads.
    import httpx

    import stackvitals.portal.action as pa
    import stackvitals.portal.cli as pc
    nothing = lambda: httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404, json={})))  # noqa: E731
    for mod in (pa, pc):
        monkeypatch.setattr(mod, "_scorecard_client", nothing)
        monkeypatch.setattr(mod, "_gql", lambda token: None)
    for name in ("STACKVITALS_BENCH_URL", "STACKVITALS_FLOW_BENCH_URL"):
        monkeypatch.setenv(name, str(tmp_path / "missing.json"))


def repo(n, private=False, archived=False):
    return {"full_name": f"acme/{n}", "name": n, "private": private, "archived": archived, "fork": False, "language": "Go",
            "pushed_at": "2026-10-10T00:00:00Z", "default_branch": "main", "topics": []}


def org_routes(names=("api", "web", "cli"), private=()):
    routes = {"/orgs/acme/repos": (200, [repo(n, n in private) for n in names]),
              "/installation/repositories": (200, {"repositories": [repo(n, n in private) for n in names]})}
    for n in names:
        routes[f"/repos/acme/{n}/contents/CODEOWNERS"] = (200, "* @amy\n")
        routes[f"/repos/acme/{n}/rules/branches/main"] = (200, [{"type": "pull_request"}, {"type": "deletion"}])
    routes["/orgs/acme/members/amy"] = (204, b"")
    return routes


def test_the_catalog_refreshes_oldest_first_and_keeps_earlier_results_when_the_budget_runs_out():
    from stackvitals.portal.catalog import build_catalog
    calls = []
    api = fake(org_routes(), calls)("t", "acme/portal", max_requests=20)  # 2 to list, 8 per repo
    previous = {"repos": [{"name": "acme/api", "checked": "2026-10-18T00:00:00Z", "owners": {"status": "valid"}},
                          {"name": "acme/web", "checked": "2026-10-10T00:00:00Z", "owners": {"status": "none"}}]}
    c = build_catalog(api, "acme", "public", NOW, previous=previous)
    by = {r["name"]: r for r in c["repos"]}
    # cli was never checked and web is older than api, so they go first; api keeps yesterday's result.
    assert by["acme/cli"]["checked"] == "2026-10-19T12:00:00Z" and by["acme/web"]["checked"] == "2026-10-19T12:00:00Z"
    assert by["acme/api"]["checked"] == "2026-10-18T00:00:00Z" and c["complete"] is False
    assert by["acme/cli"]["owners"]["status"] == "valid" and by["acme/cli"]["rules"] == ["deletion", "pull_request"]


def test_archived_repos_are_listed_but_not_checked():
    from stackvitals.portal.catalog import build_catalog
    routes = org_routes(("api",))
    routes["/orgs/acme/repos"] = (200, [repo("api"), repo("old", archived=True)])
    c = build_catalog(fake(routes)("t", "acme/portal"), "acme", "public", NOW)
    old = next(r for r in c["repos"] if r["name"] == "acme/old")
    assert old["archived"] and "owners" not in old and c["complete"] is True
    assert c["requests"] > 0  # the run's API cost is kept, for the cost check and the summary


def test_the_catalog_page_counts_owner_status_and_never_lists_private_repos_on_a_public_page():
    from stackvitals.portal.catalog import build_catalog
    from stackvitals.portal.pages import render_catalog
    c = build_catalog(fake(org_routes(private=("api",)))("t", "acme/portal"), "acme", "private", NOW)
    private_page = render_catalog(c, destination_private=True)
    public_page = render_catalog(c, destination_private=False)
    assert "acme/api" in private_page and "acme/api" not in public_page and "3 repos" in private_page
    assert "Owners: 3 valid" in private_page and "@" not in public_page.replace("@​", "")


def remote(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    return bare


def show(bare, path):
    return subprocess.run(["git", "show", f"stackvitals-data:{path}"], cwd=bare, capture_output=True, text=True).stdout


def test_the_action_keeps_daily_history_and_pages_in_the_portal_repo(tmp_path):
    from stackvitals.portal.action import run_portal_action
    routes = org_routes(private=("api",))
    routes["/repos/acme/portal"] = (200, {"full_name": "acme/portal", "private": True})
    bare = remote(tmp_path)
    env = {"GITHUB_REPOSITORY": "acme/portal", "GITHUB_TOKEN": "builtin", "STACKVITALS_PORTAL_TOKEN": "app-token",
           "STACKVITALS_REMOTE": bare.as_uri(), "GITHUB_EVENT_NAME": "schedule", "RUNNER_TEMP": str(tmp_path / "tmp"),
           "GITHUB_STEP_SUMMARY": str(tmp_path / "s.md")}
    out = run_portal_action(env, now=NOW, make_api=fake(routes))
    assert out["mode"] == "private" and out["repos"] == 3 and out["pushed"]
    assert "acme/api" in show(bare, "portal/README.md") and json.loads(show(bare, "portal/catalog.json"))["org"] == "acme"
    assert show(bare, "portal/history/2026-10-19.json")
    assert "Portal" in (tmp_path / "s.md").read_text(encoding="utf-8")


def test_a_public_portal_repo_never_gets_private_repo_data(tmp_path):
    from stackvitals.portal.action import run_portal_action
    routes = org_routes(private=("api",))
    routes["/repos/acme/portal"] = (200, {"full_name": "acme/portal", "private": False})
    bare = remote(tmp_path)
    env = {"GITHUB_REPOSITORY": "acme/portal", "GITHUB_TOKEN": "builtin", "STACKVITALS_PORTAL_TOKEN": "app-token",
           "STACKVITALS_REMOTE": bare.as_uri(), "GITHUB_EVENT_NAME": "schedule", "RUNNER_TEMP": str(tmp_path / "tmp"),
           "GITHUB_STEP_SUMMARY": str(tmp_path / "s.md")}
    run_portal_action(env, now=NOW, make_api=fake(routes))
    everything = show(bare, "portal/README.md") + show(bare, "portal/catalog.json") + show(bare, "portal/history/2026-10-19.json")
    assert "acme/api" not in everything and "acme/web" in everything
    assert "private repos were left out" in (tmp_path / "s.md").read_text(encoding="utf-8")


def test_the_local_report_lists_an_orgs_repos_with_owner_status(tmp_path, monkeypatch, capsys):
    from stackvitals.portal.cli import main
    monkeypatch.setenv("STACKVITALS_HOME", str(tmp_path / "home"))
    assert main(["report", "acme"], now=NOW, make_api=fake(org_routes()), tok="tok") == 0
    out = capsys.readouterr().out
    assert "acme/api" in out and "valid" in out


def test_the_action_runs_portal_and_the_suite_knows_the_module(monkeypatch, capsys, tmp_path):
    import stackvitals.ci.cli as cli
    import stackvitals.portal.action as pa
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    for key, value in (("GITHUB_EVENT_NAME", "schedule"), ("GITHUB_REPOSITORY", "o/r"), ("STACKVITALS_TOKEN", "tok"),
                       ("STACKVITALS_REMOTE", bare.as_uri()), ("RUNNER_TEMP", str(tmp_path / "tmp"))):
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(pa, "run_portal_action", lambda env, **k: {"mode": "private", "repos": 42, "complete": True,
                                                                     "pushed": True, "left_out": 0})
    assert cli.action_main(["--modules", "portal"]) == 0
    # A fresh data branch: the job publishes the app itself, so the data is saved even though the step wrote nothing.
    assert "Portal: 42 repos (private mode), data saved." in capsys.readouterr().out
    from stackvitals.cli import MODULES
    assert "portal" in MODULES


def test_portal_init_prints_a_daily_workflow_with_the_app_step_ready_to_switch_on(capsys):
    from stackvitals.portal.cli import main
    assert main(["init"], tok="tok") == 0
    text = capsys.readouterr().out
    assert "modules: portal" in text and "cron:" in text and "contents: write" in text
    assert "# - uses: actions/create-github-app-token" in text and "portal-token" in text


def test_the_setup_check_says_what_the_token_can_and_cannot_read(capsys):
    from stackvitals.portal.cli import main
    routes = org_routes(private=("api",))
    routes["/orgs/acme/teams"] = (403, {"message": "Resource not accessible by integration"})
    assert main(["check", "acme"], make_api=fake(routes), tok="tok") == 0
    out = capsys.readouterr().out
    assert "3 repos visible (1 private)" in out and "teams: not available" in out and "CODEOWNERS: readable" in out


def test_forks_are_listed_but_not_judged_and_bot_accounts_are_never_suggested():
    # Real data (astral-sh): forks carried their upstream's CODEOWNERS (peps: 783 errors), and zaniebot was a suggestion.
    from stackvitals.portal.catalog import build_catalog
    from stackvitals.portal.owners import suggest
    routes = org_routes(("api",))
    routes["/orgs/acme/repos"] = (200, [repo("api"), {**repo("peps"), "fork": True}])
    c = build_catalog(fake(routes)("t", "acme/portal"), "acme", "public", NOW)
    peps = next(r for r in c["repos"] if r["name"] == "acme/peps")
    assert peps["fork"] and "owners" not in peps
    commits = [{"author": {"login": who}} for who in ("zaniebot", "astral-docs-bot", "amy", "amy", "renovate[bot]")]
    assert suggest(fake({"/repos/acme/api/commits": (200, commits)})("t", "acme/api"), "acme/api", NOW) == ["amy"]


def test_the_catalog_reads_repo_files_and_scorecard_results_for_public_repos_only():
    import httpx

    from stackvitals.portal.catalog import build_catalog
    routes = org_routes(("api", "web"), private=("api",))
    routes["/repos/acme/web/community/profile"] = (200, {"files": {"readme": {"u": 1}, "license": {"u": 1}}})
    seen = []

    def sc(request):
        seen.append(request.url.path)
        return httpx.Response(200, json={"date": "2026-10-13", "checks": [{"name": "Security-Policy", "score": 10}]})
    c = build_catalog(fake(routes)("t", "acme/portal"), "acme", "private", NOW, scorecard_client=httpx.Client(transport=httpx.MockTransport(sc)))
    by = {r["name"]: r for r in c["repos"]}
    assert by["acme/web"]["docs"]["readme"] is True and by["acme/web"]["scorecard"] == {"Security-Policy": 10}
    assert by["acme/api"]["scorecard"] is None and seen == ["/projects/github.com/acme/web"]


def test_levels_and_the_most_failed_rules_reach_the_page_and_portal_toml_is_used():
    from stackvitals.portal.action import run_portal_action
    routes = org_routes(("api", "web"))
    routes["/repos/acme/portal"] = (200, {"full_name": "acme/portal", "private": True})
    routes["/repos/acme/portal/contents/portal.toml"] = (200, '[[rule]]\nid = "reviews"\ncheck = "branch_rule"\nrule = "required_signatures"\n'
                                                              'level = "bronze"\n')
    bare = remote(NOW_DIR := __import__("pathlib").Path(__import__("tempfile").mkdtemp()))
    env = {"GITHUB_REPOSITORY": "acme/portal", "GITHUB_TOKEN": "builtin", "STACKVITALS_REMOTE": bare.as_uri(),
           "GITHUB_EVENT_NAME": "schedule", "RUNNER_TEMP": str(NOW_DIR / "tmp"), "GITHUB_STEP_SUMMARY": str(NOW_DIR / "s.md")}
    run_portal_action(env, now=NOW, make_api=fake(routes))
    page = show(bare, "portal/README.md")
    assert "| Level |" in page and "Levels: 0 gold, 0 silver, 0 bronze, 2 below bronze" in page
    assert "Most failed rules: reviews (2 repos)" in page
    catalog = json.loads(show(bare, "portal/catalog.json"))
    assert catalog["repos"][0]["score"]["results"][0]["id"] == "reviews"


def test_campaigns_reach_the_page_and_a_token_that_cannot_open_issues_gets_a_note(tmp_path):
    from stackvitals.portal.action import run_portal_action
    routes = org_routes(("api", "web"))
    routes["/repos/acme/portal"] = (200, {"full_name": "acme/portal", "private": True})
    routes["/repos/acme/portal/contents/portal.toml"] = (200, '[[rule]]\nid = "codeowners"\ncheck = "owners_present"\nlevel = "bronze"\n\n'
                                                              '[[campaign]]\nid = "c1"\ntitle = "Owners everywhere"\nrules = ["codeowners"]\n'
                                                              'until = "2026-12-31"\n')
    routes["/repos/acme/web/contents/CODEOWNERS"] = (404, {"message": "Not Found"})
    bare = remote(tmp_path)
    env = {"GITHUB_REPOSITORY": "acme/portal", "GITHUB_TOKEN": "builtin", "STACKVITALS_REMOTE": bare.as_uri(),
           "GITHUB_EVENT_NAME": "schedule", "RUNNER_TEMP": str(tmp_path / "tmp"), "GITHUB_STEP_SUMMARY": str(tmp_path / "s.md")}
    run_portal_action(env, now=NOW, make_api=fake(routes))
    page = show(bare, "portal/README.md")
    assert "## Campaign: Owners everywhere" in page and "1 of 2 repos pass" in page and "73 days left" in page
    history = json.loads(show(bare, "portal/history/2026-10-19.json"))
    assert {r["name"]: r["language"] for r in history["repos"]}["acme/api"] == "Go"
    assert "issues: write" in (tmp_path / "s.md").read_text(encoding="utf-8")


def test_the_app_link_opens_githubs_form_with_read_only_permissions_and_no_webhook(capsys):
    from urllib.parse import parse_qs, urlparse

    from stackvitals.portal.cli import main
    assert main(["app-link", "acme"], tok="tok") == 0
    url = capsys.readouterr().out.strip().splitlines()[0]
    q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    assert url.startswith("https://github.com/organizations/acme/settings/apps/new?")
    assert q["webhook_active"] == "false" and q["public"] == "false"
    assert {k: q[k] for k in ("actions", "contents", "metadata", "members", "organization_custom_properties")} == \
        {k: "read" for k in ("actions", "contents", "metadata", "members", "organization_custom_properties")}
    assert not [v for v in q.values() if v == "write"]


def test_the_portal_workflow_can_keep_its_tracking_issues():
    from stackvitals.portal.cli import WORKFLOW
    assert "issues: write" in WORKFLOW
