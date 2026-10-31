import json

from stackvitals.deps.lockfiles import dependency_paths

NPM = json.dumps({"lockfileVersion": 3, "packages": {
    "": {"name": "app", "dependencies": {"express": "^4"}, "devDependencies": {"jest": "^29"}},
    "node_modules/express": {"version": "4.19.0", "dependencies": {"body-parser": "1.20.0", "qs": "6.11.0"}},
    "node_modules/body-parser": {"version": "1.20.0", "dependencies": {"qs": "6.10.0"}},
    # body-parser's own copy of qs sits under it; express gets the hoisted one.
    "node_modules/body-parser/node_modules/qs": {"version": "6.10.0"},
    "node_modules/qs": {"version": "6.11.0", "dependencies": {"side-channel": "^1"}},
    "node_modules/side-channel": {"version": "1.0.6"},
    "node_modules/jest": {"version": "29.7.0"}}})

UV = """
version = 1
[[package]]
name = "app"
version = "0.1.0"
source = { editable = "." }
dependencies = [{ name = "requests" }]

[[package]]
name = "requests"
version = "2.32.0"
source = { registry = "https://pypi.org/simple" }
dependencies = [{ name = "urllib3" }, { name = "idna" }]

[[package]]
name = "urllib3"
version = "2.2.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "idna"
version = "3.7"
source = { registry = "https://pypi.org/simple" }
"""

POETRY = """
[[package]]
name = "flask"
version = "3.0.0"
[package.dependencies]
werkzeug = ">=3.0"
jinja2 = ">=3.1"

[[package]]
name = "werkzeug"
version = "3.0.1"
[package.dependencies]
MarkupSafe = ">=2.1"

[[package]]
name = "markupsafe"
version = "2.1.5"

[[package]]
name = "jinja2"
version = "3.1.4"
"""


def test_npm_paths_follow_nodes_lookup_from_a_direct_dependency():
    got = dependency_paths("package-lock.json", NPM, {"side-channel", "qs", "express", "nope"})
    assert got["side-channel"] == ["express", "qs", "side-channel"]
    assert got["qs"] == ["express", "qs"]
    assert got["express"] == ["express"] and "nope" not in got


def test_uv_paths_start_at_the_project_and_poetry_at_packages_nothing_needs():
    assert dependency_paths("uv.lock", UV, {"urllib3"}) == {"urllib3": ["requests", "urllib3"]}
    # Review finding: poetry.lock does not say which packages are direct, so no chain is guessed.
    assert dependency_paths("poetry.lock", POETRY, {"markupsafe"}) == {}


def test_files_without_a_graph_and_broken_files_give_no_paths():
    assert dependency_paths("requirements.txt", "requests==2.32.0\n", {"requests"}) == {}
    assert dependency_paths("package-lock.json", "{not json", {"qs"}) == {}
    cyclic = json.dumps({"lockfileVersion": 3, "packages": {"": {"dependencies": {"a": "1"}},
                         "node_modules/a": {"version": "1", "dependencies": {"b": "1"}},
                         "node_modules/b": {"version": "1", "dependencies": {"a": "1"}}}})
    assert dependency_paths("package-lock.json", cyclic, {"b"}) == {"b": ["a", "b"]}
