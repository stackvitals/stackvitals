import yaml

from stackvitals.portal.export import entities_yaml, entity

REPOS = [
    {"name": "acme/web", "description": "The storefront", "language": "TypeScript", "archived": False, "fork": False,
     "descriptor": {"present": False}, "owners": {"status": "valid", "owners": ["@acme/web-team", "@ann"]},
     "score": {"level": "silver"}, "topics": ["shop"]},
    {"name": "acme/api", "descriptor": {"present": True}, "archived": False, "fork": False},
    {"name": "acme/old", "archived": True, "fork": False, "descriptor": {"present": False}},
    {"name": "acme/tool", "description": None, "language": None, "archived": False, "fork": False,
     "descriptor": {"present": False}, "owners": {"status": "none", "owners": []}, "score": {"level": None}}]


def test_an_entity_says_what_the_repo_is_who_owns_it_and_its_level():
    e = entity(REPOS[0], "https://acme.github.io/portal/")
    assert e["kind"] == "Component" and e["metadata"]["name"] == "web" and e["spec"]["owner"] == "group:web-team"
    assert e["metadata"]["annotations"]["github.com/project-slug"] == "acme/web"
    assert e["metadata"]["annotations"]["stackvitals.dev/level"] == "silver" and e["metadata"]["tags"] == ["shop", "typescript"]
    assert e["metadata"]["links"][0]["url"].startswith("https://acme.github.io/portal/")
    assert entity(REPOS[3], None)["spec"]["owner"] == "unknown"


def test_the_export_covers_only_live_repos_without_their_own_catalog_file():
    docs = list(yaml.safe_load_all(entities_yaml(REPOS, None)))
    assert [d["metadata"]["name"] for d in docs] == ["web", "tool"]
