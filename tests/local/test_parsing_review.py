"""Fixes from the Phase 12 review of untrusted file parsing: each test is one verified finding."""
import time

from stackvitals.ci import coverage


def test_a_flood_of_doctypes_is_read_in_linear_time():
    # Review finding: the DOCTYPE pattern rescanned to the end of the file from every unclosed "<!DOCTYPE" (200 KB: 27 s).
    data = b"<coverage>" + b"<!DOCTYPE" * 40000
    start = time.perf_counter()
    assert coverage.parse("coverage.xml", data) is None
    assert time.perf_counter() - start < 1.0
    jacoco = (b'<?xml version="1.0"?><!DOCTYPE report PUBLIC "-//JACOCO//DTD Report 1.1//EN" "report.dtd">'
              b'<report name="r"><package name="p"><sourcefile name="A.java"><line nr="3" mi="0" ci="2"/></sourcefile>'
              b'</package></report>')
    assert coverage.parse("jacoco.xml", jacoco)["files"] == {"p/A.java": {3: 2}}


def test_numbers_that_are_not_finite_never_crash_a_report():
    # Review finding: hits="inf" or DA:1,1e999 raised OverflowError out of the parser.
    cob = b'<coverage><packages><package><classes><class filename="a.py"><lines><line number="1" hits="inf"/>' \
          b'<line number="2" hits="nan"/><line number="3" hits="1"/></lines></class></classes></package></packages></coverage>'
    assert coverage.parse("coverage.xml", cob)["files"] == {"a.py": {1: 0, 2: 0, 3: 1}}
    assert coverage.parse("lcov.info", b"SF:a.py\nDA:1,1e999\nDA:2,3\nend_of_record\n")["files"] == {"a.py": {1: 0, 2: 3}}


def test_a_report_with_a_byte_order_mark_is_still_read():
    assert coverage.parse("lcov.info", b"\xef\xbb\xbfSF:a.py\nDA:1,1\nend_of_record\n")["files"] == {"a.py": {1: 1}}


def test_patch_coverage_picks_the_right_file_and_the_right_lines():
    # Review finding: the deepest same-named file won (a root main.go scored 0%), and a form feed shifted added lines.
    report = {"files": {"main.go": {1: 1, 2: 1}, "cmd/tool/main.go": {1: 0, 2: 0}}}
    diff = [{"filename": "main.go", "patch": "@@ -0,0 +1,2 @@\n+a\n+b"}]
    assert coverage.patch(report, diff)["covered"] == 2
    form_feed = [{"filename": "main.go", "patch": "@@ -1,2 +1,3 @@\n x\f y\n+a\n+b"}]
    assert coverage.added_lines(form_feed[0]["patch"]) == [2, 3]


def test_a_deeper_relative_path_is_another_file_while_runner_paths_still_match():
    diff = [{"filename": "main.go", "patch": "@@ -0,0 +1,1 @@\n+a"}]
    assert coverage.patch({"files": {"cmd/tool/main.go": {1: 0}}}, diff)["lines"] == 0
    assert coverage.patch({"files": {"/home/runner/work/r/r/main.go": {1: 1}}}, diff)["covered"] == 1
    assert coverage.patch({"files": {r"D:\a\r\r\main.go": {1: 1}}}, diff)["covered"] == 1


def _zip(name, data, method=None):
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(name, data)
    return buf.getvalue()


def test_hostile_numbers_and_types_in_test_reports_never_crash_the_parser():
    # Review finding: time="1e306", CTRF duration 1e999 or NaN, retries "x" and a dict message escaped the parser.
    from stackvitals.ci.testreports import parse_archive
    junit = b'<testsuite><testcase classname="t" name="a" time="1e306"/><testcase classname="t" name="b" time="nan"/></testsuite>'
    out = parse_archive(_zip("junit.xml", junit))
    assert out["total"] == 2 and all(ms == 0 for _t, ms in out["all"])
    ctrf = (b'{"results": {"tests": [{"name": "a", "status": "failed", "duration": 1e999, "message": {"x": 1}},'
            b'{"name": "b", "status": "passed", "retries": "x", "duration": NaN}, {"name": 5, "status": ["odd"]}]}}')
    out = parse_archive(_zip("ctrf-report.json", ctrf))
    assert out["total"] == 3 and len(out["failed"]) == 1 and out["flaky"] == []


def test_an_artifact_that_cannot_be_read_is_recorded_once_and_never_stops_the_run(monkeypatch):
    # Review finding: a corrupt deflate stream raised zlib.error out of collect(), on every run.
    import zlib

    import pytest

    from stackvitals.ci import collect
    from stackvitals.ci.api import APIError

    class Api:
        def artifacts(self, run_id):
            return [{"id": 7, "name": "junit-results", "size_in_bytes": 10}]

        def download(self, art_id):
            return b"PK..."

    def broken(data):
        raise zlib.error("Error -3 while decompressing data")
    monkeypatch.setattr(collect, "parse_archive", broken)
    recs = collect._reports(Api(), {"id": 1}, {}, collect.TEST_ARTIFACTS, 10_000, set())
    assert [(r["art"], r["unreadable"], r["total"]) for r in recs] == [(7, True, 0)]

    class Offline(Api):
        def download(self, art_id):
            raise APIError("GET /artifacts/7/zip: HTTP 502")
    with pytest.raises(APIError):  # a network error is retried on the next run, not written off
        collect._reports(Offline(), {"id": 1}, {}, collect.TEST_ARTIFACTS, 10_000, set())


def test_a_hostile_catalog_file_is_a_problem_on_its_page_never_a_crash():
    # Review finding: deep nesting (RecursionError), impossible dates and huge ints escaped, and an alias bomb was
    # expanded by str() (442 bytes: 8 s and 624 MB).
    from stackvitals.portal import descriptor
    deep = "kind: Component\nmetadata: {name: x}\nspec: {dependsOn: " + "[" * 5000 + "]" * 5000 + "}\n"
    assert descriptor.parse(deep)[0] == [] and descriptor.parse(deep)[1][0].startswith("not valid YAML")
    assert descriptor.parse("kind: Component\nmetadata: {name: x, created: 2026-02-30}\n")[0] == []
    huge = "kind: Component\nmetadata: {name: " + "9" * 5000 + "}\nspec: {owner: " + "0x" + "f" * 5000 + "}\n"
    entities, problems = descriptor.parse(huge)
    assert problems and all(len(str(e.get("name") or "")) < 300 for e in entities)
    bomb = "a: &a [x,x,x,x,x,x,x,x,x]\n" + "".join(f"{c}: &{c} [{','.join('*' + chr(ord(c) - 1) for _ in range(9))}]\n"
                                                  for c in "bcdefgh") + "kind: *h\n"
    start = time.perf_counter()
    assert descriptor.parse(bomb)[1] == ["document 1: no kind is not a Backstage kind"]
    assert time.perf_counter() - start < 1.0


def test_portal_toml_mistakes_fall_back_to_the_default_rules_with_a_note():
    # Review finding: check = ["file"] or fields = [{a = 1}] raised TypeError past rules_or_default.
    from stackvitals.portal.scorecard import rules_or_default
    for text in ('[[rule]]\nid = "x"\ncheck = ["file"]\nlevel = "bronze"\n',
                 '[[rule]]\nid = "x"\ncheck = "catalog"\nfields = [{a = 1}]\nlevel = "bronze"\n',
                 '[[rule]]\nid = "x"\ncheck = "file"\npath = "README.md"\ncontains = "^## (\\\\w+\\\\s?)+$"\nlevel = "bronze"\n'):
        rules, _ex, notes = rules_or_default(text)
        assert notes and "default rules were used" in notes[0] and rules[0]["id"] == "codeowners"


def test_one_repo_that_cannot_be_checked_never_stops_the_org_catalog(monkeypatch):
    # Review finding: anything but OutOfBudget in one repo's checks escaped build_catalog and failed every run.
    import sys
    sys.path.insert(0, "tests/local")
    from test_portal_catalog import NOW, org_routes
    from test_portal_m1 import fake

    from stackvitals.portal import catalog
    real = catalog.descriptor_for

    def odd(api, repo, pre=None):
        if repo["name"] == "acme/web":
            raise RuntimeError("unexpected")
        return real(api, repo, pre)
    monkeypatch.setattr(catalog, "descriptor_for", odd)
    c = catalog.build_catalog(fake(org_routes(("api", "web")))("t", "acme/portal"), "acme", "public", NOW)
    by = {r["name"]: r for r in c["repos"]}
    assert by["acme/api"]["checked"] and by["acme/web"]["error"] == "RuntimeError" and not by["acme/web"].get("checked")


def _deps_dev_client(calls, projects=None):
    import httpx

    def handle(request):
        calls.append(request.url.host)
        if request.url.host == "api.deps.dev":
            name = request.url.path.split("/packages/")[1].split("/versions/")[0]
            project = (projects or {}).get(name, f"github.com/o/{name}")
            return httpx.Response(200, json={"licenses": ["MIT"], "relatedProjects": [
                {"projectKey": {"id": project}, "relationType": "SOURCE_REPO"}]})
        if request.url.host == "api.scorecard.dev":
            return httpx.Response(404)
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handle))


def test_a_large_sbom_stays_within_the_lookup_and_score_limits(tmp_path):
    # Review finding: the Scorecard pass looked up every package on deps.dev (1,000 packages: 1,000 calls in one run).
    from datetime import datetime, timezone

    from stackvitals.deps import supply
    now = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
    packages = [{"purl": f"pkg:npm/p{i}@1.0", "name": f"p{i}", "version": "1.0", "system": "NPM", "licences": []}
                for i in range(1000)]
    calls = []
    client = _deps_dev_client(calls)
    cache = supply.LicenceCache(tmp_path)
    supply.licences(packages, client, cache)
    supply.scorecards(packages, client, supply.SupplyStore(tmp_path), now, cache, lookups=0)
    assert calls.count("api.deps.dev") == supply.LOOKUPS and calls.count("api.scorecard.dev") == supply.SCORES


def test_scorecard_asks_rotate_through_every_project_instead_of_repeating_the_first_forty(tmp_path):
    # Review finding: 404s and same-date answers were never remembered, so every run asked the same 40 projects.
    from datetime import datetime, timedelta, timezone

    from stackvitals.deps import supply
    now = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
    packages = [{"purl": f"pkg:githubactions/o/a{i:03}@1", "name": f"o/a{i:03}", "version": "1", "system": supply.ACTIONS,
                 "licences": []} for i in range(100)]
    store = supply.SupplyStore(tmp_path)
    first, second = [], []
    supply.scorecards(packages, _deps_dev_client(first), store, now, None)
    store.save()
    store = supply.SupplyStore(tmp_path)
    supply.scorecards(packages, _deps_dev_client(second), store, now + timedelta(days=1), None)
    assert len(first) == len(second) == supply.SCORES
    asked = lambda calls: calls  # noqa: E731
    assert asked(first) and store.asked and len(store.asked) == 2 * supply.SCORES


def test_a_package_at_two_versions_is_not_licence_drift(tmp_path):
    # Review finding: the old quarter kept one version's licence and compared every new row to it.
    from datetime import datetime, timezone

    from stackvitals.deps import supply
    store = supply.SupplyStore(tmp_path)
    rows = [{"purl": "pkg:npm/a@1.0", "name": "a", "system": "NPM", "version": "1.0", "licences": ["MIT"]},
            {"purl": "pkg:npm/a@2.0", "name": "a", "system": "NPM", "version": "2.0", "licences": ["Apache-2.0"]}]
    store.snapshot(rows, datetime(2026, 6, 1, tzinfo=timezone.utc))
    store.snapshot(rows, datetime(2026, 10, 1, tzinfo=timezone.utc))
    assert supply.drift(store, datetime(2026, 10, 21, tzinfo=timezone.utc)) == []
    store.snapshot([*rows[:1], {**rows[1], "version": "10.0", "licences": ["BUSL-1.1"]}], datetime(2026, 10, 1, tzinfo=timezone.utc))
    assert [(d["from"], d["to"]) for d in supply.drift(store, datetime(2026, 10, 21, tzinfo=timezone.utc))] == [("Apache-2.0", "BUSL-1.1")]


def test_licence_rules_read_parentheses_and_several_licences():
    # Review finding: "GPL-3.0-only AND (MIT OR Apache-2.0)" and ["GPL-3.0-only", "MIT OR Apache-2.0"] passed GPL-*.
    from stackvitals.deps import supply
    pkg = lambda ls: [{"purl": "p", "name": "x", "version": "1", "system": "NPM", "licences": ls}]  # noqa: E731
    assert supply.policy(pkg(["GPL-3.0-only AND (MIT OR Apache-2.0)"]), ["GPL-*"])["denied"]
    assert supply.policy(pkg(["GPL-3.0-only", "MIT OR Apache-2.0"]), ["GPL-*"])["denied"]
    assert not supply.policy(pkg(["(GPL-3.0-only OR MIT) AND Apache-2.0"]), ["GPL-*"])["denied"]
    assert not supply.policy(pkg(["GPL-2.0-only WITH Classpath-exception-2.0 OR MIT"]), ["GPL-*"])["denied"]
    assert supply.policy(pkg(["GPL-2.0-only WITH Classpath-exception-2.0"]), ["GPL-*"])["denied"]


def test_shards_read_only_push_runs_and_never_pass_on_option_like_test_ids():
    # Review finding: a fork PR from someone:main counted as the default branch, and an id like "tests/ --co::t" put
    # "--co" into every shard's pytest command.
    from stackvitals.ci import shards
    asked = {}

    class Api:
        repo = "o/r"

        def _get(self, path, params=None):
            asked.update(params or {})
            return {"workflow_runs": []}
    shards.latest_times(Api(), "main")
    assert asked.get("event") == "push" and asked.get("branch") == "main"
    out = shards.split([["tests/test_a.py::t", 10], ["tests/ --co::t", 99999], ["-x::t", 5], ["tests/b.py::t", 20]], 2)
    assert sorted(f for s in out for f in s["files"]) == ["tests/b.py", "tests/test_a.py"]


def test_skips_and_coverage_on_the_default_branch_ignore_runs_from_pull_requests():
    # Review finding: a fork PR from contributor:main (pull_request_target or issue_comment) replaced the skip list and
    # set the latest coverage.
    from datetime import datetime, timezone

    from stackvitals.ci.analyze import _coverage, _inventory
    now = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
    runs = {(1, 1): {"id": 1, "att": 1, "cr": "2026-10-20T10:00:00Z", "br": "main", "ev": "push"},
            (2, 1): {"id": 2, "att": 1, "cr": "2026-10-21T10:00:00Z", "br": "main", "ev": "pull_request_target"}}
    data = {"tests": [{"run": 1, "att": 1, "name": "junit", "sk": ["a"], "failed": [], "cov": {"lines": 100, "covered": 80}},
                      {"run": 2, "att": 1, "name": "junit", "sk": ["b"], "failed": [], "cov": {"lines": 100, "covered": 50}}]}
    _new, skipped = _inventory(data, runs, {1: 1, 2: 1}, now, "main", [])
    assert [s["id"] for s in skipped] == ["a"]
    cov = _coverage(data, runs, now, datetime(2026, 10, 1, tzinfo=timezone.utc), "main")
    assert cov["latest"]["pct"] == 0.8 and cov["latest"]["run"] == 1


def test_a_coverage_matrix_reads_the_pull_request_and_its_files_once(monkeypatch):
    # Review finding: every coverage artifact looked the PR up and read its files again (10 jobs: 10x the requests).
    from stackvitals.ci import collect
    calls = []

    class Api:
        def artifacts(self, run_id):
            return [{"id": i, "name": f"coverage-{i}", "size_in_bytes": 10} for i in range(5)]

        def download(self, art_id):
            return b"zip"
    monkeypatch.setattr(collect, "parse_archive", lambda data: {"total": 0, "failed": [], "flaky": [], "skipped": 0,
                                                                "cov": {"format": "lcov", "lines": 1, "covered": 1,
                                                                        "files": {"a.py": {1: 1}}}})
    monkeypatch.setattr(collect, "_pr_number", lambda api, run: calls.append("number") or 7)
    monkeypatch.setattr(collect, "_pr_files", lambda api, n: calls.append("files") or [{"filename": "a.py", "patch": "@@ -0,0 +1 @@\n+x"}])
    recs = collect._reports(Api(), {"id": 1, "ev": "pull_request"}, {}, collect.TEST_ARTIFACTS, 10_000, set())
    assert len(recs) == 5 and all(r["patch"]["pr"] == 7 for r in recs) and calls == ["number", "files"]


def test_one_huge_report_is_capped_before_it_reaches_the_data_branch():
    # Review finding: one 9.4 MB report stored a 10.8 MB record (unbounded failures, ids of any length).
    from stackvitals.ci import testreports
    cases = "".join(f'<testcase classname="c" name="{"x" * 2000}{i}"><failure message="m"/></testcase>' for i in range(3000))
    out = testreports.parse_archive(_zip("junit.xml", f"<testsuite>{cases}</testsuite>".encode()))
    assert out["total"] == 3000 and len(out["failed"]) == testreports.MAX_ROWS
    assert max(len(f[0]) for f in out["failed"]) <= testreports.MAX_ID and len(out["all"]) <= testreports.MAX_ALL


def test_the_known_test_list_stops_at_its_cap_and_learns_only_from_the_repos_own_runs():
    # Review finding: one 1.5 MB report of fake ids from a fork filled the 50k list, and then nothing was ever new.
    from stackvitals.ci import collect
    seen = set(f"t{i}" for i in range(collect.KNOWN_MAX - 10))
    rec = {}
    collect._learn(rec, [f"new{i}" for i in range(100)], seen, known=True, own=True)
    assert len(seen) == collect.KNOWN_MAX and rec["new"] == [f"new{i}" for i in range(collect.NEW_KEEP)]
    fork = {}
    collect._learn(fork, ["evil1", "evil2"], set(), known=True, own=False)
    assert "new" not in fork
