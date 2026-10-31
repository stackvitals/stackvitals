import base64
from datetime import date

import pytest

from stackvitals.core import decisions as dec
from stackvitals.ci.api import APIError
from stackvitals.portal.golden import GoldenError, load_paths, run

TOML = '''
[[golden_path]]
id = "service"
title = "New service"
kind = "repo"
template = "acme/service-template"

[[golden_path]]
id = "ci"
title = "Standard CI"
kind = "files"
folder = "golden/ci"
'''


class Api:
    def __init__(self, files=None):
        self.calls, self.files = [], files or {}

    def send(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path.endswith("/generate"):
            return {"html_url": "https://github.com/acme/payments"}
        if path.endswith("/pulls"):
            return {"html_url": "https://github.com/acme/web/pull/9"}
        return {}

    def _get(self, path, params=None):
        self.calls.append(("GET", path, params))
        if "/collaborators/" in path:
            return {"permission": "write" if path.endswith("/ann/permission") else "read"}
        if "/contents/" in path:
            raise APIError("GET contents: HTTP 404")
        if path == "/repos/acme/web":
            return {"default_branch": "main"}
        if path == "/repos/acme/web/git/ref/heads/main":
            return {"object": {"sha": "base1"}}
        if path.startswith("/repos/acme/portal/git/trees"):
            return {"tree": [{"path": p, "type": "blob"} for p in self.files] + [{"path": "golden/ci", "type": "tree"}]}
        raise AssertionError(path)

    def file(self, path, ref=None, repo=None):
        return self.files[path].encode()


def test_golden_paths_are_read_from_portal_toml_and_bad_ones_are_said():
    paths = load_paths(TOML)
    assert set(paths) == {"service", "ci"} and paths["service"]["private"] is True
    with pytest.raises(GoldenError):
        load_paths('[[golden_path]]\nid = "x"\nkind = "repo"\n')  # no template


def test_a_repo_path_creates_the_repo_from_the_template_in_the_org():
    app = Api()
    text, url = run(app, Api(), "acme/portal", "acme", load_paths(TOML)["service"], {"name": "payments", "description": "Pay"}, "ann")
    assert app.calls[0] == ("POST", "/repos/acme/service-template/generate",
                            {"owner": "acme", "name": "payments", "description": "Pay", "private": True})
    assert url == "https://github.com/acme/payments" and "payments" in text
    with pytest.raises(GoldenError):
        run(app, Api(), "acme/portal", "acme", load_paths(TOML)["service"], {"name": "../evil"}, "ann")


def test_a_files_path_opens_a_pr_with_the_portal_repos_files():
    app, portal = Api(), Api({"golden/ci/.github/workflows/ci.yml": "name: CI\n", "README-other.md": "x"})
    text, url = run(app, portal, "acme/portal", "acme", load_paths(TOML)["ci"], {"repo": "acme/web"}, "ann")
    puts = [c for c in app.calls if c[0] == "PUT"]
    assert [c[1] for c in puts] == ["/repos/acme/web/contents/.github/workflows/ci.yml"]
    assert base64.b64decode(puts[0][2]["content"]).decode() == "name: CI\n" and puts[0][2]["branch"] == "stackvitals/golden-ci"
    assert url == "https://github.com/acme/web/pull/9"
    with pytest.raises(GoldenError):
        run(app, portal, "acme/portal", "acme", load_paths(TOML)["ci"], {"repo": "other-org/web"}, "ann")
    # Review finding: write access to the portal repo isn't write access to the target repo.
    with pytest.raises(GoldenError, match="can't write"):
        run(Api(), portal, "acme/portal", "acme", load_paths(TOML)["ci"], {"repo": "acme/web"}, "mallory")


def test_a_request_block_can_ask_for_a_golden_path():
    body = '```stackvitals\n{"version": 1, "golden": {"path": "service", "inputs": {"name": "payments"}}}\n```'
    req = dec.parse_request(body, date(2026, 10, 23))
    assert req.golden == {"path": "service", "inputs": {"name": "payments"}} and not req.changes


def test_a_path_needing_approval_waits_and_runs_once_someone_else_approves(monkeypatch, tmp_path):
    from datetime import datetime, timezone

    from stackvitals.core import requests as rq
    from stackvitals.portal import golden
    ran = []
    monkeypatch.setattr(golden, "run", lambda app, api, repo, org, path, inputs, requester: ran.append((path["id"], requester)) or ("Created acme/pay.", "u"))
    toml = TOML.replace('template = "acme/service-template"', 'template = "acme/service-template"\napprovals = 1')
    body = '```stackvitals\n{"version": 1, "golden": {"path": "service", "inputs": {"name": "pay"}}}\n```'

    class Repo:
        repo = "acme/portal"

        def file(self, path, ref=None, repo=None):
            return toml.encode()

        def _get(self, path, params=None):
            if "/collaborators/" in path:
                return {"role_name": "write" if not path.endswith("/eve/permission") else "read"}
            if path.endswith("/issues/7"):
                return {"user": {"login": "ann"}, "body": body, "state": "open"}
            raise AssertionError(path)
    env = {"STACKVITALS_PORTAL_TOKEN": "app"}
    waiting = rq._golden(env, Repo(), {"path": "service", "inputs": {"name": "pay"}}, "ann", body=body)
    assert "needs someone else's approval" in rq._golden(env, Repo(), {"path": "service", "inputs": {"name": "pay"}}, "ann", issue=False)
    assert waiting.startswith(rq.WAITING) and ran == []

    class Store:
        def __init__(self):
            self.rows = []

        def record(self, changes, **k):
            self.rows += changes

    class WS:
        memo = {}
    said, now = [], datetime(2026, 10, 23, tzinfo=timezone.utc)
    say = lambda n, text, close: said.append((text, close))  # noqa: E731
    rq._approve(WS(), Repo(), Store(), {"kind": "comment", "number": 7, "login": "ann", "body": "/stackvitals approve"}, now, say, env)
    rq._approve(WS(), Repo(), Store(), {"kind": "comment", "number": 7, "login": "eve", "body": "/stackvitals approve"}, now, say, env)
    assert ran == [] and "someone other" in said[0][0] and "write access" in said[1][0]
    code = rq.approval_code(body)
    assert f"/stackvitals approve {code}" in waiting
    # Without the request's current code (or after the request was edited) nothing runs.
    rq._approve(WS(), Repo(), Store(), {"kind": "comment", "number": 7, "login": "bob", "body": "/stackvitals approve"}, now, say, env)
    rq._approve(WS(), Repo(), Store(), {"kind": "comment", "number": 7, "login": "bob", "body": "/stackvitals approve 0000beef"}, now, say, env)
    assert ran == [] and f"approve {code}" in said[-1][0] and said[-1][1] is None
    rq._approve(WS(), Repo(), Store(), {"kind": "comment", "number": 7, "login": "bob", "body": f"/stackvitals approve {code}"}, now, say, env)
    assert ran == [("service", "ann")] and said[-1][0].startswith("Approved by bob.") and said[-1][1] == "completed"
