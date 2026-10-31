"""Portal's typed catalog: a repo's catalog-info.yaml (Backstage's format), its owner checked against CODEOWNERS, file and
content checks from portal.toml, and rules that only count from a date ("enable later")."""
from datetime import datetime, timezone

from stackvitals.portal import descriptor
from stackvitals.portal.scorecard import evaluate, file_rules, load_rules

NOW = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)

BACKSTAGE = """
apiVersion: backstage.io/v1alpha1
kind: Component
metadata:
  name: artist-web
  title: Artist Web
  description: |
    The place to be,
    for great artists.
  annotations:
    github.com/project-slug: acme/artist-web
  tags: [java, web]
  links:
    - url: https://admin.example.com
      title: Admin
    - url: javascript:alert(1)
      title: Bad
spec:
  type: website
  lifecycle: production
  owner: group:default/artist-relations
  system: public-websites
  dependsOn:
    - resource:default/artists-db
    - component:search
  providesApis: [artist-api]
---
apiVersion: backstage.io/v1alpha1
kind: API
metadata:
  name: artist-api
spec:
  type: openapi
  lifecycle: production
  owner: artist-relations
  definition:
    $text: ./openapi.yaml
"""


def test_a_backstage_file_becomes_typed_entities():
    entities, problems = descriptor.parse(BACKSTAGE)
    assert problems == []
    web, api = entities
    assert (web["kind"], web["name"], web["type"], web["lifecycle"], web["owner"], web["system"]) == \
        ("Component", "artist-web", "website", "production", "group:default/artist-relations", "public-websites")
    assert web["depends_on"] == ["resource:default/artists-db", "component:search"] and web["provides_apis"] == ["artist-api"]
    assert web["description"].startswith("The place to be") and web["tags"] == ["java", "web"]
    assert web["links"] == [{"url": "https://admin.example.com", "title": "Admin"}]  # web links only
    assert (api["kind"], api["owner"], api["system"]) == ("API", "artist-relations", None)


def test_broken_or_thin_files_are_listed_never_fatal():
    entities, problems = descriptor.parse("kind: Component\nmetadata: {name: x}\nspec: {type: service}\n")
    assert entities[0]["name"] == "x" and problems == ["Component x: no lifecycle, owner"]
    assert descriptor.parse("kind: [unclosed")[0] == [] and descriptor.parse("kind: [unclosed")[1][0].startswith("not valid YAML")
    assert descriptor.parse("- just\n- a list\n")[1] == ["document 1 is not a mapping"]
    assert descriptor.parse("kind: Gadget\nmetadata: {name: g}\n")[1] == ["document 1: Gadget is not a Backstage kind"]
    assert descriptor.parse("kind: Component\nspec: {owner: a}\n")[1] == ["document 1: no metadata.name"]
    # Safe loading only: a Python tag never runs, it is a YAML problem.
    assert descriptor.parse("kind: !!python/object/apply:os.system ['echo hi']\n")[0] == []
    assert descriptor.parse("a: b\n" * 60000)[1] == ["catalog-info.yaml is over 256 KB; not read"]
    assert descriptor.parse("")[0] == [] and descriptor.parse("")[1] == ["catalog-info.yaml is empty"]


def test_entity_refs_follow_backstage():
    assert descriptor.ref("group:default/web-team", "group") == ("group", "default", "web-team")
    assert descriptor.ref("web-team", "group") == ("group", "default", "web-team")
    assert descriptor.ref("user:amy", "group") == ("user", "default", "amy")
    assert descriptor.ref("Team-A", "group") == ("group", "default", "team-a")
    assert descriptor.ref("", "group") is None and descriptor.ref(None, "group") is None


def test_the_catalog_owner_is_checked_against_codeowners():
    owners = ["@acme/artist-relations", "@amy", "docs@acme.com"]
    assert descriptor.owner_check("group:default/artist-relations", owners) == \
        ("pass", "artist-relations is @acme/artist-relations in CODEOWNERS")
    assert descriptor.owner_check("user:amy", owners)[0] == "pass"
    result, why = descriptor.owner_check("platform", owners)
    assert result == "fail" and why == "catalog-info.yaml names platform; CODEOWNERS names @acme/artist-relations, @amy"
    assert descriptor.owner_check(None, owners) == ("fail", "catalog-info.yaml names no owner")


RULES = """
[[rule]]
id = "catalog"
check = "catalog"
fields = ["owner", "lifecycle", "system"]
level = "bronze"

[[rule]]
id = "catalog-owner"
check = "catalog_owner"
level = "bronze"

[[rule]]
id = "runbook"
check = "file"
path = "docs/runbook.md"
contains = "^## On call"
level = "silver"

[[rule]]
id = "no-latest-tags"
check = "file"
path = "deploy/app.yaml"
lacks = ":latest"
level = "silver"

[[rule]]
id = "dockerfile"
check = "file"
path = "Dockerfile"
level = "gold"
from = 2027-01-01
"""


def repo(**over):
    base = {"name": "acme/artist-web", "owners": {"status": "valid", "owners": ["@acme/artist-relations"]},
            "descriptor": {"present": True, "entities": descriptor.parse(BACKSTAGE)[0], "problems": []},
            "files": {"docs/runbook.md": {"present": True, "contains:^## On call": True},
                      "deploy/app.yaml": {"present": True, "lacks::latest": False}, "Dockerfile": {"present": False}}}
    return {**base, **over}


def test_catalog_file_and_later_rules_in_the_scorecard():
    rules, ex = load_rules(RULES)
    out = evaluate(repo(), rules, ex, NOW, None)
    by = {r["id"]: r for r in out["results"]}
    assert by["catalog"] == {"id": "catalog", "level": "bronze", "result": "pass",
                             "evidence": "Component artist-web (website, production), owner group:default/artist-relations, "
                                         "system public-websites"}
    assert by["catalog-owner"]["result"] == "pass" and by["runbook"]["result"] == "pass"
    assert by["no-latest-tags"]["result"] == "pass"
    # Before its date a rule shows what it would say but never counts: gold has nothing that counts yet.
    assert by["dockerfile"]["result"] == "preview" and by["dockerfile"]["evidence"] == "counts from 2027-01-01; now: fail (no Dockerfile)"
    assert out["level"] == "silver"
    later = evaluate(repo(), rules, ex, datetime(2027, 1, 2, tzinfo=timezone.utc), None)
    assert {r["id"]: r["result"] for r in later["results"]}["dockerfile"] == "fail" and later["level"] == "silver"


def test_missing_pieces_fail_or_say_why_they_cannot_be_checked():
    rules, ex = load_rules(RULES)
    thin = descriptor.parse("kind: Component\nmetadata: {name: web}\nspec: {type: service, lifecycle: beta, owner: platform}\n")[0]
    out = {r["id"]: r for r in evaluate(repo(descriptor={"present": True, "entities": thin, "problems": []},
                                             files={"docs/runbook.md": {"present": True, "contains:^## On call": False},
                                                    "deploy/app.yaml": {"present": True, "lacks::latest": True}}),
                                        rules, ex, NOW, None)["results"]}
    assert (out["catalog"]["result"], out["catalog"]["evidence"]) == ("fail", "Component web: no system")
    assert out["catalog-owner"]["result"] == "fail" and "platform" in out["catalog-owner"]["evidence"]
    assert (out["runbook"]["result"], out["runbook"]["evidence"]) == ("fail", "docs/runbook.md doesn't match ^## On call")
    assert (out["no-latest-tags"]["result"], out["no-latest-tags"]["evidence"]) == ("fail", "deploy/app.yaml matches :latest")
    none = {r["id"]: r for r in evaluate(repo(descriptor={"present": False}, files={}), rules, ex, NOW, None)["results"]}
    assert (none["catalog"]["result"], none["catalog"]["evidence"]) == ("fail", "no catalog-info.yaml")
    assert none["catalog-owner"]["result"] == "not available" and none["runbook"]["result"] == "not available"


def test_rules_say_which_files_the_catalog_run_must_read():
    rules, _ = load_rules(RULES)
    assert file_rules(rules) == [{"path": "docs/runbook.md", "contains": "^## On call"},
                                 {"path": "deploy/app.yaml", "lacks": ":latest"}, {"path": "Dockerfile"}]
    import pytest
    with pytest.raises(ValueError):
        load_rules('[[rule]]\nid = "x"\ncheck = "file"\nlevel = "bronze"\n')  # a file rule needs a path
    with pytest.raises(ValueError):
        load_rules('[[rule]]\nid = "x"\ncheck = "file"\npath = "a"\ncontains = "("\nlevel = "bronze"\n')  # a broken regex


class FilesAPI:
    def __init__(self, files):
        self.files, self.requests, self.asked = files, 0, []

    def file(self, path, ref, repo=None):
        from stackvitals.ci.api import APIError
        self.requests += 1
        self.asked.append((repo, path, ref))
        if path not in self.files:
            raise APIError(f"GET /repos/{repo}/contents/{path}: HTTP 404 Not Found")
        return self.files[path].encode()


def test_the_catalog_run_reads_the_descriptor_and_checked_files_once_each():
    from stackvitals.portal.inventory import descriptor_for, file_facts
    api = FilesAPI({"catalog-info.yaml": BACKSTAGE, "docs/runbook.md": "# Runbook\n## On call\nPage the web team.\n"})
    r = {"name": "acme/artist-web", "default_branch": "main"}
    d = descriptor_for(api, r)
    assert d["present"] and [e["name"] for e in d["entities"]] == ["artist-web", "artist-api"] and d["problems"] == []
    rules, _ = load_rules(RULES)
    facts = file_facts(api, r, file_rules(rules))
    assert facts == {"docs/runbook.md": {"present": True, "contains:^## On call": True}, "deploy/app.yaml": {"present": False},
                     "Dockerfile": {"present": False}}
    assert ("acme/artist-web", "catalog-info.yaml", "main") in api.asked and api.requests == 4
    assert descriptor_for(FilesAPI({}), r) == {"present": False}


def test_the_org_catalog_carries_each_repos_entities_with_the_owner_check_and_the_file_facts():
    import sys
    sys.path.insert(0, "tests/local")
    from test_portal_catalog import org_routes
    from test_portal_m1 import fake

    from stackvitals.portal.catalog import build_catalog
    routes = org_routes(("api", "web"))
    routes["/repos/acme/api/contents/CODEOWNERS"] = (200, "* @acme/artist-relations\n")
    routes["/repos/acme/api/contents/catalog-info.yaml"] = (200, BACKSTAGE)
    routes["/repos/acme/api/contents/docs/runbook.md"] = (200, "## On call\n")
    routes["/orgs/acme/teams/artist-relations/members"] = (200, [{"login": "amy"}])
    rules, _ = load_rules(RULES)
    c = build_catalog(fake(routes)("t", "acme/portal"), "acme", "public", NOW, file_rules=file_rules(rules))
    by = {r["name"]: r for r in c["repos"]}
    api, web = by["acme/api"], by["acme/web"]
    assert [e["name"] for e in api["descriptor"]["entities"]] == ["artist-web", "artist-api"]
    # Shown on the Catalog tab without a rule: does CODEOWNERS agree with the owner the file names?
    assert api["descriptor"]["entities"][0]["owner_check"] == ["pass", "artist-relations is @acme/artist-relations in CODEOWNERS"]
    assert api["files"]["docs/runbook.md"] == {"present": True, "contains:^## On call": True}
    assert web["descriptor"] == {"present": False} and web["files"]["docs/runbook.md"] == {"present": False}


def test_the_printable_pages_list_the_catalog_and_its_problems():
    from stackvitals.portal.pages import render_catalog, render_catalog_html
    entities = descriptor.parse(BACKSTAGE)[0]
    entities[0]["owner_check"] = ["fail", "catalog-info.yaml names artist-relations; CODEOWNERS names @acme/web"]
    catalog = {"org": "acme", "built_at": "2026-10-21T12:00:00Z", "complete": True, "repos": [
        {"name": "acme/artist-web", "private": False, "owners": {"status": "valid"},
         "descriptor": {"present": True, "entities": entities, "problems": ["API artist-api: no system"]}},
        {"name": "acme/cli", "private": False, "owners": {"status": "none"}, "descriptor": {"present": False}}]}
    md = render_catalog(catalog, destination_private=False)
    assert "## Catalog" in md and "2 entities from 1 of 2 active repos" in md and "1 owner not in CODEOWNERS" in md
    assert "| artist-web | Component | website | production | group:default/artist-relations (not in CODEOWNERS) | public-websites | acme/artist-web |" in md
    assert "acme/artist-web: API artist-api: no system" in md
    page = render_catalog_html(catalog, destination_private=False)
    assert "<h2>Catalog</h2>" in page and "artist-web" in page and "not in CODEOWNERS" in page


def test_agents_get_the_typed_catalog_from_the_published_portal(tmp_path):
    import json
    import sys
    sys.path.insert(0, "tests/local")
    from test_ci_mcp import NoRel, mcp_call
    from test_portal_m1 import fake

    from mergescout.mcp_server import App
    from stackvitals.mcp_server import build_server
    entities = descriptor.parse(BACKSTAGE)[0]
    catalog = {"org": "acme", "built_at": "2026-10-21T12:00:00Z", "complete": True, "repos": [
        {"name": "acme/artist-web", "owners": {"status": "valid"}, "descriptor": {"present": True, "entities": entities,
                                                                                    "problems": ["API artist-api: no system"]}}]}
    app = App(root=tmp_path / "h", releases=NoRel(), live=None, log=lambda *a: None)
    routes = {"/repos/acme/portal/contents/portal/catalog.json": (200, json.dumps(catalog))}
    server = build_server(app, ci_api=fake(routes), ci_home=tmp_path / "sv", ci_token="tok")
    got = mcp_call(server, "org_catalog", {"org": "acme"})["catalog"]
    assert got["repos_with_file"] == 1 and got["problems"] == ["acme/artist-web: API artist-api: no system"]
    assert got["entities"][0]["name"] == "artist-web" and got["entities"][0]["depends_on"] == ["resource:default/artists-db", "component:search"]
