from itertools import combinations

import yaml

from stackvitals.ci.cli import MODULES, workflow_template


def _doc(mods):
    return yaml.safe_load(workflow_template(modules=mods))


def test_every_combination_of_modules_is_valid_and_asks_only_for_what_it_uses():
    for n in range(1, 5):
        for mods in combinations(MODULES, n):
            d, has = _doc(mods), set(mods)
            on, perms = d[True], d["permissions"]
            assert d["jobs"]["vitals"]["steps"][0]["with"]["modules"] == ",".join(mods)
            assert ("workflow_run" in on) == ("ci" in has) and ("pull_request" in on) == ("deps" in has)
            assert ("actions" in perms) == ("ci" in has) and ("deployments" in perms) == ("flow" in has)
            assert ("checks" in perms) == bool(has & {"ci", "flow"})
            assert perms["pull-requests"] == ("write" if has & {"ci", "flow"} else "read")
            assert perms["contents"] == "write" and "schedule" in on and "issue_comment" in on


def test_the_full_set_is_the_unchanged_template():
    assert workflow_template() == workflow_template(modules=MODULES)
    d = _doc(("deps",))
    assert set(d["permissions"]) == {"contents", "issues", "pull-requests"}


def test_a_private_repo_with_pages_on_is_warned_every_run(tmp_path):
    from datetime import datetime, timezone

    from stackvitals.core.appdata import write_app_data

    class WS:
        path, repo, now, notes = tmp_path, "o/r", datetime(2026, 10, 23, tzinfo=timezone.utc), []
        env, cache = {}, {"repo_info": {"private": True, "has_pages": True, "default_branch": "main"}}
    (tmp_path / "docs").mkdir()
    write_app_data(WS)
    assert any("GitHub Pages turned on" in n for n in WS.notes)
    WS.notes, WS.cache = [], {"repo_info": {"private": True, "has_pages": False}}
    write_app_data(WS)
    assert not WS.notes
