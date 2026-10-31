import base64
import json

import httpx
import pytest

from stackvitals.core import initcli
from stackvitals.core.initcli import FILE, GitHub, Stop, run_init

YAML = "name: StackVitals\non: push\n"


class Fake:
    """A small in-memory GitHub: one repo, its contents, workflow runs, branches and Pages."""

    def __init__(self, private=False, protected=False, existing=None, pages=None, run_ends="success", push=True):
        self.private, self.protected, self.existing, self.pages = private, protected, existing, pages
        self.run_ends, self.push = run_ends, push
        self.calls, self.files, self.branches, self.prs = [], {}, {"main"}, []
        self.runs, self.polls = [], 0

    def handler(self, req: httpx.Request) -> httpx.Response:
        m, path = req.method, req.url.raw_path.decode()
        body = json.loads(req.content) if req.content else None
        self.calls.append((m, path, body))
        repo = "/repos/o/r"
        if m == "GET" and path == repo:
            return httpx.Response(200, json={"default_branch": "main", "private": self.private,
                                             "permissions": {"push": self.push, "admin": False}})
        if path.startswith(f"{repo}/contents/{FILE}"):
            ref = path.split("ref=")[-1] if "ref=" in path else "main"
            if m == "GET":
                content = self.files.get(ref) or (self.existing if ref == "main" else None)
                if content is None:
                    return httpx.Response(404, json={"message": "Not Found"})
                return httpx.Response(200, json={"sha": "f1", "content": base64.b64encode(content.encode()).decode()})
            if m == "PUT":
                if self.protected and body["branch"] == "main":
                    return httpx.Response(409, json={"message": "Changes must be made through a pull request."})
                self.files[body["branch"]] = base64.b64decode(body["content"]).decode()
                if body["branch"] == "main":
                    self.runs.append({"id": 7, "head_sha": "c1", "status": "queued", "event": "push", "html_url": "https://run/7"})
                return httpx.Response(201, json={"commit": {"sha": "c1"}})
        if m == "GET" and path.startswith(f"{repo}/actions/workflows/stackvitals.yml/runs"):
            return httpx.Response(200, json={"workflow_runs": self.runs})
        if m == "GET" and path == f"{repo}/actions/runs/7":
            self.polls += 1
            if self.polls < 3:
                return httpx.Response(200, json={"status": "in_progress", "html_url": "https://run/7"})
            self.branches.add("stackvitals-data")
            return httpx.Response(200, json={"status": "completed", "conclusion": self.run_ends, "html_url": "https://run/7"})
        if m == "GET" and path.startswith(f"{repo}/branches/"):
            return httpx.Response(200 if path.rsplit("/", 1)[-1] in self.branches else 404, json={})
        if path == f"{repo}/pages":
            if m == "GET":
                return httpx.Response(200, json=self.pages) if self.pages else httpx.Response(404, json={"message": "Not Found"})
            if m == "POST":
                self.pages = {"source": body["source"], "html_url": "https://o.github.io/r/"}
                return httpx.Response(201, json=self.pages)
        if m == "GET" and path.startswith(f"{repo}/git/ref/heads/"):
            return httpx.Response(200, json={"object": {"sha": "base1"}})
        if m == "POST" and path == f"{repo}/git/refs":
            return httpx.Response(201, json={})
        if m == "GET" and path.startswith(f"{repo}/pulls"):
            return httpx.Response(200, json=[])
        if m == "POST" and path == f"{repo}/pulls":
            self.prs.append(body)
            return httpx.Response(201, json={"html_url": "https://pr/1", "number": 1})
        return httpx.Response(404, json={"message": f"unexpected {m} {path}"})


def go(fake, **kw):
    out = []
    gh = GitHub("t", httpx.Client(transport=httpx.MockTransport(fake.handler)))
    code = run_init("o/r", YAML, gh, out.append, sleep=lambda s: None, poll=0, **kw)
    return code, "\n".join(out)


def test_public_repo_commits_runs_and_turns_on_pages():
    fake = Fake()
    code, out = go(fake)
    assert code == 0
    assert fake.files["main"] == YAML
    assert ("POST", "/repos/o/r/pages", {"source": {"branch": "stackvitals-data", "path": "/docs"}}) in fake.calls
    assert "https://o.github.io/r/" in out


def test_private_repo_keeps_pages_off_and_points_at_the_local_app():
    fake = Fake(private=True)
    code, out = go(fake)
    assert code == 0
    assert not any(c[1] == "/repos/o/r/pages" for c in fake.calls)
    assert "stackvitals ui o/r" in out and "private" in out


def test_a_protected_branch_gets_a_pull_request_and_nothing_on_main():
    fake = Fake(protected=True)
    code, out = go(fake)
    assert code == 0
    assert "main" not in fake.files and fake.files["stackvitals-setup"] == YAML
    assert fake.prs and fake.prs[0]["base"] == "main"
    assert "https://pr/1" in out and "run this command again" in out


def test_a_different_existing_file_changes_only_through_a_pull_request():
    fake = Fake(existing="name: Old\n")
    code, out = go(fake)
    assert code == 0 and "main" not in fake.files and fake.prs


def test_replace_commits_over_a_different_file():
    fake = Fake(existing="name: Old\n")
    code, _ = go(fake, replace=True)
    assert code == 0 and fake.files["main"] == YAML


def test_the_same_file_is_left_alone_and_a_queued_run_is_followed():
    fake = Fake(existing=YAML)
    fake.runs.append({"id": 7, "head_sha": "x", "status": "queued", "event": "push", "html_url": "https://run/7"})
    code, out = go(fake)
    assert code == 0 and "already there" in out
    assert not any(c[0] == "PUT" for c in fake.calls)


def test_a_failed_first_run_stops_with_its_link():
    fake = Fake(run_ends="failure")
    with pytest.raises(Stop, match="https://run/7"):
        go(fake)


def test_pages_serving_something_else_is_kept():
    fake = Fake(pages={"build_type": "legacy", "source": {"branch": "gh-pages", "path": "/"}})
    code, out = go(fake)
    assert code == 0 and "kept as it is" in out
    assert not any(c[0] in ("POST", "PUT") and c[1] == "/repos/o/r/pages" for c in fake.calls)


def test_no_write_access_stops_before_writing():
    fake = Fake(push=False)
    with pytest.raises(Stop, match="not write"):
        go(fake)
    assert not any(c[0] in ("PUT", "POST") for c in fake.calls)


def test_no_token_changes_nothing(monkeypatch, capsys):
    monkeypatch.setattr(initcli.ci_cli, "token", lambda: None)
    assert initcli.main(["o/r"]) == 2
    assert "gh auth login" in capsys.readouterr().err


def test_a_bad_name_is_refused(capsys):
    assert initcli.main(["not-a-repo"]) == 2
