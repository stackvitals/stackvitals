"""Dependency evidence: upgrade PRs read from titles, the upgrade ledger, the package map and vulnerability history.
One guard per real-data finding; task tests live in tests/local."""
import http.client
from datetime import datetime, timedelta, timezone

import duckdb

from mergescout.signals.bump_ledger import build_bump_ledger, build_bump_prs, parse_branch
from mergescout.signals.bumps import parse_bump
from mergescout.signals.deps_map import check_claims, lookup_packages
from mergescout.signals.osv import refresh_vulns

NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)


def test_real_bot_titles_from_both_bots_are_read():
    # 800 real titles: the first parser understood 87% of Dependabot and 43% of Renovate updates; 398 unseen ones: 100%.
    b = parse_bump("chore(ci)(deps): bump actions/checkout from 4 to 7 in the github-actions group", "dependabot/github_actions/x", "dependabot")
    assert (b["package"], b["bump"], b["grouped"]) == ("actions/checkout", "major", False)
    b = parse_bump("[Security] Bump urllib3 from 1.26.5 to 1.26.18", "dependabot/pip/urllib3-1.26.18", "dependabot[bot]")
    assert b["security"] and b["bump"] == "patch"
    b = parse_bump("build(deps): update dependency uuid from ^14.0.0 to v14.0.3", "renovate/uuid-14.x", "renovate[bot]")
    assert (b["package"], b["bump"]) == ("uuid", "patch")
    assert parse_bump("Configure Renovate", "renovate/configure", "renovate[bot]") is None
    assert parse_branch("dependabot/pip/setuptools-scm-gte-8.0.0") == ("pypi", "setuptools-scm", "8.0.0")
    assert parse_branch("dependabot/npm_and_yarn/frontend/babel/core-7.24.0") is None


def test_the_ledger_skips_superseded_closes_and_counts_reverts():
    day = lambda d: NOW - timedelta(days=d)  # noqa: E731
    con = duckdb.connect()
    con.execute("""CREATE TABLE prs (repo_id BIGINT, number INT, created_at TIMESTAMPTZ, merged_at TIMESTAMPTZ, closed_at TIMESTAMPTZ,
        state VARCHAR, author_login VARCHAR, head_ref VARCHAR, title VARCHAR, ci_state VARCHAR, commit_count INT)""")
    con.execute("CREATE TABLE repo_meta (repo_id BIGINT, language VARCHAR)")
    con.executemany("INSERT INTO prs VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
        [1, 1, day(30), None, day(29), "CLOSED", "dependabot", "dependabot/pip/x-2.0.0", "Bump x from 1.0.0 to 2.0.0", "SUCCESS", 1],
        [1, 2, day(29), day(28), day(28), "MERGED", "dependabot", "dependabot/pip/x-2.0.1", "Bump x from 1.0.0 to 2.0.1", "FAILURE", 3],
        [1, 3, day(25), day(24), day(24), "MERGED", "ann", "revert-2", 'Revert "Bump x from 1.0.0 to 2.0.1"', None, None]])
    build_bump_prs(con)
    build_bump_ledger(con, NOW)
    prs, closed, failed, extra, reverted = con.execute(
        "SELECT prs, closed_unmerged, ci_failed, extra_commits, reverted FROM bump_ledger WHERE package = 'x'").fetchone()
    assert (prs, closed, failed, extra, reverted) == (2, 0, 1, 1, 1)


def test_deps_dev_answers_in_pages_and_a_lost_answer_skips_one_package():
    pkgs = {"requests": "github.com/psf/requests", "flask": "github.com/pallets/flask"}

    def get(url):
        name = url.rsplit("/", 1)[1]
        if name == "boom":
            raise http.client.RemoteDisconnected("closed")
        return {"versions": [{"versionKey": {"version": "1.0"}, "publishedAt": "2026-09-01T00:00:00Z", "isDefault": True}]}

    def post(url, body):
        # Found live: 100 per page with a nextPageToken; the first version read only page one.
        start = int(body.get("pageToken") or 0)
        req = body["requests"][start]
        name = req["versionKey"]["name"]
        page = {"responses": [{"request": req, "version": {"relatedProjects": [{"projectKey": {"id": pkgs[name]},
                "relationProvenance": "UNVERIFIED_METADATA", "relationType": "SOURCE_REPO"}]}}]}
        if start + 1 < len(body["requests"]):
            page["nextPageToken"] = str(start + 1)
        return page
    got = lookup_packages([("pypi", "requests"), ("pypi", "flask"), ("pypi", "boom")], get, post, NOW)
    assert got[("pypi", "flask")]["repo"] == "pallets/flask" and ("pypi", "boom") not in got


def test_a_claimed_repo_counts_only_when_its_manifest_names_the_package():
    class Manifest:
        def query(self, query, variables=None, **kw):
            from mergescout.github.graphql import GraphQLResult
            data = {"r0": {"f0": {"text": '[project]\nname = "requests"\n'}}, "r1": {"f0": {"text": '{"name": "other"}'}}}
            return GraphQLResult(data=data, cost=1, remaining=999, reset_at="x")
    infos = {("pypi", "requests"): {"ecosystem": "pypi", "package": "requests", "repo": "psf/requests", "link": "claimed"},
             ("npm", "left-pad"): {"ecosystem": "npm", "package": "left-pad", "repo": "evil/fork", "link": "claimed"}}
    check_claims(infos, Manifest())
    assert [infos[k]["link"] for k in infos] == ["claimed_checked", "claimed_unconfirmed"]


def test_osv_history_merges_aliases_and_the_cache_survives_timestamp_spelling():
    rec = {"id": "GHSA-1", "aliases": ["PYSEC-1"], "published": "2026-01-01T00:00:00Z", "modified": "2026-01-02T00:00:00.123456789Z",
           "affected": [{"package": {"name": "x", "ecosystem": "PyPI"}, "ranges": [{"events": [{"fixed": "2"}]}]}]}
    alias = {**rec, "id": "PYSEC-1", "aliases": ["GHSA-1"]}

    def post(url, body):
        return {"results": [{"vulns": [{"id": "GHSA-1", "modified": "2026-01-02T00:00:00.123456Z"},
                                       {"id": "PYSEC-1", "modified": "2026-01-02T00:00:00.123456Z"}]}]}
    fetched = []

    def get(url):
        fetched.append(url)
        return rec if url.endswith("GHSA-1") else alias
    first = refresh_vulns([("pypi", "x")], {}, NOW, post, get)
    assert first["packages"]["pypi:x"]["advisories"] == 1
    fetched.clear()
    refresh_vulns([("pypi", "x")], first, NOW, post, get)
    assert fetched == []  # live: the record spells the time with more digits; the first cache refetched everything


def test_dossier_verdicts_follow_hard_signals_and_say_when_evidence_is_thin():
    # Real data: one lead merging made 866 packages "monitor"; 925 thin ones too. Hard signals still investigate.
    from stackvitals.deps.dossier import dossier
    from stackvitals.deps.evidence import index_evidence
    cell = {"ecosystem": "pypi", "package": "lib", "bump": "minor", "prs": 120, "repos": 50, "merged": 100, "closed_unmerged": 8,
            "ci_known": 110, "ci_failed": 9, "expected_failed": 8.0, "extra_commits": 3, "reverted": 0}
    m = {"ecosystem": "pypi", "package": "lib", "version": "2.15.1", "repo": "acme/lib", "link": "verified", "deprecated": False,
         "status": None, "releases_12m": 6, "last_release": "2026-09-01", "first_release": "2015-01-01"}
    trend = {"acme/lib": {"stars": 5000, "direction": {"outside_merge_rate": "steady", "first_response_hours": "steady"},
                          "quarters": [{"outside_merge_rate": 0.6, "first_response_hours": 20, "top_merger_share": 0.95}] * 4,
                          "peers": {"outside_merge_rate": {"place": "merges outside PRs less than most similar repos", "peers": 300}}}}
    osv = {"pypi:lib": {"advisories": 2, "last_2y": 2, "unfixed": 0, "last_affected": ["2.13.0"], "disputed": 1,
                        "latest": "2026-09-30", "severity": {}, "malware": False, "ids": []}}
    ev = index_evidence({"cells": [cell]}, {"packages": {"pypi:lib": m}}, {"repos": trend}, {"packages": osv})
    assert dossier("pypi", "lib", ev, NOW)["verdict"] == "use"  # pyjwt case: newest release is past the bound
    ev["map"]["pypi:lib"] = {**m, "version": "2.13.0"}
    assert dossier("pypi", "lib", ev, NOW)["verdict"] == "investigate"
    thin = index_evidence({"cells": [{**cell, "prs": 5, "repos": 3}]}, {"packages": {"pypi:lib": m}}, {"repos": {}}, {"packages": {}})
    assert dossier("pypi", "lib", thin, NOW)["verdict"] is None


def test_the_dossier_hand_check_findings_stay_fixed():
    # 20 real dossiers read by hand: 9 wrong lines, 8 unfair verdicts. One check per pattern that changed a verdict.
    from mergescout.signals.bump_ledger import NOT_PACKAGES
    from stackvitals.deps.dossier import dossier
    from stackvitals.deps.evidence import index_evidence
    cell = {"ecosystem": "npm", "package": "lib", "bump": "minor", "prs": 120, "repos": 50, "merged": 100, "closed_unmerged": 8,
            "ci_known": 110, "ci_failed": 9, "expected_failed": 8.0, "extra_commits": 3, "reverted": 0, "eco_inferred": False}
    m = {"ecosystem": "npm", "package": "lib", "version": "7.74.0", "repo": "acme/mono", "link": "claimed_unconfirmed",
         "deprecated": False, "status": None, "releases_12m": 6, "last_release": "2026-09-01", "first_release": "2015-01-01"}
    osv = {"npm:lib": {"advisories": 0, "last_2y": 0, "unfixed": 0, "severity": {}, "malware": False, "ids": []}}
    ev = lambda cells, trend=None: index_evidence({"cells": cells}, {"packages": {"npm:lib": m}}, {"repos": trend or {}},  # noqa: E731
                                                  {"packages": osv, "complete": True})
    # swiper, typescript: an established monorepo package whose root manifest has another name is a fact, not a warning.
    assert dossier("npm", "lib", ev([cell]), NOW)["verdict"] == "use"
    # Docker "ubuntu" bumps were counted as npm's "ubuntu": a guessed ecosystem never decides, and image names aren't guessed.
    assert dossier("npm", "lib", ev([{**cell, "eco_inferred": True}]), NOW)["verdict"] is None and "ubuntu" in NOT_PACKAGES
    # dask: 71 of 89 outside PRs still open last quarter while the merge rate of the decided ones looked fine.
    q = {"outside_opened": 89, "outside_decided": 18, "outside_merge_rate": 0.6, "first_response_hours": 20, "top_merger_share": 0.4}
    trend = {"acme/mono": {"stars": 9000, "quarters": [q] * 4, "direction": {}, "peers": {}}}
    assert "71 of 89" in dossier("npm", "lib", ev([cell], trend), NOW)["reasons"][0]
    # react-hook-form's malware record (MAL-2026-2853) has no range, only the bad version: it is named.
    rec = {"id": "MAL-2026-2853", "aliases": [], "published": "2026-09-30T00:00:00Z", "modified": "x",
           "affected": [{"package": {"name": "lib", "ecosystem": "npm"}, "versions": ["7.73.0"]}]}
    got = refresh_vulns([("npm", "lib")], {}, NOW, lambda url, body: {"results": [{"vulns": [{"id": rec["id"], "modified": "x"}]}]},
                        lambda url: rec)
    assert got["packages"]["npm:lib"]["malware_versions"] == ["7.73.0"]


def test_names_versions_and_owner_changes_found_on_real_data():
    from mergescout.signals.bump_ledger import parse_branch, valid_name
    from mergescout.signals.deps_map import PRERELEASE
    from mergescout.signals.owners_watch import refresh_owners
    assert parse_branch("dependabot/pip/boto3-approx-eq-1.35.0")[1] == "boto3"
    assert not valid_name("pypi", "https://github.com/astral-sh/ruff-pre-commit") and not valid_name("npm", "jdx/mise")
    assert PRERELEASE.search("1.0.0.dev6") and PRERELEASE.search("6.0.0-beta.3") and not PRERELEASE.search("2.32.3")
    latest = {"version": "1.7.0", "_npmUser": {"name": "GitHub Actions", "email": "a@b", "trustedPublisher": {"id": "github"}},
              "maintainers": [{"name": "jason", "email": "c@d"}], "dist": {}}
    day1 = refresh_owners([("npm", "axios", "1.7.0")], {}, NOW, lambda url: latest)
    later = {**latest, "version": "1.7.1", "_npmUser": {"name": "someone", "email": "e@f"}}
    day2 = refresh_owners([("npm", "axios", "1.7.0")], day1, NOW + timedelta(days=1), lambda url: later)
    assert [e["kind"] for e in day2["packages"]["npm:axios"]["events"]][0] == "trusted_lost" and "@" not in str(day2)


def test_the_pr_check_reads_lockfile_changes_and_never_comments_on_forks(tmp_path):
    import json

    import httpx

    from stackvitals.ci.api import ActionsAPI
    from stackvitals.deps.action import lockfile_changes, run_deps_action
    base = '{"lockfileVersion": 3, "packages": {"node_modules/lodash": {"version": "4.17.20"}}}'
    head = '{"lockfileVersion": 3, "packages": {"node_modules/lodash": {"version": "4.17.21"}, "node_modules/axios": {"version": "1.7.0"}}}'
    assert [c["change"] for c in lockfile_changes("package-lock.json", base, head)] == ["added", "changed"]
    posted = []

    def handler(request):
        if request.url.path.endswith("/pulls/7/files"):
            return httpx.Response(200, json=[{"filename": "package-lock.json", "status": "modified"}])
        if request.url.path.endswith("/contents/package-lock.json"):
            return httpx.Response(200, content=(base if request.url.params["ref"] == "b" else head).encode())
        if request.url.path.endswith("/contents/decisions/state.json"):
            return httpx.Response(404, json={})  # no accepted packages
        posted.append(request.url.path)
        return httpx.Response(201, json={})
    event = tmp_path / "e.json"
    event.write_text(json.dumps({"pull_request": {"number": 7, "base": {"sha": "b"}, "head": {"sha": "h", "repo": {"full_name": "fork/r"}}}}))
    env = {"GITHUB_EVENT_NAME": "pull_request", "GITHUB_EVENT_PATH": str(event), "GITHUB_REPOSITORY": "o/r", "GITHUB_TOKEN": "t"}
    out = run_deps_action(env, now=NOW, evidence=None, comments=True,
                          make_api=lambda t, r, **k: ActionsAPI(t, r, client=httpx.Client(transport=httpx.MockTransport(handler))))
    assert out["changed"] == 2 and posted == []


def test_the_pr_check_cannot_be_fooled_or_broken_by_the_prs_own_files(tmp_path, capsys):
    # Review findings: a folder name injected workflow commands, an alias or another host borrowed a registry verdict,
    # and one unreadable lockfile crashed the whole check.
    import json

    import httpx

    from stackvitals.ci.api import ActionsAPI
    from stackvitals.deps.action import run_deps_action
    evil = "x,line=1\n::error::spoofed/package-lock.json"
    head = json.dumps({"lockfileVersion": 3, "packages": {"node_modules/react": {"name": "evil-pkg", "version": "1.0.0"},
                       "node_modules/lodash": {"version": "4.17.21", "resolved": "https://evil.example/lodash.tgz"}}})

    def handler(request):
        if request.url.path.endswith("/pulls/7/files"):
            return httpx.Response(200, json=[{"filename": evil, "status": "added"}, {"filename": "uv.lock", "status": "added"}])
        if "uv.lock" in request.url.path:
            return httpx.Response(200, content=b"<<<<<<< HEAD\n")
        if request.url.params.get("ref") == "h":
            return httpx.Response(200, content=head.encode())
        return httpx.Response(404, json={})
    event = tmp_path / "e.json"
    event.write_text(json.dumps({"pull_request": {"number": 7, "base": {"sha": "b"}, "head": {"sha": "h", "repo": {"full_name": "o/r"}}}}))
    env = {"GITHUB_EVENT_NAME": "pull_request", "GITHUB_EVENT_PATH": str(event), "GITHUB_REPOSITORY": "o/r", "GITHUB_TOKEN": "t",
           "GITHUB_STEP_SUMMARY": str(tmp_path / "s.md")}
    lodash = {"ecosystem": "npm", "package": "lodash", "version": "4.17.21", "repo": "lodash/lodash", "link": "verified",
              "deprecated": False, "status": None, "releases_12m": 2, "last_release": "2026-01-01", "first_release": "2012-01-01"}
    from stackvitals.deps.evidence import index_evidence
    ev = index_evidence({"cells": []}, {"packages": {"npm:lodash": lodash}}, {"repos": {}}, {"packages": {}})
    out = run_deps_action(env, now=NOW, evidence=ev,
                          make_api=lambda t, r, **k: ActionsAPI(t, r, client=httpx.Client(transport=httpx.MockTransport(handler))))
    summary, printed = (tmp_path / "s.md").read_text(encoding="utf-8"), capsys.readouterr().out
    assert not any(line.startswith("::error") for line in printed.splitlines())
    assert "npm:evil-pkg" in summary and out["monitor"] == 1 and "evil.example" in summary and "uv.lock" in summary


def test_old_release_counts_are_looked_up_again_and_a_quiet_repo_is_reported():
    # Real data (httpx, 2026-10-21): the map said its latest release was a 1.0.0.dev build of 2026-08-31 beside the stable
    # 0.28.1, and its trend printed nothing although outside pull requests had stopped two quarters earlier.
    from datetime import datetime, timezone

    from mergescout.signals.deps_map import refresh_map
    from stackvitals.deps.dossier import _trend_lines
    now = datetime(2026, 10, 21, tzinfo=timezone.utc)
    old = {"pypi:httpx": {"version": "0.28.1", "last_release": "2026-08-31", "fetched_at": "2026-10-20T00:00:00Z"}}
    asked = []
    refresh_map([("pypi", "httpx")], old, now, lookup=lambda pkgs, **kw: asked.extend(pkgs) or {})
    assert asked == [("pypi", "httpx")]
    quarters = [{"quarter": q, "outside_opened": n, "outside_decided": d, "outside_merge_rate": r}
                for q, n, d, r in (("2025Q4", 23, 9, 0.22), ("2026Q1", 28, 8, 0.12), ("2026Q2", 0, 0, None), ("2026Q3", 0, 0, None))]
    lines, _ = _trend_lines({"direction": {}, "quarters": quarters}, {"repo": "encode/httpx"})
    assert any(x["signal"] == "warn" and "last 2 quarters" in x["text"] for x in lines)


def test_security_updates_waiting_over_48_hours_are_called_out():
    """P11 M3: the hygiene view Dependabot doesn't give, from pull requests already kept."""
    from stackvitals.deps.hygiene import hygiene
    def bump(n, hours, title):
        return {"n": n, "ti": title, "cr": (NOW - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ"), "au": "dependabot[bot]",
                "at": "Bot", "head": f"dependabot/pip/x-{n}", "lb": []}
    out = hygiene({"open": [bump(1, 60, "[Security] Bump urllib3 from 2.0.0 to 2.2.2"),
                            bump(2, 10, "[Security] Bump idna from 3.6 to 3.7")], "closed": []}, {}, NOW)
    assert [u["pr"] for u in out["security_overdue"]] == [1]


def test_the_sbom_waits_out_githubs_still_working_answer_and_licence_choices_are_read_right():
    # Real-data finding (pallets/flask): while the report is made GitHub answers 202 with a "{}" body, not an empty one.
    import json as js

    from stackvitals.deps import supply

    class Api:
        repo, pending, slept = "o/r", 2, 0

        def sleep(self, s):
            self.slept += 1

        def _get(self, path, params=None, raw=False):
            return {"sbom_url": "https://api.github.com/repos/o/r/dependency-graph/sbom/fetch-report/u1"}

        def fetch(self, path):
            if self.pending:
                self.pending -= 1
                return 202, b"{}"
            return 200, js.dumps({"packages": [{"name": "x", "versionInfo": "1.0", "licenseConcluded": "GPL-3.0-only OR MIT",
                                                "externalRefs": [{"referenceType": "purl", "referenceLocator": "pkg:npm/x@1.0"}]}]}).encode()
    api = Api()
    packages = supply.sbom(api)
    assert [p["name"] for p in packages] == ["x"] and api.slept == 2
    # A choice of licences is fine when one choice is allowed.
    assert supply.policy(packages, ["GPL-3.0*"])["denied"] == []


def test_packages_without_a_source_project_never_break_the_scorecard_pass(tmp_path):
    # Trial error: a package deps.dev links to no project crashed the Scorecard pass.
    import httpx

    from stackvitals.deps import supply
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"licenses": ["MIT"], "relatedProjects": []})))
    pkgs = [{"purl": "pkg:npm/x@1.0", "name": "x", "version": "1.0", "system": "NPM", "licences": []}]
    assert supply.scorecards(pkgs, client, supply.SupplyStore(tmp_path), NOW)["projects"] == 0


def test_the_sbom_skips_the_repo_itself_and_scores_workflow_actions_by_their_repo(tmp_path):
    # Real-data finding (sandbox SBOM): the repo itself is listed with a pkg:github purl (what the document DESCRIBES),
    # and workflow actions come as pkg:githubactions, which deps.dev doesn't know.
    import httpx

    from stackvitals.deps import supply
    doc = {"packages": [{"name": "actions/checkout", "SPDXID": "SPDXRef-a", "versionInfo": "4.*.*", "externalRefs": [
                            {"referenceType": "purl", "referenceLocator": "pkg:githubactions/actions/checkout@4.%2A.%2A"}]},
                        {"name": "com.github.o/r", "SPDXID": "SPDXRef-repo", "versionInfo": "main", "externalRefs": [
                            {"referenceType": "purl", "referenceLocator": "pkg:github/o/r@main"}]}],
           "relationships": [{"relationshipType": "DESCRIBES", "spdxElementId": "SPDXRef-DOCUMENT", "relatedSpdxElement": "SPDXRef-repo"}]}
    packages = supply.parse_spdx(doc)
    assert [(p["system"], p["name"]) for p in packages] == [("ACTIONS", "actions/checkout")]
    asked = []
    client = httpx.Client(transport=httpx.MockTransport(
        lambda r: asked.append(str(r.url)) or httpx.Response(200, json={"score": 8.0, "date": "2026-10-19"})))
    assert supply.scorecards(packages, client, supply.SupplyStore(tmp_path), NOW)["checked"] == 1
    assert asked == ["https://api.scorecard.dev/projects/github.com/actions/checkout"]
    assert supply.policy(packages, ["GPL-*"])["unknown"] == 0  # actions run in CI and never ship


def test_a_refused_sbom_is_asked_again_weekly_while_a_slow_one_retries_next_run(tmp_path):
    # Fresh-install finding: the dependency graph is off by default on private repos, and every 3-hourly run asked
    # again and warned again.
    from datetime import timedelta

    from stackvitals.ci.api import APIError
    from stackvitals.core.config import parse
    from stackvitals.deps import supply

    class Ws:
        path, cache, notes, repo = tmp_path, {"settings": parse("")[0]}, [], "o/r"
    asked = []

    class Off:
        repo = "o/r"

        def _get(self, path, params=None, raw=False):
            asked.append(path)
            raise APIError(f"GET {path}: HTTP 404 Not Found")
    run = lambda when: supply.supply_step(Ws, {"GITHUB_EVENT_NAME": "schedule"}, when, make_api=lambda *a, **k: Off())  # noqa: E731
    assert run(NOW)["error"] and run(NOW + timedelta(hours=3)) is None and len(asked) == 1
    assert run(NOW + timedelta(days=7))["error"] and len(asked) == 2


def test_dependency_depth_exploits_versions_policy_rollbacks_and_paths():
    import json as _json

    from stackvitals.deps.action import apply_policy
    from stackvitals.deps.dossier import _osv_lines
    from stackvitals.deps.lockfiles import dependency_paths
    # Exploited in the wild beats the severity label; the installed version is checked against the fix (real advisory).
    osv = {"advisories": 1, "ids": [], "kev": [{"id": "CVE-2023-32681", "fixed": True}],
           "affects": [{"id": "GHSA-j8r2-6x86-q33q", "ranges": [["2.3.0", "2.31.0"]]}]}
    lines = _osv_lines(osv, True, versions=["2.30.0"])
    assert any(x["signal"] == "warn" and "CISA KEV" in x["text"] for x in lines)
    assert any(x["signal"] == "alarm" and "fixed in 2.31.0" in x["text"] for x in lines)
    assert not any("affected by" in x["text"] for x in _osv_lines(osv, True, versions=["2.31.0"]))
    # A repo's severity policy flags, and says how to accept.
    d = {"verdict": "use", "reasons": [], "osv": {"open_severity": "CRITICAL"}}
    assert apply_policy(d, {"max_severity": "high"}, "x")["verdict"] == "investigate"
    # The way a flagged package came in, from the lockfile's own graph.
    lock = _json.dumps({"lockfileVersion": 3, "packages": {"": {"dependencies": {"a": "1"}},
                        "node_modules/a": {"version": "1", "dependencies": {"b": "1"}}, "node_modules/b": {"version": "1"}}})
    assert dependency_paths("package-lock.json", lock, {"b"}) == {"b": ["a", "b"]}


def test_lookalike_names_need_few_downloads_and_reachability_reads_govulncheck():
    import httpx

    from stackvitals.deps.lookalike import judge
    from stackvitals.deps.reach import read_govulncheck
    # Real names from the bench: a malicious look-alike with 4 downloads a week, a legitimate one with 192 million.
    popular = {"npm": {"express", "safe-buffer"}}
    counts = {"exprses": 4, "safer-buffer": 192455187}
    stats = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"downloads": counts[r.url.path.rsplit("/", 1)[-1]]})))
    assert judge("npm", "exprses", popular, stats)["verdict"] == "investigate"
    assert judge("npm", "safer-buffer", popular, stats) is None
    stream = ('{"osv": {"id": "GO-1", "aliases": ["CVE-1"]}}\n{"finding": {"osv": "GO-1", "fixed_version": "v2", "trace": '
              '[{"module": "m", "package": "m/p", "function": "F"}, {"module": "app", "package": "app", "function": "main"}]}}')
    found = read_govulncheck(stream)["findings"][0]
    assert (found["reach"], found["fixed"], found["path"]) == ("called", "v2", ["main", "p.F"])


def test_with_outside_lookups_off_no_dependency_name_leaves_the_repo(tmp_path):
    # Trust groundwork: docs/privacy.md promises `[deps] outside_lookups = false` keeps every package name in the repo.
    import json
    import httpx
    from stackvitals.core.config import parse
    from stackvitals.deps import supply
    from stackvitals.deps.lookalike import judge
    spdx = {"spdxVersion": "SPDX-2.3", "packages": [{"SPDXID": "p1", "name": "npm:left-pad", "versionInfo": "1.3.0",
                                                      "licenseConcluded": "GPL-3.0-only", "externalRefs": [
        {"referenceCategory": "PACKAGE-MANAGER", "referenceType": "purl", "referenceLocator": "pkg:npm/left-pad@1.3.0"}]}],
        "relationships": []}

    class API:
        repo = "o/r"

        def _get(self, path, params=None, raw=False):
            return {"sbom_url": "https://api.github.com/repos/o/r/dependency-graph/sbom/fetch-report/u1"}

        def fetch(self, path):
            return 200, json.dumps(spdx).encode()

        def sleep(self, s):
            pass

    class Ws:
        def __init__(self, path, settings):
            self.path, self.cache, self.notes, self.repo = path, {"settings": settings}, [], "o/r"
    sent = []
    client = httpx.Client(transport=httpx.MockTransport(lambda r: sent.append(str(r.url)) or httpx.Response(500)))
    cfg = parse('[deps]\noutside_lookups = false\n[deps.licenses]\ndeny = ["GPL-3.0*"]\n')[0]
    out = supply.supply_step(Ws(tmp_path, cfg), {"GITHUB_EVENT_NAME": "schedule"}, NOW, make_api=lambda *a, **k: API(), client=client)
    # Review finding: off once wiped every licence, so the deny list passed everything; GitHub's own licences stay.
    assert out["packages"] == 1 and out["denied"] == 1 and sent == []
    assert judge("npm", "lodahs", {"npm": {"lodash"}}, None)["verdict"] == "monitor" and sent == []


def test_every_lockfile_is_scanned_by_the_pinned_scanner_and_a_wrong_download_is_refused(tmp_path, monkeypatch):
    # Phase 19: every package in every ecosystem, from a scanner pinned by version and SHA-256, cached by the Action.
    from pathlib import Path

    import pytest
    import yaml

    from stackvitals.deps import vulns
    root = Path(__file__).resolve().parents[1]
    action = yaml.safe_load((root / "action.yml").read_text(encoding="utf-8"))
    cache = next(s for s in action["runs"]["steps"] if "actions/cache@" in (s.get("uses") or ""))
    assert f"osv-scanner-{vulns.SCANNER}" in cache["with"]["path"] and len(vulns.SHA256) == 6
    assert vulns.scannable("svc/Cargo.lock") and vulns.scannable("composer.lock") and not vulns.scannable("vendor/x/composer.lock")

    class Bad:
        def get(self, url):
            class R:
                content = b"not the scanner"
                def raise_for_status(self):
                    return self
            return R()
    monkeypatch.setattr(vulns, "asset", lambda: "osv-scanner_linux_amd64")
    with pytest.raises(vulns.ScannerError, match="SHA-256"):
        vulns.ensure_scanner(tmp_path, client=Bad())
