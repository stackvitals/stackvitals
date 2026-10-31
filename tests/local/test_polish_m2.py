"""Polish pass M2: one CODEOWNERS matcher with GitHub's rules, owners in CI Health, and PR-metadata workflows."""
from datetime import timedelta

from ci_fake import T0, iso

from stackvitals import codeowners

NOW = T0 + timedelta(days=30)
# GitHub's documented example file (docs: "About code owners").
DOCS = """# This is a comment.
*       @global-owner1 @global-owner2
*.js    @js-owner #This is an inline comment.
*.go docs@example.com
*.txt @octo-org/octocats
/build/logs/ @doctocat
docs/* docs@example.com
apps/ @octocat
/docs/ @doctocat
/scripts/ @doctocat @octocat
**/logs @octocat
/apps/ @octocat
/apps/github
"""


def owners(path, text=DOCS):
    return codeowners.owners_for(path, codeowners.parse(text))


def test_githubs_documented_examples():
    assert owners("README.md") == ["@global-owner1", "@global-owner2"]
    assert owners("src/web/app.js") == ["@js-owner"]  # inline comment dropped
    assert owners("cmd/main.go") == ["docs@example.com"] and owners("notes.txt") == ["@octo-org/octocats"]
    assert owners("build/logs/2026/run.log") == ["@octocat"]  # /build/logs/ then **/logs: the last match wins
    assert owners("docs/getting-started.md") == ["@doctocat"]
    assert owners("lib/docs/x.md") == ["@global-owner1", "@global-owner2"]  # /docs/ is anchored to the root
    assert owners("scripts/release.sh") == ["@doctocat", "@octocat"]
    assert owners("deep/a/logs/today") == ["@octocat"] and owners("logs") == ["@octocat"]
    assert owners("apps/github/index.js") == []  # a pattern with no owners leaves the path without owners
    assert owners("apps/web/index.html") == ["@octocat"] and owners("src/apps/x.py") == ["@octocat"]


def test_star_stays_in_one_folder_and_double_star_crosses_folders():
    text = "docs/* @a\nsrc/**/test_*.py @b\n/x/**/y @c\nweb/** @d\n"
    assert owners("docs/a.md", text) == ["@a"] and owners("docs/build-app/trouble.md", text) == []
    assert owners("src/test_a.py", text) == ["@b"] and owners("src/pkg/sub/test_a.py", text) == ["@b"]
    assert owners("lib/src/test_a.py", text) == []  # a slash inside the pattern anchors it to the root
    assert owners("x/y", text) == ["@c"] and owners("x/1/2/y", text) == ["@c"] and owners("web/a/b.css", text) == ["@d"]


def test_question_marks_escaped_spaces_and_lines_github_ignores():
    text = "file?.md @a\n/My\\ Docs/ @b\n!secret @c\n\n   # indented comment\n*.MD @d\n"
    assert owners("file1.md", text) == ["@a"] and owners("file12.md", text) == []
    assert owners("My Docs/plan.md", text) == ["@b"]
    assert owners("secret", text) == [] and owners("README.MD", text) == ["@d"] and owners("readme.md", text) == []


def test_every_module_uses_the_same_matcher():
    from stackvitals.flow.knowledge import codeowners_for
    from stackvitals.portal.owners import parse_codeowners
    # Team Flow had "docs/*" crossing folders and "/docs/" matching nested docs folders.
    assert codeowners_for("docs/build-app/trouble.md", "docs/* @a\n") == []
    assert codeowners_for("lib/docs/x.md", "/docs/ @a\n") == []
    assert codeowners_for("src/a.js", DOCS) == ["js-owner"]
    assert parse_codeowners("* @a # owners\n") == [("*", ["@a"])]


PIP_TRIGGERS = """name: PR Checklist

on:
  pull_request:
    types:
      - opened
      - edited
      - reopened
      - labeled
      - unlabeled

jobs:
  check-pr-template:
    if: >
      !contains(github.event.pull_request.labels.*.name, 'skip PR template check')
    name: Check PR template
    runs-on: ubuntu-slim
    steps:
      - name: Check PR body
        env:
          PR_BODY: ${{ github.event.pull_request.body }}
"""


def test_workflows_that_run_on_pr_edits_or_labels_are_recognised():
    from stackvitals.ci.triggers import pr_metadata_triggered as meta
    assert meta(PIP_TRIGGERS)  # real file: pypa/pip check-pr-template.yml
    assert not meta("on: [push, pull_request]\njobs: {}\n") and not meta("on: pull_request\n")
    assert not meta("on:\n  pull_request:\n    types: [opened, synchronize]\n    branches: [edited-docs]\n")
    assert meta("'on':\n  pull_request_target:\n    types: [ opened, \"labeled\" ]\n")
    assert meta("on:\n  push:\n  pull_request: {types: [edited]}\n")
    # Edits on issues are not PR edits; a comment mentioning "edited" is not a trigger.
    assert not meta("on:\n  issues:\n    types: [edited]\n  pull_request:  # runs when edited? no\n    paths: ['src/**']\n")


def pr_run(rid, day, c, path, tree="t1"):
    cr = T0 + timedelta(days=day)
    return {"t": "run", "id": rid, "att": 1, "path": path, "wfn": "W", "ev": "pull_request", "br": "fix", "sha": f"s{rid}",
            "tree": tree, "pr": [7], "c": c, "cr": iso(cr), "st": iso(cr), "up": iso(cr + timedelta(minutes=1))}


def pr_job(jid, rid, day, c, name):
    st = T0 + timedelta(days=day)
    return {"t": "job", "run": rid, "att": 1, "id": jid, "n": name, "c": c, "cr": iso(st), "st": iso(st),
            "en": iso(st + timedelta(minutes=1)), "lb": ["ubuntu-latest"], "steps": [[2, "Check PR body", c, iso(st), iso(st)]]}


def test_same_code_flips_in_pr_metadata_workflows_are_not_flakes_but_reruns_still_are():
    # Real data (pypa/pip): "Check PR template" flipped 19 times on the same code as people edited the PR description.
    from stackvitals.ci.analyze import analyze
    wf = ".github/workflows/check-pr-template.yml"
    data = {"runs": [pr_run(1, 20, "failure", wf), pr_run(2, 20, "success", wf), pr_run(3, 21, "failure", wf, tree="t2"),
                     pr_run(4, 21, "success", wf, tree="t2")],
            "jobs": [pr_job(10 + i, i, 20 + (i > 2), c, "Check PR template")
                     for i, c in ((1, "failure"), (2, "success"), (3, "failure"), (4, "success"))]}
    assert analyze(data, NOW, default_branch="main")["jobs"][0]["flake_events"] == 2
    quiet = analyze(data, NOW, default_branch="main", pr_metadata={wf: {"check-pr-template", "Check PR template"}})["jobs"][0]
    assert quiet["flake_events"] == 0 and quiet["state"] == "ok"
    rerun = {"runs": [pr_run(5, 22, "failure", wf), {**pr_run(5, 22, "success", wf), "att": 2}],
             "jobs": [pr_job(50, 5, 22, "failure", "Check PR template"), {**pr_job(51, 5, 22, "success", "Check PR template"), "att": 2}]}
    assert analyze(rerun, NOW, default_branch="main", pr_metadata={wf: {"Check PR template"}})["jobs"][0]["flake_events"] == 1


class FileAPI:
    def __init__(self, files):
        self.files, self.calls = files, []

    def file(self, path, ref, repo=None):
        from stackvitals.ci.api import NotFound
        self.calls.append((path, ref))
        if path not in self.files:
            raise NotFound(f"GET contents/{path}@{ref}: HTTP 404")
        return self.files[path].encode()


def test_workflow_triggers_are_read_once_a_week_and_remembered(tmp_path):
    from stackvitals.ci.store import DataStore
    from stackvitals.ci.triggers import pr_metadata_workflows
    wf, ci = ".github/workflows/check-pr-template.yml", ".github/workflows/ci.yml"
    store = DataStore(tmp_path)
    data = {"runs": [pr_run(1, 20, "failure", wf), pr_run(2, 20, "success", ci), {**pr_run(3, 20, "success", "dynamic/x"), "ev": "push"}]}
    api = FileAPI({wf: PIP_TRIGGERS, ci: "on:\n  pull_request:\n"})
    jobs = {wf: {"check-pr-template", "Check PR template"}}
    assert pr_metadata_workflows(api, store, data, "main", "2026-10-19") == jobs and len(api.calls) == 2
    assert pr_metadata_workflows(api, store, data, "main", "2026-10-22") == jobs and len(api.calls) == 2  # remembered
    gone = FileAPI({})
    assert pr_metadata_workflows(gone, store, data, "main", "2026-10-27") == jobs  # unreadable: keep what was known
    assert len(gone.calls) == 2


FILES = ["tests/test_calc.py", "src/test/java/com/acme/BarTest.java", "pkg/tests/test_db.py", "tests/test_db.py",
         "web/src/cart.test.ts", ".github/workflows/ci.yml"]
OWNERS = "* @lead\n/tests/ @qa\n/src/test/ @jvm-team\n.github/workflows/ @acme/ops\n"


def test_a_tests_file_is_found_from_its_id():
    from stackvitals.ci.owners import test_file
    assert test_file("tests/test_api.py::test_retry[a/b]", FILES + ["tests/test_api.py"]) == "tests/test_api.py"  # pytest ids carry the path
    assert test_file("tests.test_calc::test_add", FILES) == "tests/test_calc.py"  # JUnit classnames are dotted
    assert test_file("tests.test_calc.TestCalc::test_add", FILES) == "tests/test_calc.py"
    assert test_file("com.acme.BarTest::works", FILES) == "src/test/java/com/acme/BarTest.java"
    assert test_file("com.acme.BarTest$Inner::works", FILES) == "src/test/java/com/acme/BarTest.java"
    assert test_file("test_db::test_pool", FILES) is None  # two files fit: no guess
    assert test_file("Checkout cart::adds an item", FILES) is None and test_file("tests.test_calc::x", None) is None


def shown_result():
    return {"window_days": 30, "generated": "2026-10-19T12:00:00Z", "runs": 10, "rerun_share": 0.1, "infra_events": 0,
            "queue": {"median_s": 1, "p95_s": 2}, "minutes": {"linux": 1, "windows": 0, "macos": 0, "other": 0}, "has_test_reports": True,
            "jobs": [{"workflow": ".github/workflows/ci.yml", "job": "test", "runs": 10, "failures": 2, "flake_events": 2,
                      "flake_rate": 0.2, "rate_low": 0.05, "rate_high": 0.5, "state": "flaky", "last_flake": "2026-10-18T00:00:00Z",
                      "top_step": "Run tests", "retry_minutes": 3.0, "prs_affected": [], "evidence": [], "median_s": 60, "p95_s": 70,
                      "slower": None}],
            "tests": [{"id": "tests.test_calc::test_add", "suite": "junit", "workflow": ".github/workflows/ci.yml", "runs": 10,
                       "failures": 2, "flake_events": 2, "flake_rate": 0.2, "rate_low": 0.05, "rate_high": 0.5, "state": "flaky",
                       "last_flake": "2026-10-18T00:00:00Z", "message": "boom", "prs_affected": [], "evidence": []},
                      {"id": "Checkout cart::adds an item", "suite": "junit", "workflow": ".github/workflows/ci.yml", "runs": 10,
                       "failures": 2, "flake_events": 2, "flake_rate": 0.2, "rate_low": 0.05, "rate_high": 0.5, "state": "flaky",
                       "last_flake": "2026-10-18T00:00:00Z", "message": "boom", "prs_affected": [], "evidence": []}],
            "slow_tests": []}


def test_flaky_items_name_their_owners_from_the_test_file_else_the_workflow():
    from stackvitals.ci.owners import attach_owners
    from stackvitals.ci.report import render_html
    result = shown_result()
    attach_owners(result, {"text": OWNERS}, {"tests.test_calc::test_add": "tests/test_calc.py"})
    calc, cart = result["tests"]
    assert calc["owners"] == ["@qa"] and calc["owners_from"] == "tests/test_calc.py"
    assert cart["owners"] == ["@acme/ops"] and cart["owners_from"] == ".github/workflows/ci.yml"
    assert result["jobs"][0]["owners"] == ["@acme/ops"]
    page = render_html(result, "o/r")
    assert "<th>Owners</th>" in page and "@qa" in page and "CODEOWNERS for tests/test_calc.py" in page
    # Without a CODEOWNERS file there is no empty column.
    assert "<th>Owners</th>" not in render_html(shown_result(), "o/r")


class IssueAPI:
    repo = "o/r"

    def __init__(self):
        self.sent = []

    def _get(self, path, params=None):
        return []

    def send(self, method, path, body=None):
        self.sent.append((method, path, body))


def test_issues_name_owners_without_pinging_unless_mentions_are_turned_on():
    from stackvitals.ci.automation import alert_message, sync_issues
    from stackvitals.core.chat import text as plain
    from stackvitals.ci.owners import attach_owners
    result = shown_result()
    attach_owners(result, {"text": OWNERS}, {"tests.test_calc::test_add": "tests/test_calc.py"})
    quiet = IssueAPI()
    sync_issues(quiet, result)
    body = next(b["body"] for m, p, b in quiet.sent if b and "test_add" in b["title"])
    assert "`@qa`" in body and "tests/test_calc.py" in body
    loud = IssueAPI()
    sync_issues(loud, result, mention_owners=True)
    body = next(b["body"] for m, p, b in loud.sent if b and "test_add" in b["title"])
    assert "@qa" in body and "`@qa`" not in body
    text = plain(alert_message(["test tests.test_calc::test_add"], "o/r", result))
    assert "owners @qa" in text


class OwnersAPI(FileAPI):
    repo = "o/r"

    def __init__(self, files, errors):
        super().__init__(files)
        self.errors = errors

    def _get(self, path, params=None):
        self.calls.append((path, None))
        return {"errors": self.errors}


def test_owners_github_ignores_are_left_out_like_github_does(tmp_path):
    # Real data (home-assistant/core): 1,770 "Unknown owner" lines; GitHub shows no owners for those paths.
    from stackvitals.ci.owners import attach_owners, read_codeowners
    from stackvitals.ci.store import DataStore
    errors = [{"line": 2, "kind": "Unknown owner", "source": "/tests/ @qa\n",
               "message": "Unknown owner on line 2: make sure @qa exists and has write access to the repository"}]
    store = DataStore(tmp_path)
    api = OwnersAPI({".github/CODEOWNERS": OWNERS}, errors)
    co = read_codeowners(api, "main", store, "2026-10-19")
    assert co["text"] == OWNERS and co["unknown"] == {"@qa"}
    assert read_codeowners(api, "main", store, "2026-10-19") == co and len(api.calls) == 2  # once a day
    result = shown_result()
    attach_owners(result, co, {"tests.test_calc::test_add": "tests/test_calc.py"})
    assert result["tests"][0]["owners"] == ["@acme/ops"]  # no valid owner for the test file: its workflow's owners


def test_agents_see_the_owners_of_a_flaky_test():
    from stackvitals.ci.owners import attach_owners
    from stackvitals.mcp_server import _brief
    result = shown_result()
    attach_owners(result, {"text": OWNERS}, {"tests.test_calc::test_add": "tests/test_calc.py"})
    assert _brief(result["tests"][0], "test")["owners"] == ["@qa"]
    assert "owners" not in _brief(shown_result()["tests"][0], "test")
