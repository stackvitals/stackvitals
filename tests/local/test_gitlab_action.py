import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from stackvitals.ci import action, gitlab_action
from stackvitals.ci.action import DataBranch, GitError
from stackvitals.ci.feedback import MARKER

NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)


def _ts(hours):
    return (NOW - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _job(jid, name, status, hours):
    return {"id": jid, "name": name, "status": status, "stage": "test", "created_at": _ts(hours),
            "started_at": _ts(hours), "finished_at": _ts(hours - 0.1), "tag_list": []}


class FakeLab:
    # Twelve default-branch pipelines where "unit" fails once and passes on retry, plus one running MR pipeline.
    def __init__(self, project, token=None, base=None, notes=None):
        self.project, self.sent = project, []
        self.notes = notes if notes is not None else []
        self.pipes, self.jobs = [], {}
        for i in range(12):
            pid, h = 100 + i, 200 - i * 10
            self.pipes.append({"id": pid, "status": "success", "source": "push", "ref": "main", "sha": f"s{i}",
                               "created_at": _ts(h), "started_at": _ts(h), "updated_at": _ts(h - 1)})
            self.jobs[pid] = [_job(pid * 10, "unit", "failed", h), _job(pid * 10 + 1, "unit", "success", h - 0.5),
                              _job(pid * 10 + 2, "lint", "success", h)]
        self.live = {"id": 999, "status": "running", "source": "merge_request_event",
                     "ref": "refs/merge-requests/7/head", "sha": "mrsha", "created_at": _ts(1), "updated_at": _ts(0.5)}
        self.jobs[999] = [_job(9990, "unit", "failed", 1), _job(9991, "lint", "success", 1),
                          _job(9992, "stackvitals", "running", 0.2)]

    def get(self, path, params=None):
        if path == "":
            return {"default_branch": "main"}
        assert path == "/pipelines/999"
        return self.live

    def pages(self, path, params, limit=50):
        if path == "/pipelines":
            yield from self.pipes + [self.live]
        elif path.endswith("/notes"):
            yield from self.notes
        else:
            yield from self.jobs[int(path.split("/")[2])]

    def send(self, method, path, body):
        self.sent.append((method, path, body))
        return {}


def _env(**more):
    return {"CI_PROJECT_PATH": "g/p", "GITLAB_TOKEN": "tok", "CI_DEFAULT_BRANCH": "main", "CI_JOB_NAME": "stackvitals",
            **more}


def _remote(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    return bare


def test_history_lands_in_data_branch_and_pages(tmp_path):
    bare = _remote(tmp_path)
    labs = []
    make = lambda *a, **k: labs.append(FakeLab(*a, **k)) or labs[-1]
    out = gitlab_action.run(_env(STACKVITALS_PAGES_DIR=str(tmp_path / "public")), NOW, make, bare.as_uri())
    assert out["pipelines"] == 12 and out["outcome"] != "rejected" and out["note"] is None
    files = subprocess.run(["git", "ls-tree", "-r", "--name-only", "stackvitals-data"], cwd=bare,
                           capture_output=True, text=True).stdout
    assert "ci/state.json" in files and "docs/index.html" in files
    assert (tmp_path / "public" / "index.html").exists()
    # The running pipeline is never stored: it is read again once it finishes.
    assert "999" not in subprocess.run(["git", "grep", "-l", '"id": 999', "stackvitals-data"], cwd=bare,
                                       capture_output=True, text=True).stdout


def test_failed_mr_pipeline_gets_one_note_then_edits_it(tmp_path):
    bare = _remote(tmp_path)
    labs = []
    make = lambda *a, **k: labs.append(FakeLab(*a, **k)) or labs[-1]
    env = _env(CI_MERGE_REQUEST_IID="7", CI_PIPELINE_ID="999", STACKVITALS_PAGES_DIR=str(tmp_path / "public"))
    out = gitlab_action.run(env, NOW, make, bare.as_uri())
    assert out["note"] == "created"
    method, path, body = labs[-1].sent[0]
    assert (method, path) == ("POST", "/merge_requests/7/notes")
    # The note names the flaky job, never the StackVitals job itself, and no GitHub-only verdict check.
    assert MARKER in body["body"] and "`GitLab CI / unit`" in body["body"] and "/ stackvitals`" not in body["body"]
    # GitLab job logs are not read, so a job that flaked before is never called a likely flake there.
    assert "Flaked before" in body["body"] and "verdict passes" not in body["body"]
    make2 = lambda *a, **k: labs.append(FakeLab(*a, notes=[{"id": 55, "body": body["body"]}], **k)) or labs[-1]
    out = gitlab_action.run(env, NOW, make2, bare.as_uri())
    assert out["note"] == "updated" and labs[-1].sent[0][:2] == ("PUT", "/merge_requests/7/notes/55")


def test_missing_token_says_what_to_set():
    try:
        gitlab_action.run({"CI_PROJECT_PATH": "g/p"}, NOW)
    except SystemExit as exc:
        assert "GITLAB_TOKEN" in str(exc)
    else:
        raise AssertionError("expected a stop")


def _make(labs, **kw):
    return lambda *a, **k: labs.append(FakeLab(*a, **kw, **k)) or labs[-1]


def _refusing_remote(tmp_path):
    # A server-side hook that turns every push down, like a protected branch or a push rule.
    bare = _remote(tmp_path)
    hook = bare / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'GitLab: You are not allowed to push code to protected branches' >&2\nexit 1\n",
                    encoding="utf-8", newline="\n")
    hook.chmod(0o755)
    return bare


def test_a_refused_push_fails_the_job_and_says_what_to_check(tmp_path, monkeypatch):
    monkeypatch.setattr(gitlab_action.time, "sleep", lambda s: None)
    bare = _refusing_remote(tmp_path)
    with pytest.raises(SystemExit) as stop:
        gitlab_action.run(_env(STACKVITALS_PAGES_DIR=str(tmp_path / "public")), NOW, _make([]), bare.as_uri())
    msg = str(stop.value)
    assert "stackvitals-data" in msg and "protected" in msg and "write_repository" in msg


def test_a_race_lost_on_every_try_fails_the_job(tmp_path, monkeypatch):
    monkeypatch.setattr(gitlab_action.time, "sleep", lambda s: None)
    monkeypatch.setattr(gitlab_action.DataBranch, "commit_push", lambda self, m: "rejected")
    with pytest.raises(SystemExit) as stop:
        gitlab_action.run(_env(STACKVITALS_PAGES_DIR=str(tmp_path / "public")), NOW, _make([]),
                          _remote(tmp_path).as_uri())
    assert "stackvitals-data" in str(stop.value)


def test_data_branch_refused_push_raises_but_a_race_still_retries(tmp_path, monkeypatch):
    monkeypatch.setattr(action.time, "sleep", lambda s: None)
    refused = DataBranch(_refusing_remote(tmp_path).as_uri(), "stackvitals-data", tmp_path / "a")
    refused.open()
    (refused.path / "f.txt").write_text("1", encoding="utf-8")
    with pytest.raises(GitError, match="refused"):
        refused.commit_push("one")
    # A plain race (someone pushed first) is still the caller's cue to start again.
    (tmp_path / "r").mkdir()
    bare = _remote(tmp_path / "r")
    first, other = (DataBranch(bare.as_uri(), "stackvitals-data", tmp_path / n) for n in ("b", "c"))
    first.open(), other.open()
    (first.path / "f.txt").write_text("1", encoding="utf-8")
    (other.path / "f.txt").write_text("2", encoding="utf-8")
    assert other.commit_push("other") == "pushed" and first.commit_push("mine") == "rejected"


def test_branch_pipeline_with_an_open_mr_notes_that_mr(tmp_path):
    labs = []
    env = _env(CI_OPEN_MERGE_REQUESTS="g/other!3,g/p!7", CI_COMMIT_BRANCH="fix", CI_PIPELINE_ID="999",
               STACKVITALS_PAGES_DIR=str(tmp_path / "public"))
    out = gitlab_action.run(env, NOW, _make(labs), _remote(tmp_path).as_uri())
    assert out["note"] == "created" and labs[-1].sent[0][:2] == ("POST", "/merge_requests/7/notes")


def test_open_mrs_of_other_projects_are_ignored():
    assert gitlab_action._mr_iid({"CI_PROJECT_PATH": "g/p", "CI_OPEN_MERGE_REQUESTS": "g/other!3"}) is None
    assert gitlab_action._mr_iid({"CI_PROJECT_PATH": "g/p", "CI_OPEN_MERGE_REQUESTS": "g/pp!3,g/p!12"}) == "12"
    assert gitlab_action._mr_iid({"CI_PROJECT_PATH": "g/p", "CI_MERGE_REQUEST_IID": "5",
                                  "CI_OPEN_MERGE_REQUESTS": "g/p!12"}) == "5"


def test_template_runs_in_branch_pipelines_with_an_open_mr():
    yaml = pytest.importorskip("yaml")
    tpl = yaml.safe_load((Path(__file__).parents[2] / "templates" / "gitlab" / "stackvitals.yml").read_text("utf-8"))
    rules = tpl["stackvitals"]["rules"]
    assert {"if": "$CI_COMMIT_BRANCH && $CI_OPEN_MERGE_REQUESTS", "when": "always"} in rules


def _passing_lab(labs, notes):
    # The same MR pipeline, but "unit" passed this time.
    def make(*a, **k):
        lab = FakeLab(*a, notes=notes, **k)
        lab.jobs[999][0] = _job(9990, "unit", "success", 1)
        labs.append(lab)
        return lab
    return make


def test_a_passing_pipeline_turns_the_old_note_into_passing_now(tmp_path):
    labs = []
    env = _env(CI_MERGE_REQUEST_IID="7", CI_PIPELINE_ID="999", STACKVITALS_PAGES_DIR=str(tmp_path / "public"))
    out = gitlab_action.run(env, NOW, _passing_lab(labs, [{"id": 55, "body": f"{MARKER}\nold failure"}]),
                            _remote(tmp_path).as_uri())
    method, path, body = labs[-1].sent[0]
    assert out["note"] == "updated" and (method, path) == ("PUT", "/merge_requests/7/notes/55")
    assert MARKER in body["body"] and "CI is passing now" in body["body"] and "The latest run passed." in body["body"]


def test_a_passing_pipeline_with_no_note_posts_nothing(tmp_path):
    labs = []
    env = _env(CI_MERGE_REQUEST_IID="7", CI_PIPELINE_ID="999", STACKVITALS_PAGES_DIR=str(tmp_path / "public"))
    out = gitlab_action.run(env, NOW, _passing_lab(labs, []), _remote(tmp_path).as_uri())
    assert out["note"] is None and labs[-1].sent == []


def test_notes_are_read_twenty_pages_deep():
    seen = {}

    class Lab:
        def pages(self, path, params, limit=50):
            seen["limit"] = limit
            return iter([])

        def send(self, *a):
            return {}
    gitlab_action._note(Lab(), "7", "x")
    assert seen["limit"] == 20


def test_remote_follows_the_server_url_and_never_shows_the_token(tmp_path, monkeypatch):
    remote = gitlab_action._remote_url({"CI_SERVER_URL": "http://git.example.com:8080/gl", "CI_PROJECT_PATH": "g/p"}, "tok")
    assert remote == "http://oauth2:tok@git.example.com:8080/gl/g/p.git"
    assert gitlab_action._remote_url({"CI_PROJECT_PATH": "g/p"}, "tok") == "https://oauth2:tok@gitlab.com/g/p.git"
    # A server that can't be reached: the error names no token.
    monkeypatch.setattr(action.time, "sleep", lambda s: None)
    secret = "glpat-SECRET123"
    bad = gitlab_action._remote_url({"CI_SERVER_URL": "http://127.0.0.1:9", "CI_PROJECT_PATH": "g/p"}, secret)
    with pytest.raises(GitError) as err:
        DataBranch(bad, "stackvitals-data", tmp_path / "x").open()
    assert secret not in str(err.value)
