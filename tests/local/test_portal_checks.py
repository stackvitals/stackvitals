from stackvitals.portal.checks import load_level, plan, send


def repo(name, level, results, archived=False):
    return {"name": name, "default_branch": "main", "archived": archived, "fork": False,
            "score": {"level": level, "results": results}}


CATALOG = {"repos": [
    repo("o/a", "gold", [{"id": "owners", "level": "bronze", "result": "pass", "evidence": "CODEOWNERS"}]),
    repo("o/b", "bronze", [{"id": "owners", "level": "bronze", "result": "pass", "evidence": "ok"},
                           {"id": "branch-rule", "level": "silver", "result": "fail", "evidence": "no PR rule on main"},
                           {"id": "docs", "level": "gold", "result": "fail", "evidence": "no docs/"}]),
    repo("o/c", None, [], archived=True)]}


def test_the_required_level_is_read_from_portal_toml_and_off_by_default():
    assert load_level("") is None and load_level('[checks]\nlevel = "silver"\n') == "silver"
    assert load_level('[checks]\nlevel = "platinum"\n') is None


def test_each_repo_gets_a_check_saying_what_keeps_it_below_the_level():
    got = {c["repo"]: c for c in plan(CATALOG, "silver")}
    assert set(got) == {"o/a", "o/b"}  # archived repos get none
    assert got["o/a"]["conclusion"] == "success" and got["o/b"]["conclusion"] == "failure"
    assert "branch-rule" in got["o/b"]["summary"] and "no PR rule on main" in got["o/b"]["summary"]
    assert "docs" not in got["o/b"]["summary"]  # a gold rule doesn't block silver


def test_checks_go_on_the_default_branch_and_open_prs_within_a_write_cap():
    calls = []

    class Api:
        def _get(self, path, params=None):
            calls.append(("GET", path))
            if path.endswith("/commits/main"):
                return {"sha": "abc"}
            return [{"head": {"sha": "pr1"}}, {"head": {"sha": "pr2"}}]

        def send(self, method, path, body=None):
            calls.append((method, path, body["head_sha"], body["conclusion"]))
            return {}
    done = send(Api(), plan(CATALOG, "silver"), cap=3)
    posts = [c for c in calls if c[0] == "POST"]
    assert len(posts) == 3 and done["posted"] == 3 and done["stopped"] is True
    assert posts[0][1] == "/repos/o/a/check-runs" and {p[2] for p in posts} <= {"abc", "pr1", "pr2"}
