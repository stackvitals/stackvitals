import base64
import json
from datetime import datetime, timezone

import httpx

from stackvitals.ci.api import ActionsAPI
from stackvitals.deps.action import lockfile_changes, run_deps_action
from stackvitals.deps.evidence import index_evidence

NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
BASE = json.dumps({"lockfileVersion": 3, "packages": {"": {}, "node_modules/lodash": {"version": "4.17.20"},
                                                      "node_modules/left-pad": {"version": "1.3.0"}}})
HEAD = json.dumps({"lockfileVersion": 3, "packages": {"": {}, "node_modules/lodash": {"version": "4.17.21"},
                                                      "node_modules/axios": {"version": "1.7.0"}}})


def test_changes_are_added_upgraded_and_removed_packages():
    changes = lockfile_changes("package-lock.json", BASE, HEAD)
    assert changes == [{"ecosystem": "npm", "package": "axios", "change": "added", "from": [], "to": ["1.7.0"]},
                       {"ecosystem": "npm", "package": "lodash", "change": "changed", "from": ["4.17.20"], "to": ["4.17.21"]}]


def evidence():
    m = lambda pkg, repo: {"ecosystem": "npm", "package": pkg, "version": "1.0.0", "repo": repo, "link": "verified",  # noqa: E731
                           "deprecated": False, "status": None, "releases_12m": 5, "last_release": "2026-09-01",
                           "first_release": "2015-01-01"}
    cell = lambda pkg: {"ecosystem": "npm", "package": pkg, "bump": "minor", "prs": 120, "repos": 50, "merged": 100,  # noqa: E731
                        "closed_unmerged": 5, "ci_known": 100, "ci_failed": 8, "expected_failed": 7.0, "extra_commits": 2,
                        "reverted": 0}
    osv = {"npm:axios": {"advisories": 3, "last_2y": 2, "unfixed": 0, "latest": "2026-09-30", "severity": {}, "malware": True,
                         "malware_ids": ["MAL-2026-2307"], "ids": []}}
    return index_evidence({"cells": [cell("lodash"), cell("axios")]},
                          {"packages": {"npm:lodash": m("lodash", "lodash/lodash"), "npm:axios": m("axios", "axios/axios")}},
                          {"repos": {}}, {"packages": osv})


def api_with(comments):
    def handler(request):
        path = request.url.path
        if path == "/repos/o/r/pulls/7/files":
            return httpx.Response(200, json=[{"filename": "web/package-lock.json", "status": "modified"},
                                             {"filename": "src/app.js", "status": "modified"}])
        if path == "/repos/o/r/contents/web/package-lock.json":
            return httpx.Response(200, content=(BASE if request.url.params["ref"] == "base1" else HEAD).encode())
        if path == "/repos/o/r/issues/7/comments" and request.method == "GET":
            return httpx.Response(200, json=[])
        if path == "/repos/o/r/issues/7/comments" and request.method == "POST":
            comments.append(json.loads(request.content)["body"])
            return httpx.Response(201, json={"id": 1})
        return httpx.Response(404, json={"message": "Not Found"})
    return lambda token, repo, **kw: ActionsAPI(token, repo, client=httpx.Client(transport=httpx.MockTransport(handler)),
                                                sleep=lambda s: None, **kw)


def event(tmp_path, fork=False):
    path = tmp_path / "event.json"
    path.write_text(json.dumps({"pull_request": {"number": 7, "base": {"sha": "base1", "repo": {"full_name": "o/r"}},
                                                 "head": {"sha": "head1", "repo": {"full_name": "fork/r" if fork else "o/r"}}}}))
    return {"GITHUB_EVENT_NAME": "pull_request", "GITHUB_EVENT_PATH": str(path), "GITHUB_REPOSITORY": "o/r",
            "GITHUB_TOKEN": "t", "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md")}


def test_a_pull_request_that_changes_a_lockfile_gets_verdicts_in_the_summary_and_annotations(tmp_path, capsys):
    comments = []
    out = run_deps_action(event(tmp_path), now=NOW, make_api=api_with(comments), evidence=evidence())
    assert out == {"lockfiles": 1, "changed": 2, "investigate": 1, "monitor": 0}
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "axios" in summary and "investigate" in summary and "MAL-2026-2307" in summary and "4.17.20 → 4.17.21" in summary
    printed = capsys.readouterr().out
    assert "::warning file=web/package-lock.json" in printed and comments == []  # comments are opt-in


def test_comments_are_opt_in_and_never_on_fork_prs(tmp_path):
    comments = []
    run_deps_action(event(tmp_path), now=NOW, make_api=api_with(comments), evidence=evidence(), comments=True)
    assert len(comments) == 1 and "axios" in comments[0] and "<!-- stackvitals:deps -->" in comments[0]
    comments.clear()
    run_deps_action(event(tmp_path, fork=True), now=NOW, make_api=api_with(comments), evidence=evidence(), comments=True)
    assert comments == []


def test_other_events_and_prs_without_lockfiles_do_nothing(tmp_path):
    env = {**event(tmp_path), "GITHUB_EVENT_NAME": "schedule"}
    assert run_deps_action(env, now=NOW, make_api=api_with([]), evidence=evidence()) is None


def test_without_evidence_the_summary_says_so_and_the_run_passes(tmp_path):
    out = run_deps_action(event(tmp_path), now=NOW, make_api=api_with([]), evidence=None)
    assert out["changed"] == 2 and "evidence" in (tmp_path / "summary.md").read_text(encoding="utf-8").lower()


def test_on_pull_requests_only_the_dependency_check_runs(tmp_path, monkeypatch, capsys):
    # CI health and Team Flow write to the data branch; a fork PR's token is read-only, so they never run on PRs.
    import stackvitals.ci.cli as cli
    import stackvitals.deps.action as deps_action
    called = {}
    monkeypatch.setattr(cli, "run_action", lambda *a, **k: called.setdefault("ci", True))
    monkeypatch.setattr(deps_action, "run_deps_action", lambda env, **k: (called.update(deps=k),
                        {"lockfiles": 1, "changed": 2, "investigate": 1, "monitor": 0})[1])
    for k, v in event(tmp_path).items():
        monkeypatch.setenv(k, v)
    assert cli.action_main(["--modules", "ci,flow,deps", "--deps-comments", "true"]) == 0
    assert "ci" not in called and called["deps"]["comments"] is True
    assert "Dependency check: 2 changed packages in 1 lockfile, 1 to investigate" in capsys.readouterr().out


def test_the_workflow_template_runs_the_check_on_lockfile_changes():
    from stackvitals.ci.cli import workflow_template
    text = workflow_template("o/a@v0", ["CI"])
    assert "pull_request:" in text and "**/*lock.json" in text and "**/*.lock" in text and "ci,flow,deps" in text


def fake_api(files, contents, comments=None, comment_status=201):
    from urllib.parse import unquote

    def handler(request):
        path = unquote(request.url.raw_path.decode().split("?", 1)[0])
        if path.endswith("/pulls/7/files"):
            page = int(request.url.params.get("page", 1))
            return httpx.Response(200, json=files[(page - 1) * 100: page * 100])
        if "/contents/" in path:
            body = contents.get((path.split("/contents/", 1)[1], request.url.params["ref"]))
            if isinstance(body, int):
                return httpx.Response(body, json={})
            return httpx.Response(200, content=body) if body is not None else httpx.Response(404, json={})
        if path.endswith("/issues/7/comments"):
            if request.method == "GET":
                return httpx.Response(200, json=[])
            if comments is not None:
                comments.append(json.loads(request.content)["body"])
            return httpx.Response(comment_status, json={"id": 1})
        return httpx.Response(404, json={})
    return lambda token, repo, **kw: ActionsAPI(token, repo, client=httpx.Client(transport=httpx.MockTransport(handler)),
                                                sleep=lambda s: None, **kw)


def test_a_pr_file_name_cannot_inject_workflow_commands(tmp_path, capsys):
    # Review: a fork PR named a folder "x,line=1,title=ok\n::error::spoofed" and printed a real ::error line.
    evil = "x,line=1,title=ok\n::error::spoofed/package-lock.json"
    run_deps_action(event(tmp_path), now=NOW, make_api=fake_api([{"filename": evil, "status": "added"}],
                                                                {(evil, "head1"): HEAD.encode()}), evidence=evidence())
    printed = capsys.readouterr().out
    assert not any(line.startswith("::error") for line in printed.splitlines()) and "file=x%2Cline=1%2Ctitle=ok%0A" in printed


def test_unreadable_lockfiles_are_reported_and_never_fail_the_check(tmp_path):
    # Review: UTF-16 requirements (PowerShell's pip freeze >), a BOM, conflict markers, a 502 and a "#" in a path all crashed.
    req16 = b"\xff\xfe" + "requests==2.32.3\n".encode("utf-16-le")
    names = ("a/requirements.txt", "b/package-lock.json", "c/uv.lock", "d/requirements.txt", "e#1/requirements.txt")
    files = [{"filename": n, "status": "added"} for n in names]
    contents = {("a/requirements.txt", "head1"): req16, ("b/package-lock.json", "head1"): b"\xef\xbb\xbf" + HEAD.encode(),
                ("c/uv.lock", "head1"): b"<<<<<<< HEAD\n[[package]]\n", ("d/requirements.txt", "head1"): 502,
                ("e#1/requirements.txt", "head1"): b"flask==3.1.0\n"}
    out = run_deps_action(event(tmp_path), now=NOW, make_api=fake_api(files, contents), evidence=None)
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert out["changed"] == 4 and "pypi:requests" in summary and "npm:axios" in summary and "pypi:flask" in summary
    assert "c/uv.lock" in summary and "d/requirements.txt" in summary and "couldn't be read" in summary


def test_the_action_never_fails_a_pr_check_on_a_dependency_check_error(tmp_path, monkeypatch, capsys):
    import stackvitals.ci.cli as cli
    import stackvitals.deps.action as deps_action

    def boom(env, **k):
        raise RuntimeError("out of requests")
    monkeypatch.setattr(deps_action, "run_deps_action", boom)
    for k, v in event(tmp_path).items():
        monkeypatch.setenv(k, v)
    assert cli.action_main(["--modules", "deps"]) == 0
    assert "::warning::The dependency check could not finish" in capsys.readouterr().out


def test_pr_checks_get_their_own_concurrency_group_and_a_token_fallback():
    # Review: PR runs shared "stackvitals" with CI runs, so GitHub cancelled a pending PR check when CI finished.
    from pathlib import Path

    from stackvitals.ci.cli import workflow_template
    assert "group: stackvitals-${{ github.event.pull_request.number || (" in workflow_template("o/a@v0", ["CI"])
    assert "GITHUB_TOKEN: ${{ github.token }}" in Path(__file__).parents[2].joinpath("action.yml").read_text(encoding="utf-8")


def test_an_aliased_or_off_registry_package_never_borrows_a_registry_packages_verdict(tmp_path):
    # Review: "node_modules/react" with name "evil-pkg", or lodash from another host, showed the real package's verdict.
    head = json.dumps({"lockfileVersion": 3, "packages": {"": {}, "node_modules/react": {
        "name": "evil-pkg", "version": "1.0.0", "resolved": "https://registry.npmjs.org/evil-pkg/-/evil-pkg-1.0.0.tgz"},
        "node_modules/lodash": {"version": "4.17.21", "resolved": "https://evil.example/lodash-4.17.21.tgz"}}})
    out = run_deps_action(event(tmp_path), now=NOW, make_api=fake_api([{"filename": "package-lock.json", "status": "added"}],
                                                                      {("package-lock.json", "head1"): head.encode()}),
                          evidence=evidence())
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "npm:evil-pkg" in summary and "npm:react" not in summary
    assert out["monitor"] == 1 and "evil.example" in summary
    uv = '[[package]]\nname = "requests"\nversion = "2.32.3"\nsource = { git = "https://github.com/evil/requests" }\n'
    from stackvitals.deps.lockfiles import foreign_sources
    assert foreign_sources("uv.lock", uv) == {("pypi", "requests"): "github.com"}


def test_a_renamed_lockfile_is_compared_with_its_old_path(tmp_path):
    files = [{"filename": "reqs/requirements.txt", "status": "renamed", "previous_filename": "requirements.txt"}]
    body = b"requests==2.32.3\nflask==3.1.0\n"
    out = run_deps_action(event(tmp_path), now=NOW, make_api=fake_api(files, {("reqs/requirements.txt", "head1"): body,
                                                                            ("requirements.txt", "base1"): body}), evidence=None)
    assert out["changed"] == 0


def test_a_huge_lockfile_change_keeps_the_comment_under_githubs_limit_and_says_why_it_failed(tmp_path, capsys):
    big = {"lockfileVersion": 3, "packages": {"": {}, **{f"node_modules/pkg-{i}": {"version": "1.0.0"} for i in range(400)}}}
    comments = []
    api = fake_api([{"filename": "package-lock.json", "status": "added"}], {("package-lock.json", "head1"): json.dumps(big).encode()},
                   comments, comment_status=422)
    run_deps_action(event(tmp_path), now=NOW, make_api=api, evidence=evidence(), comments=True)
    assert len(comments[0]) < 20000 and "and 370 more" in comments[0]
    assert "HTTP 422" in capsys.readouterr().out


def test_lockfiles_past_the_first_300_changed_files_are_still_found(tmp_path):
    files = [{"filename": f"src/f{i}.js", "status": "modified"} for i in range(320)]
    files.append({"filename": "package-lock.json", "status": "modified"})
    out = run_deps_action(event(tmp_path), now=NOW, make_api=fake_api(files, {("package-lock.json", "head1"): HEAD.encode(),
                                                                            ("package-lock.json", "base1"): BASE.encode()}),
                          evidence=None)
    assert out["lockfiles"] == 1 and out["changed"] == 2


def test_package_names_and_registry_text_cannot_break_the_table_or_ping_people(tmp_path):
    ev = evidence()
    ev["map"]["npm:lodash"] = {**ev["map"]["npm:lodash"], "deprecated": True, "deprecated_reason": "ask @octocat\nfor help"}
    run_deps_action(event(tmp_path), now=NOW, make_api=api_with([]), evidence=ev)
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "@octocat" not in summary and "ask @​octocat for help" in summary


def test_a_flagged_package_pulled_in_by_another_names_the_way_it_came_in(tmp_path):
    global HEAD
    old = HEAD
    HEAD = json.dumps({"lockfileVersion": 3, "packages": {
        "": {"dependencies": {"lodash": "^4"}},
        "node_modules/lodash": {"version": "4.17.21", "dependencies": {"axios": "^1"}},
        "node_modules/axios": {"version": "1.7.0"}}})
    try:
        run_deps_action(event(tmp_path), now=NOW, make_api=api_with([]), evidence=evidence())
    finally:
        HEAD = old
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "npm:axios (via lodash → axios)" in summary and "npm:lodash (via" not in summary


def test_an_added_package_imitating_a_popular_one_with_few_downloads_is_flagged(tmp_path):
    global HEAD
    old = HEAD
    HEAD = json.dumps({"lockfileVersion": 3, "packages": {"": {}, "node_modules/lodahs": {"version": "1.0.0"},
                                                          "node_modules/lodash": {"version": "4.17.21"}}})
    stats = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"downloads": 4})))
    try:
        out = run_deps_action(event(tmp_path), now=NOW, make_api=api_with([]), evidence=evidence(), registry=stats)
    finally:
        HEAD = old
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert out["investigate"] == 1 and "one edit from the popular lodash" in summary and "4 downloads" in summary


def test_a_pull_request_that_only_adds_a_known_vulnerability_in_cargo_gets_the_comment(tmp_path, monkeypatch):
    from pathlib import Path
    from stackvitals.deps import vulns
    posted = []

    def handler(request):
        path = request.url.path
        if path == "/repos/o/r/pulls/7/files":
            return httpx.Response(200, json=[{"filename": "Cargo.lock", "status": "modified"}])
        if path == "/repos/o/r/issues/7/comments" and request.method == "GET":
            return httpx.Response(200, json=[])
        if path == "/repos/o/r/issues/7/comments" and request.method == "POST":
            posted.append(json.loads(request.content)["body"])
            return httpx.Response(201, json={"id": 1})
        return httpx.Response(404, json={"message": "Not Found"})
    make = lambda token, repo, **kw: ActionsAPI(token, repo, client=httpx.Client(transport=httpx.MockTransport(handler)),  # noqa: E731
                                                sleep=lambda s: None, **kw)
    added = {"id": "RUSTSEC-2026-0001", "file": "Cargo.lock", "ecosystem": "crates.io", "package": "tokio", "version": "1.0.0",
             "severity": "high", "malware": False, "fixed": "1.0.1", "summary": "x", "aliases": []}
    monkeypatch.setattr(vulns, "pr_diff", lambda *a, **k: {"added": [added], "removed": []})
    run_deps_action(event(tmp_path), now=NOW, make_api=make, comments=True, scan=Path("osv"))
    assert len(posted) == 1 and "tokio" in posted[0]
