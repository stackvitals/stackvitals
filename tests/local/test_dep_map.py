from datetime import datetime, timezone

from mergescout.signals.deps_map import check_claims, lookup_packages, manifest_name

NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)


def versions(name, system, dates, default):
    return {"packageKey": {"system": system, "name": name}, "versions": [
        {"versionKey": {"system": system, "name": name, "version": v}, "publishedAt": d, "isDefault": v == default}
        for v, d in dates]}


PACKAGES = {
    ("PYPI", "requests"): versions("requests", "PYPI", [("2.31.0", "2025-05-22T00:00:00Z"), ("2.32.3", "2026-05-29T00:00:00Z"),
                                                         ("2.32.4", "2026-09-01T00:00:00Z")], "2.32.4"),
    ("NPM", "@babel/core"): versions("@babel/core", "NPM", [("7.24.0", "2026-02-28T00:00:00Z")], "7.24.0"),
    ("NPM", "sigstore"): versions("sigstore", "NPM", [("3.0.0", "2026-08-01T00:00:00Z")], "3.0.0"),
}
VERSIONS = {
    ("PYPI", "requests", "2.32.4"): {"relatedProjects": [{"projectKey": {"id": "github.com/psf/requests"},
                                                          "relationProvenance": "UNVERIFIED_METADATA", "relationType": "SOURCE_REPO"}],
                                     "licenses": ["Apache-2.0"], "advisoryKeys": [{"id": "GHSA-9hjg-9r4m-mvj7"}],
                                     "isDeprecated": False, "projectStatus": {"status": "ACTIVE"}},
    ("NPM", "@babel/core", "7.24.0"): {"relatedProjects": [{"projectKey": {"id": "github.com/babel/babel"},
                                                            "relationProvenance": "UNVERIFIED_METADATA", "relationType": "SOURCE_REPO"}],
                                       "licenses": ["MIT"], "advisoryKeys": [], "isDeprecated": False},
    ("NPM", "sigstore", "3.0.0"): {"relatedProjects": [{"projectKey": {"id": "github.com/sigstore/sigstore-js"},
                                                        "relationProvenance": "SLSA_ATTESTATION", "relationType": "SOURCE_REPO"}],
                                   "attestations": [{"verified": True}], "licenses": ["Apache-2.0"], "advisoryKeys": []},
}


def fake_get(url):
    from urllib.parse import unquote
    system, name = url.split("/systems/")[1].split("/packages/")
    return PACKAGES.get((system.upper(), unquote(name)))


def fake_post(url, body):
    assert url.endswith("/v3alpha/versionbatch")
    out = []
    for req in body["requests"]:
        k = req["versionKey"]
        v = VERSIONS.get((k["system"], k["name"], k["version"]))
        out.append({"request": req, "version": {"versionKey": k, **v} if v else None})
    return {"responses": out}


def test_packages_get_their_repo_how_the_link_was_proven_and_release_history():
    got = lookup_packages([("pypi", "requests"), ("npm", "@babel/core"), ("npm", "sigstore"), ("npm", "no-such")],
                          fake_get, fake_post, NOW)
    r = got[("pypi", "requests")]
    assert (r["version"], r["repo"], r["link"]) == ("2.32.4", "psf/requests", "claimed")
    assert r["advisories"] == ["GHSA-9hjg-9r4m-mvj7"] and r["releases_12m"] == 2 and r["last_release"] == "2026-09-01"
    assert got[("npm", "sigstore")]["link"] == "verified"
    assert got[("npm", "no-such")]["repo"] is None and got[("npm", "no-such")]["link"] is None


def test_manifest_names_from_package_json_pyproject_and_setup_cfg():
    assert manifest_name("package.json", '{"name": "@babel/core", "version": "1"}') == "@babel/core"
    assert manifest_name("pyproject.toml", '[project]\nname = "Requests"\n') == "Requests"
    assert manifest_name("pyproject.toml", '[tool.poetry]\nname = "poetry-core"\n') == "poetry-core"
    assert manifest_name("setup.cfg", "[metadata]\nname = flask\n") == "flask"
    assert manifest_name("package.json", "not json") is None


class Manifests:
    """A fake GraphQL client returning each repo's manifests."""

    def __init__(self, files):
        self.files, self.calls = files, 0

    def query(self, query, variables=None, partial=False, **kw):
        from mergescout.github.graphql import GraphQLResult
        self.calls += 1
        data = {"rateLimit": {"cost": 1, "remaining": 999, "resetAt": "x"}}
        for line in query.splitlines():
            line = line.strip()
            if line.startswith("r") and ": repository(" in line:
                alias = line.split(":")[0]
                owner = line.split('owner: "')[1].split('"')[0]
                name = line.split('name: "')[1].split('"')[0]
                data[alias] = {}
                current = (alias, f"{owner}/{name}")
            elif line.startswith("f") and ": object(expression:" in line:
                key = line.split(":")[0]
                path = line.split('"HEAD:')[1].split('"')[0]
                text = self.files.get((current[1], path))
                data[current[0]][key] = {"text": text} if text is not None else None
        return GraphQLResult(data=data, cost=1, remaining=999, reset_at="x")


def test_a_claimed_link_is_checked_against_the_repos_own_manifest():
    infos = {("pypi", "requests"): {"ecosystem": "pypi", "package": "requests", "repo": "psf/requests", "link": "claimed"},
             ("npm", "@babel/core"): {"ecosystem": "npm", "package": "@babel/core", "repo": "babel/babel", "link": "claimed"},
             ("npm", "left-pad"): {"ecosystem": "npm", "package": "left-pad", "repo": "evil/fork", "link": "claimed"},
             ("npm", "sigstore"): {"ecosystem": "npm", "package": "sigstore", "repo": "sigstore/sigstore-js", "link": "verified"}}
    gql = Manifests({("psf/requests", "pyproject.toml"): '[project]\nname = "requests"\n',
                     ("babel/babel", "package.json"): '{"name": "babel"}',
                     ("babel/babel", "packages/babel-core/package.json"): '{"name": "@babel/core"}',
                     ("babel/babel", "packages/core/package.json"): None,
                     ("evil/fork", "package.json"): '{"name": "something-else"}'})
    check_claims(infos, gql)
    assert infos[("pypi", "requests")]["link"] == "claimed_checked"
    assert infos[("npm", "@babel/core")]["link"] == "claimed_checked"  # a monorepo folder named after the package
    assert infos[("npm", "left-pad")]["link"] == "claimed_unconfirmed"
    assert infos[("npm", "sigstore")]["link"] == "verified" and gql.calls == 1


def test_version_lookups_follow_deps_devs_pages_and_match_answers_by_key():
    # deps.dev answers 100 versions per page with a nextPageToken (found on 278 real packages: only 100 came back).
    def paged_post(url, body):
        start = int(body.get("pageToken") or 0)
        page = fake_post(url, {"requests": body["requests"][start:start + 1]})
        if start + 1 < len(body["requests"]):
            page["nextPageToken"] = str(start + 1)
        return page
    got = lookup_packages([("pypi", "requests"), ("npm", "@babel/core"), ("npm", "sigstore")], fake_get, paged_post, NOW)
    assert [got[k]["repo"] for k in (("pypi", "requests"), ("npm", "@babel/core"), ("npm", "sigstore"))] == \
        ["psf/requests", "babel/babel", "sigstore/sigstore-js"]


def test_setup_py_names_literal_or_through_a_constant():
    assert manifest_name("setup.py", 'from setuptools import setup\nsetup(\n    name="sentry-sdk",\n    version="2.0")') == "sentry-sdk"
    assert manifest_name("setup.py", 'NAME = "PyYAML"\nsetup(name=NAME)') == "PyYAML"
    assert manifest_name("setup.py", "import os\nsetup(name=os.environ['X'])") is None


def test_claims_look_in_common_monorepo_folders():
    # Real layouts from 33 unconfirmed links: langchain in libs/, ray in python/, acorn in acorn/, electron's npm/.
    infos = {("pypi", "langchain"): {"ecosystem": "pypi", "package": "langchain", "repo": "langchain-ai/langchain", "link": "claimed"},
             ("pypi", "ray"): {"ecosystem": "pypi", "package": "ray", "repo": "ray-project/ray", "link": "claimed"},
             ("npm", "acorn"): {"ecosystem": "npm", "package": "acorn", "repo": "acornjs/acorn", "link": "claimed"},
             ("npm", "electron"): {"ecosystem": "npm", "package": "electron", "repo": "electron/electron", "link": "claimed"},
             ("pypi", "nltk"): {"ecosystem": "pypi", "package": "nltk", "repo": "nltk/nltk", "link": "claimed"}}
    gql = Manifests({("langchain-ai/langchain", "libs/langchain/pyproject.toml"): '[project]\nname = "langchain"\n',
                     ("ray-project/ray", "python/setup.py"): 'setup(name="ray")',
                     ("acornjs/acorn", "acorn/package.json"): '{"name": "acorn"}',
                     ("electron/electron", "npm/package.json"): '{"name": "electron"}',
                     ("nltk/nltk", "setup.py"): 'setup(name="nltk")'})
    check_claims(infos, gql)
    assert {k: v["link"] for k, v in infos.items()} == {k: "claimed_checked" for k in infos}


def test_lookups_stop_at_the_time_budget_and_leave_the_rest_out():
    import time
    calls = []

    def slow_get(url):
        calls.append(url)
        time.sleep(0.2)
        return fake_get(url)
    got = lookup_packages([("pypi", "requests"), ("npm", "@babel/core"), ("npm", "sigstore")] * 5, slow_get, fake_post, NOW,
                          workers=1, budget_s=0.5)
    assert len(calls) < 15 and len(got) <= 3


def test_a_github_error_stops_the_checks_and_leaves_links_unchecked():
    from mergescout.github.graphql import RateLimited

    class Limited:
        def query(self, *a, **k):
            raise RateLimited("hourly limit")
    infos = {("pypi", "nltk"): {"ecosystem": "pypi", "package": "nltk", "repo": "nltk/nltk", "link": "claimed"}}
    assert check_claims(infos, Limited()) == 0 and infos[("pypi", "nltk")]["link"] == "claimed"


def test_the_daily_map_reuses_fresh_answers_and_looks_up_only_new_or_stale_packages():
    from mergescout.signals.deps_map import refresh_map
    previous = {"pypi:requests": {"ecosystem": "pypi", "package": "requests", "repo": "psf/requests", "link": "claimed_checked",
                                  "fetched_at": "2026-10-15T00:00:00Z", "release_rule": 2},
                "npm:lodash": {"ecosystem": "npm", "package": "lodash", "repo": "lodash/lodash", "link": "verified",
                               "fetched_at": "2026-09-01T00:00:00Z"}}
    asked, checked = [], []

    def lookup(pkgs, **kw):
        asked.extend(pkgs)
        return {p: {"ecosystem": p[0], "package": p[1], "repo": "x/y", "link": "claimed"} for p in pkgs if p != ("npm", "slow")}

    def check(infos, gql, **kw):
        checked.extend(k for k, v in infos.items() if v["link"] == "claimed")
        for v in infos.values():
            v["link"] = "claimed_checked" if v["link"] == "claimed" else v["link"]
        return len(checked)
    got = refresh_map([("pypi", "requests"), ("npm", "lodash"), ("npm", "react"), ("npm", "slow")], previous, NOW,
                      gql=object(), lookup=lookup, check=check)
    assert sorted(asked) == [("npm", "lodash"), ("npm", "react"), ("npm", "slow")]  # requests is 3 days old: reused
    assert got["pypi:requests"]["fetched_at"] == "2026-10-15T00:00:00Z" and got["npm:react"]["link"] == "claimed_checked"
    assert got["npm:react"]["fetched_at"] == "2026-10-18T12:00:00Z"
    assert "npm:slow" not in got and sorted(checked) == [("npm", "lodash"), ("npm", "react")]
    # Without a GitHub token new claimed links stay "claimed" (not checked yet).
    again = refresh_map([("npm", "vue")], {}, NOW, gql=None, lookup=lookup, check=check)
    assert again["npm:vue"]["link"] == "claimed"


def test_a_dropped_connection_skips_one_package_which_keeps_its_last_answer():
    import http.client

    def get(url):
        if "sigstore" in url:
            raise http.client.RemoteDisconnected("closed")
        return fake_get(url)
    got = lookup_packages([("pypi", "requests"), ("npm", "sigstore")], get, fake_post, NOW)
    assert ("npm", "sigstore") not in got and got[("pypi", "requests")]["repo"] == "psf/requests"


def test_a_prerelease_default_gives_way_to_the_newest_stable_version():
    # Real data: deps.dev's default for httpx is 1.0.0.dev6, whose metadata links no repo; 0.28.1 does.
    pkgs = {("PYPI", "httpx"): versions("httpx", "PYPI", [("0.28.1", "2025-12-06T00:00:00Z"), ("1.0.0.dev6", "2026-08-31T00:00:00Z")],
                                       "1.0.0.dev6"),
            ("NPM", "vite"): versions("vite", "NPM", [("5.4.0", "2026-08-01T00:00:00Z"), ("6.0.0-beta.3", "2026-09-01T00:00:00Z")],
                                      "6.0.0-beta.3")}

    def get(url):
        from urllib.parse import unquote
        system, name = url.split("/systems/")[1].split("/packages/")
        return pkgs.get((system.upper(), unquote(name)))
    got = lookup_packages([("pypi", "httpx"), ("npm", "vite")], get, lambda url, body: {"responses": []}, NOW)
    assert got[("pypi", "httpx")]["version"] == "0.28.1" and got[("npm", "vite")]["version"] == "5.4.0"


def test_a_cached_prerelease_answer_is_looked_up_again():
    from mergescout.signals.deps_map import refresh_map
    previous = {"pypi:httpx": {"ecosystem": "pypi", "package": "httpx", "version": "1.0.0.dev6", "repo": None, "link": None,
                               "fetched_at": "2026-10-17T00:00:00Z"}}
    asked = []

    def lookup(pkgs, **kw):
        asked.extend(pkgs)
        return {p: {"ecosystem": p[0], "package": p[1], "version": "0.28.1", "repo": "encode/httpx", "link": "verified"} for p in pkgs}
    got = refresh_map([("pypi", "httpx")], previous, NOW, lookup=lookup)
    assert asked == [("pypi", "httpx")] and got["pypi:httpx"]["repo"] == "encode/httpx"


def test_release_counts_and_the_latest_release_leave_out_nightly_builds():
    # Hand-check: dev and nightly builds were counted as releases, so a quiet package looked busy.
    pkg = versions("nightly", "PYPI", [("1.0.0", "2026-01-10T00:00:00Z"), ("1.1.0", "2026-06-01T00:00:00Z"),
                                       ("1.2.0.dev20261001", "2026-10-01T00:00:00Z"), ("1.2.0.dev20261002", "2026-10-02T00:00:00Z")],
                   "1.1.0")
    r = lookup_packages([("pypi", "nightly")], lambda url: pkg, lambda url, body: {"responses": []}, NOW)[("pypi", "nightly")]
    assert (r["releases_12m"], r["last_release"], r["first_release"]) == (2, "2026-06-01", "2026-01-10")


def test_a_deprecated_version_keeps_the_registrys_reason_cut_short():
    pkg = versions("old", "NPM", [("2.0.0", "2025-01-01T00:00:00Z")], "2.0.0")

    def post(url, body):
        k = body["requests"][0]["versionKey"]
        return {"responses": [{"request": body["requests"][0], "version": {
            "versionKey": k, "isDeprecated": True, "deprecatedReason": "Moved to new-pkg. " + "x" * 400}}]}
    r = lookup_packages([("npm", "old")], lambda url: pkg, post, NOW)[("npm", "old")]
    assert r["deprecated"] and r["deprecated_reason"].startswith("Moved to new-pkg.") and len(r["deprecated_reason"]) <= 160


def test_an_npm_package_published_from_a_repo_subfolder_is_checked_in_that_folder():
    # Hand-check: swiper and postcss-lab-function keep their manifest where npm's repository.directory says.
    infos = {("npm", "lab-fn"): {"ecosystem": "npm", "package": "lab-fn", "repo": "csstools/plugins", "link": "claimed"},
             ("npm", "sneaky"): {"ecosystem": "npm", "package": "sneaky", "repo": "a/b", "link": "claimed"}}
    gql = Manifests({("csstools/plugins", "plugins/lab-fn/package.json"): '{"name": "lab-fn"}'})
    registry = {"lab-fn": {"repository": {"type": "git", "url": "git+https://github.com/csstools/plugins.git",
                                          "directory": "./plugins/lab-fn/"}},
                "sneaky": {"repository": {"directory": 'x" } } evil: viewer { login'}}}
    asked = []

    def get_json(url):
        asked.append(url)
        return registry.get(url.split("registry.npmjs.org/")[1].split("/latest")[0])
    check_claims(infos, gql, get_json=get_json)
    assert infos[("npm", "lab-fn")]["link"] == "claimed_checked" and infos[("npm", "lab-fn")]["directory"] == "plugins/lab-fn"
    # A folder name that could change the query is never used.
    assert infos[("npm", "sneaky")].get("directory") is None and infos[("npm", "sneaky")]["link"] == "claimed_unconfirmed"
    assert len(asked) == 2


def test_odd_registry_answers_never_stop_the_claim_checks():
    # Review: "directory": 5 raised out of the thread pool and skipped the whole package map every day.
    infos = {("npm", n): {"ecosystem": "npm", "package": n, "repo": "a/b", "link": "claimed"} for n in ("num", "text", "boom")}
    answers = {"num": {"repository": {"directory": 5}}, "text": {"repository": "github:a/b"}}

    def get_json(url):
        name = url.split("registry.npmjs.org/")[1].split("/latest")[0]
        if name == "boom":
            raise ValueError("bad json")
        return answers[name]
    check_claims(infos, Manifests({}), get_json=get_json)
    assert all(i["directory"] is None and i["link"] == "claimed_unconfirmed" for i in infos.values())


def test_an_answer_counted_before_pre_releases_were_left_out_is_looked_up_again():
    # Real data (2026-10-21): httpx's map entry said its latest release was 2026-08-31 (a 1.0.0.dev build) next to the
    # stable 0.28.1 of 2024-12-06, because it was built before dev builds stopped counting as releases.
    from mergescout.signals.deps_map import refresh_map
    previous = {"pypi:httpx": {"ecosystem": "pypi", "package": "httpx", "version": "0.28.1", "last_release": "2026-08-31",
                               "fetched_at": "2026-10-17T00:00:00Z"}}
    asked = []

    def lookup(pkgs, **kw):
        asked.extend(pkgs)
        return {p: {"ecosystem": p[0], "package": p[1], "version": "0.28.1", "last_release": "2024-12-06", "release_rule": 2}
                for p in pkgs}
    got = refresh_map([("pypi", "httpx")], previous, NOW, gql=None, lookup=lookup)
    assert asked == [("pypi", "httpx")] and got["pypi:httpx"]["last_release"] == "2024-12-06"
