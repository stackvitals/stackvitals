"""Supply chain: the repo's SBOM from GitHub's async report (the sync endpoint closes 13 Nov 2026), each package's licence
from deps.dev, a licence policy with decisions, licence drift between quarterly snapshots, and OpenSSF Scorecard drops for
the projects behind the packages."""
import json
from datetime import datetime, timezone

import httpx
import pytest

from stackvitals.deps import supply

NOW = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
SPDX = {"spdxVersion": "SPDX-2.3", "packages": [
    {"name": "com.github.o/r", "SPDXID": "SPDXRef-Repository", "versionInfo": "main", "licenseDeclared": "MIT"},
    {"name": "npm:left-pad", "SPDXID": "SPDXRef-npm-left-pad-1.3.0", "versionInfo": "1.3.0", "licenseConcluded": "NOASSERTION",
     "externalRefs": [{"referenceCategory": "PACKAGE-MANAGER", "referenceType": "purl", "referenceLocator": "pkg:npm/left-pad@1.3.0"}]},
    {"name": "pypi:gpl-thing", "SPDXID": "SPDXRef-pip-gpl-thing-2.0", "versionInfo": "2.0",
     "externalRefs": [{"referenceCategory": "PACKAGE-MANAGER", "referenceType": "purl", "referenceLocator": "pkg:pypi/gpl-thing@2.0"}]},
    {"name": "npm:@scope/ui", "SPDXID": "SPDXRef-npm-scope-ui-4.1.0", "versionInfo": "4.1.0",
     "externalRefs": [{"referenceCategory": "PACKAGE-MANAGER", "referenceType": "purl", "referenceLocator": "pkg:npm/%40scope/ui@4.1.0"}]}],
    "relationships": [{"relationshipType": "DESCRIBES", "spdxElementId": "SPDXRef-DOCUMENT", "relatedSpdxElement": "SPDXRef-Repository"}]}


class FakeAPI:
    repo = "o/r"

    def __init__(self, pending=1):
        self.pending, self.calls, self.slept = pending, [], []

    def sleep(self, s):
        self.slept.append(s)

    def _get(self, path, params=None, raw=False):
        self.calls.append(path)
        assert path.endswith("/dependency-graph/sbom/generate-report")
        return {"sbom_url": "https://api.github.com/repos/o/r/dependency-graph/sbom/fetch-report/u1"}

    def fetch(self, path):
        # Real-data finding: while the report is being made GitHub answers 202 with a "{}" body, not an empty one.
        self.calls.append(path)
        assert path == "/repos/o/r/dependency-graph/sbom/fetch-report/u1"
        if self.pending:
            self.pending -= 1
            return 202, b"{}"
        return 200, json.dumps(SPDX).encode()


def test_the_sbom_comes_from_the_async_report_once_it_is_ready():
    api = FakeAPI(pending=2)
    packages = supply.sbom(api)
    assert [p["purl"] for p in packages] == ["pkg:npm/left-pad@1.3.0", "pkg:pypi/gpl-thing@2.0", "pkg:npm/%40scope/ui@4.1.0"]
    assert packages[2]["system"] == "NPM" and packages[2]["name"] == "@scope/ui" and packages[2]["version"] == "4.1.0"
    assert packages[0]["licences"] == [] and len(api.slept) == 2
    with pytest.raises(supply.SupplyError):
        supply.sbom(FakeAPI(pending=99), polls=3)


def deps_dev(licences, projects=None, seen=None):
    def handle(request):
        (seen if seen is not None else []).append(str(request.url))
        if request.url.host == "api.deps.dev":
            name = request.url.path.split("/packages/")[1].split("/versions/")[0]
            from urllib.parse import unquote
            name = unquote(name)
            if name not in licences:
                return httpx.Response(404, json={"error": "not found"})
            return httpx.Response(200, json={"licenses": licences[name], "relatedProjects": [
                {"projectKey": {"id": (projects or {}).get(name, "")}, "relationType": "SOURCE_REPO"}] if (projects or {}).get(name) else []})
        if request.url.host == "api.scorecard.dev":
            return httpx.Response(200, json={"score": 3.1, "date": "2026-10-19", "repo": {"name": "github.com/x/y"}})
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handle))


def test_licences_come_from_deps_dev_and_are_cached_since_a_version_never_changes(tmp_path):
    seen = []
    packages = supply.parse_spdx(SPDX)
    client = deps_dev({"left-pad": ["WTFPL"], "gpl-thing": ["GPL-3.0-only"], "@scope/ui": ["MIT"]}, seen=seen)
    cache = supply.LicenceCache(tmp_path)
    got = supply.licences(packages, client, cache)
    assert got["pkg:npm/left-pad@1.3.0"] == ["WTFPL"] and got["pkg:pypi/gpl-thing@2.0"] == ["GPL-3.0-only"]
    assert any("%40scope%2Fui" in u for u in seen)
    cache.save()
    again = []
    supply.licences(packages, deps_dev({}, seen=again), supply.LicenceCache(tmp_path))
    assert again == []


def test_the_policy_names_denied_licences_unless_a_decision_accepted_them():
    pkgs = [{"purl": "pkg:pypi/gpl-thing@2.0", "name": "gpl-thing", "version": "2.0", "system": "PYPI", "licences": ["GPL-3.0-only"]},
            {"purl": "pkg:npm/left-pad@1.3.0", "name": "left-pad", "version": "1.3.0", "system": "NPM", "licences": ["WTFPL"]},
            {"purl": "pkg:npm/agpl@1.0", "name": "agpl", "version": "1.0", "system": "NPM", "licences": ["AGPL-3.0-or-later"]},
            {"purl": "pkg:npm/dual@1.0", "name": "dual", "version": "1.0", "system": "NPM", "licences": ["GPL-3.0-only OR MIT"]},
            {"purl": "pkg:npm/both@1.0", "name": "both", "version": "1.0", "system": "NPM", "licences": ["MIT AND GPL-3.0-only"]},
            {"purl": "pkg:npm/mystery@1.0", "name": "mystery", "version": "1.0", "system": "NPM", "licences": []}]
    out = supply.policy(pkgs, ["GPL-3.0*", "AGPL-*"], accepted={"agpl"})
    # A choice of licences ("A OR B") is fine when one choice is allowed; "A AND B" needs every part allowed.
    assert [(x["name"], x["licence"]) for x in out["denied"]] == [("gpl-thing", "GPL-3.0-only"), ("both", "MIT AND GPL-3.0-only")]
    assert [x["name"] for x in out["accepted"]] == ["agpl"] and out["unknown"] == 1 and out["by_licence"]["WTFPL"] == 1


def test_licence_drift_compares_the_same_package_across_quarterly_snapshots(tmp_path):
    store = supply.SupplyStore(tmp_path)
    store.snapshot([{"purl": "pkg:npm/a@1.0", "name": "a", "system": "NPM", "version": "1.0", "licences": ["MIT"]}],
                   datetime(2026, 6, 1, tzinfo=timezone.utc))
    now = [{"purl": "pkg:npm/a@2.0", "name": "a", "system": "NPM", "version": "2.0", "licences": ["BUSL-1.1"]},
           {"purl": "pkg:npm/b@1.0", "name": "b", "system": "NPM", "version": "1.0", "licences": ["MIT"]}]
    store.snapshot(now, NOW)
    drift = supply.drift(store, NOW)
    assert drift == [{"name": "a", "system": "NPM", "from": "MIT", "to": "BUSL-1.1", "from_quarter": "2026-Q2", "to_quarter": "2026-Q4"}]


def test_scorecard_drops_are_found_by_keeping_each_projects_score_history(tmp_path):
    store = supply.SupplyStore(tmp_path)
    store.scores = {"github.com/x/y": [["2026-09-01", 6.4]]}
    pkgs = [{"purl": "pkg:npm/left-pad@1.3.0", "name": "left-pad", "version": "1.3.0", "system": "NPM", "licences": []}]
    client = deps_dev({"left-pad": ["WTFPL"]}, projects={"left-pad": "github.com/x/y"})
    out = supply.scorecards(pkgs, client, store, NOW)
    assert out["drops"] == [{"project": "github.com/x/y", "before": 6.4, "after": 3.1, "since": "2026-09-01", "packages": ["left-pad"]}]
    assert out["low"][0]["project"] == "github.com/x/y" and store.scores["github.com/x/y"][-1] == ["2026-10-19", 3.1]


def test_packages_with_no_known_source_project_are_skipped_for_scorecards(tmp_path):
    pkgs = [{"purl": "pkg:npm/left-pad@1.3.0", "name": "left-pad", "version": "1.3.0", "system": "NPM", "licences": []},
            {"purl": "pkg:githubactions/actions/checkout@4", "name": "actions/checkout", "version": "4", "system": None, "licences": []}]
    out = supply.scorecards(pkgs, deps_dev({"left-pad": ["WTFPL"]}), supply.SupplyStore(tmp_path), NOW)
    assert out == {"checked": 0, "projects": 0, "drops": [], "low": [], "names": {}}


class Ws:
    def __init__(self, path, settings):
        self.path, self.cache, self.notes, self.repo = path, {"settings": settings}, [], "o/r"


def test_the_weekly_step_publishes_the_supply_chain_and_waits_a_week_on_the_schedule(tmp_path):
    from stackvitals.core.config import parse
    cfg, notes = parse('[deps.licenses]\ndeny = ["GPL-3.0*"]\n')
    assert notes == [] and cfg["deps"]["licenses"]["deny"] == ["GPL-3.0*"]
    ws = Ws(tmp_path, cfg)
    client = deps_dev({"left-pad": ["WTFPL"], "gpl-thing": ["GPL-3.0-only"], "@scope/ui": ["MIT"]})
    env = {"GITHUB_EVENT_NAME": "schedule", "STACKVITALS_TOKEN": "t"}
    out = supply.supply_step(ws, env, NOW, make_api=lambda tok, repo, **kw: FakeAPI(pending=0), client=client)
    assert out["packages"] == 3 and out["denied"] == 1
    page = json.loads((tmp_path / "docs" / "supply.json").read_text(encoding="utf-8"))
    assert page["licences"]["denied"][0]["name"] == "gpl-thing" and page["systems"] == {"NPM": 2, "PYPI": 1}
    assert page["policy"]["deny"] == ["GPL-3.0*"]
    # The schedule reads it once a week; a manual run reads it now.
    assert supply.supply_step(ws, env, NOW, make_api=lambda tok, repo, **kw: FakeAPI(pending=0), client=client) is None
    again = supply.supply_step(ws, {**env, "GITHUB_EVENT_NAME": "workflow_dispatch"}, NOW,
                               make_api=lambda tok, repo, **kw: FakeAPI(pending=0), client=client)
    assert again["packages"] == 3


def test_a_dependency_graph_that_is_off_is_said_plainly_and_does_not_fail_the_job(tmp_path):
    from stackvitals.core.config import parse

    class Off(FakeAPI):
        def fetch(self, path):
            raise AssertionError("never asked")

        def _get(self, path, params=None, raw=False):
            from stackvitals.ci.api import APIError
            raise APIError(f"GET /repos/acme/app/dependency-graph/sbom/generate-report: HTTP 404 "
                           '{"message":"Not Found","documentation_url":"https://docs.github.com/rest","status":"404"}')
    ws = Ws(tmp_path, parse("")[0])
    out = supply.supply_step(ws, {"GITHUB_EVENT_NAME": "schedule"}, NOW, make_api=lambda tok, repo, **kw: Off(), client=deps_dev({}))
    # Sandbox finding: a long repo name cut the old note before the status, so the reason never showed.
    assert out["error"] and "dependency graph" in ws.notes[0] and "HTTP 404" in ws.notes[0]


def test_agents_read_the_published_supply_chain():
    from stackvitals.core import services

    class Api:
        def __init__(self, tok, repo, max_requests=None):
            self.repo = repo

        def file(self, path, ref):
            assert path == "docs/supply.json" and ref == "stackvitals-data"
            return json.dumps({"schema": 1, "packages": 3, "licences": {"denied": [{"name": "gpl-thing"}]}}).encode()
    found, source = services.supply("o/r", "t", make_api=Api)
    assert found["packages"] == 3 and source == "stackvitals-data branch"

    class Missing(Api):
        def file(self, path, ref):
            from stackvitals.ci.api import APIError
            raise APIError("GET: HTTP 404")
    assert services.supply("o/r", "t", make_api=Missing)[0] is None


# Real data (the sandbox's SBOM, 2026-10-21): the repo itself has a pkg:github purl and is what the document DESCRIBES;
# workflow actions come as pkg:githubactions with a version range.
REAL = {"packages": [
    {"name": "actions/checkout", "SPDXID": "SPDXRef-githubactions-actions-checkout-4..-bfd09a", "versionInfo": "4.*.*",
     "externalRefs": [{"referenceCategory": "PACKAGE-MANAGER", "referenceType": "purl",
                       "referenceLocator": "pkg:githubactions/actions/checkout@4.%2A.%2A"}]},
    {"name": "github/codeql-action/analyze", "SPDXID": "SPDXRef-githubactions-github-codeql-action-analyze-3", "versionInfo": "3",
     "externalRefs": [{"referenceCategory": "PACKAGE-MANAGER", "referenceType": "purl",
                       "referenceLocator": "pkg:githubactions/github/codeql-action/analyze@3"}]},
    {"name": "com.github.o/r", "SPDXID": "SPDXRef-github-o-r-main-64fb39", "versionInfo": "main",
     "externalRefs": [{"referenceCategory": "PACKAGE-MANAGER", "referenceType": "purl", "referenceLocator": "pkg:github/o/r@main"}]}],
    "relationships": [{"relationshipType": "DESCRIBES", "spdxElementId": "SPDXRef-DOCUMENT",
                       "relatedSpdxElement": "SPDXRef-github-o-r-main-64fb39"}]}


def test_workflow_actions_are_packages_with_scorecards_and_the_repo_itself_is_not(tmp_path):
    packages = supply.parse_spdx(REAL)
    assert [(p["system"], p["name"], p["version"]) for p in packages] == \
        [("ACTIONS", "actions/checkout", "4.*.*"), ("ACTIONS", "github/codeql-action/analyze", "3")]
    seen = []
    client = deps_dev({}, seen=seen)
    cache = supply.LicenceCache(tmp_path)
    # deps.dev doesn't know actions: no lookups, licences unknown.
    assert supply.licences(packages, client, cache) == {p["purl"]: [] for p in packages} and seen == []
    out = supply.scorecards(packages, client, supply.SupplyStore(tmp_path), NOW, cache)
    # The project behind an action is its repo (a subfolder action belongs to the repo), so Scorecard covers it.
    assert out["projects"] == 2 and out["checked"] == 2
    assert sorted(u.split("/projects/")[1] for u in seen) == ["github.com/actions/checkout", "github.com/github/codeql-action"]
    # Actions run in CI and never ship: the licence rule leaves them out rather than counting them as unknown.
    assert supply.policy(packages, ["GPL-*"]) == {"denied": [], "accepted": [], "unknown": 0, "by_licence": {}}


def test_a_refused_sbom_is_asked_again_weekly_not_on_every_run(tmp_path):
    # Fresh-install finding: the dependency graph is off by default on private repos, and every 3-hourly run asked again
    # and put the same warning on the run.
    from datetime import timedelta

    from stackvitals.core.config import parse
    asked = []

    class Off(FakeAPI):
        def _get(self, path, params=None, raw=False):
            from stackvitals.ci.api import APIError
            asked.append(path)
            raise APIError(f"GET {path}: HTTP 404 Not Found")
    ws = Ws(tmp_path, parse("")[0])
    run = lambda event, when: supply.supply_step(ws, {"GITHUB_EVENT_NAME": event}, when,  # noqa: E731
                                                  make_api=lambda tok, repo, **kw: Off(), client=deps_dev({}))
    assert run("schedule", NOW)["error"] and len(asked) == 1 and "next week" in ws.notes[0]
    assert run("schedule", NOW + timedelta(hours=3)) is None and len(asked) == 1
    assert run("workflow_dispatch", NOW + timedelta(hours=4))["error"] and len(asked) == 2  # a manual run asks now
    assert run("schedule", NOW + timedelta(days=7))["error"] and len(asked) == 3


def test_a_report_that_was_only_slow_is_asked_again_on_the_next_run(tmp_path):
    from datetime import timedelta

    from stackvitals.core.config import parse
    ws = Ws(tmp_path, parse("")[0])
    slow = lambda: supply.supply_step(ws, {"GITHUB_EVENT_NAME": "schedule"}, NOW + timedelta(hours=len(ws.notes) * 3),  # noqa: E731
                                      make_api=lambda tok, repo, **kw: FakeAPI(pending=99), client=deps_dev({}))
    assert "wasn't ready" in slow()["error"] and "wasn't ready" in slow()["error"]  # not put off for a week


def test_with_outside_lookups_off_no_dependency_name_leaves_the_repo(tmp_path):
    from stackvitals.core.config import parse
    from stackvitals.deps.lookalike import judge
    cfg, notes = parse("[deps]\noutside_lookups = false\n")
    assert notes == [] and cfg["deps"]["outside_lookups"] is False
    sent = []
    client = httpx.Client(transport=httpx.MockTransport(lambda r: sent.append(str(r.url)) or httpx.Response(500)))
    out = supply.supply_step(Ws(tmp_path, cfg), {"GITHUB_EVENT_NAME": "schedule"}, NOW,
                             make_api=lambda tok, repo, **kw: FakeAPI(pending=0), client=client)
    page = json.loads((tmp_path / "docs" / "supply.json").read_text(encoding="utf-8"))
    assert sent == [] and out["packages"] == 3 and page["outside_lookups"] is False
    assert judge("npm", "lodahs", {"npm": {"lodash"}}, None)["verdict"] == "monitor"
