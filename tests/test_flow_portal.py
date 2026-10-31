"""Portal: the org catalog. One guard per real-data finding and privacy rule; task tests live in tests/local."""
from datetime import datetime, timezone

import httpx

from stackvitals.ci.api import ActionsAPI

NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)


def test_private_repos_never_reach_a_public_page_and_forks_are_not_judged():
    # Real data (astral-sh): forks carried their upstream's CODEOWNERS (peps: 783 errors), so they are listed, not checked.
    from stackvitals.portal.catalog import build_catalog
    from stackvitals.portal.pages import publishable, render_catalog
    repo = lambda n, private=False, fork=False: {"full_name": f"acme/{n}", "private": private, "archived": False, "fork": fork,  # noqa: E731
                                                 "language": "Go", "pushed_at": "2026-10-10T00:00:00Z", "default_branch": "main"}
    routes = {"/orgs/acme/repos": [repo("api", private=True), repo("web"), repo("peps", fork=True)],
              "/repos/acme/web/contents/CODEOWNERS": "* @amy\n", "/repos/acme/api/contents/CODEOWNERS": "* @amy\n"}

    def handler(request):
        body = routes.get(request.url.path)
        if body is None:
            return httpx.Response(404, json={"message": "Not Found"})
        return httpx.Response(200, content=body.encode()) if isinstance(body, str) else httpx.Response(200, json=body)
    api = ActionsAPI("t", "acme/portal", client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    c = build_catalog(api, "acme", "public", NOW)
    assert "owners" not in next(r for r in c["repos"] if r["name"] == "acme/peps")
    assert [r["name"] for r in publishable(c["repos"], destination_private=False)] == ["acme/peps", "acme/web"]
    page = render_catalog(c, destination_private=False)
    assert "acme/api" not in page and "left out of this page because the portal repo is public" in page


def test_campaign_progress_and_burn_down_come_from_the_daily_history(tmp_path):
    import json

    from stackvitals.portal.campaigns import load_campaigns, progress
    c = load_campaigns('[[campaign]]\nid = "c"\ntitle = "Owners"\nrules = ["codeowners"]\nuntil = "2026-12-31"\n')[0]
    for day, failing in (("2026-10-01", 3), ("2026-10-10", 2)):
        rows = [{"name": f"acme/r{i}", "failed": ["codeowners"] if i < failing else []} for i in range(3)]
        (tmp_path / f"{day}.json").write_text(json.dumps({"repos": rows}), encoding="utf-8")
    repo = lambda i, ok: {"name": f"acme/r{i}", "checked": "x", "score": {"results": [  # noqa: E731
        {"id": "codeowners", "result": "pass" if ok else "fail"}]}}
    p = progress(c, [repo(0, False), repo(1, True), repo(2, True)], tmp_path, NOW)
    assert p["burn_down"] == [["2026-10-01", 3], ["2026-10-10", 2], ["2026-10-19", 1]] and p["days_left"] == 73


def test_campaign_reminders_go_out_once_at_seven_days_and_one_day():
    """P11 M3: Cortex and OpsLevel's deadline nudges, never repeated."""
    from datetime import datetime, timezone

    from stackvitals.portal.campaigns import reminders_due
    p = {"id": "owners", "days_left": 7, "failing": ["org/a"]}
    now = datetime(2026, 10, 25, tzinfo=timezone.utc)
    assert reminders_due([p], {}, now) == [(p, 7)] and reminders_due([p], {"owners": [7]}, now) == []
    assert reminders_due([{**p, "failing": []}], {}, now) == []


def test_catalog_files_are_read_safely_and_later_rules_never_move_a_level():
    # catalog-info.yaml comes from every repo in the org: safe YAML only, a size cap, problems listed instead of failing.
    from stackvitals.portal import descriptor
    from stackvitals.portal.scorecard import evaluate, load_rules
    assert descriptor.parse("kind: !!python/object/apply:os.system ['echo hi']\n")[0] == []
    assert descriptor.parse("a: b\n" * 60000)[1] == ["catalog-info.yaml is over 256 KB; not read"]
    # Real files (grafana, backstage, runme): owners as group:default/x, namespace/x and user:ns/x match CODEOWNERS by name.
    assert descriptor.owner_check("group:default/k6-core", ["@grafana/k6-core"])[0] == "pass"
    assert descriptor.owner_check("user:runmedev/sourishkrout", ["@sourishkrout"])[0] == "pass"
    rules, _ = load_rules('[[rule]]\nid = "readme"\ncheck = "files"\nfiles = ["readme"]\nlevel = "bronze"\n\n'
                          '[[rule]]\nid = "runbook"\ncheck = "file"\npath = "docs/runbook.md"\nlevel = "bronze"\nfrom = 2027-01-01\n')
    repo = {"name": "acme/web", "docs": {"readme": True}, "files": {"docs/runbook.md": {"present": False}}}
    out = evaluate(repo, rules, [], NOW, None)
    assert out["level"] == "bronze" and out["results"][1]["result"] == "preview"


def test_a_golden_path_never_writes_to_a_repo_the_requester_cannot_write_to():
    # Phase 17 review: write access to the portal repo isn't write access to every repo in the org.
    import pytest
    from stackvitals.portal.golden import GoldenError, load_paths, run

    class Api:
        def __init__(self):
            self.writes = []

        def _get(self, path, params=None):
            if "/collaborators/" in path:
                return {"permission": "read"}
            if "/git/trees/" in path:
                return {"tree": [{"path": "golden/ci/ci.yml", "type": "blob"}]}
            raise AssertionError(path)

        def send(self, method, path, body=None):
            self.writes.append(path)
            return {}

        def file(self, path, ref=None, repo=None):
            return b"x"
    app = Api()
    paths = load_paths('[[golden_path]]\nid = "ci"\nkind = "files"\nfolder = "golden/ci"\n')
    with pytest.raises(GoldenError, match="can't write"):
        run(app, Api(), "acme/portal", "acme", paths["ci"], {"repo": "acme/web"}, "mallory")
    assert app.writes == []
