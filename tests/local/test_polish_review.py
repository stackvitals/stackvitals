"""Fixes from the fresh-context review of the polish branch."""
from datetime import timedelta

import httpx
from ci_fake import T0, iso
from test_polish_m2 import OWNERS, PIP_TRIGGERS, FileAPI, pr_job, pr_run, shown_result

NOW = T0 + timedelta(days=30)

SAFE_TO_TEST = """on:
  pull_request_target:
    types: [opened, synchronize, reopened, labeled]
jobs:
  tests:
    if: github.event.action != 'labeled' || github.event.label.name == 'safe to test'
    runs-on: ubuntu-latest
    steps:
      - run: pytest
"""
MIXED = """on:
  pull_request:
    types: [opened, synchronize, edited]
jobs:
  title:
    name: PR title
    runs-on: ubuntu-latest
    steps:
      - uses: amannn/action-semantic-pull-request@v5
  test:
    runs-on: ubuntu-latest
    steps:
      - run: pytest
"""


def test_only_jobs_that_read_the_pr_text_lose_same_code_flips():
    from stackvitals.ci.triggers import metadata_jobs
    assert metadata_jobs(PIP_TRIGGERS) == {"check-pr-template", "Check PR template"}  # real file: pypa/pip
    step_gate = "on:\n  pull_request:\n    types: [labeled]\njobs:\n  t:\n    steps:\n      - if: contains(github.event.pull_request.labels.*.name, 'x')\n        run: echo ${{ github.event.pull_request.title }}\n"
    assert metadata_jobs(step_gate) == {"t"}  # a step's own `- if:` gates only that line, not the step's run
    assert metadata_jobs(SAFE_TO_TEST) == set()  # the label only gates the run; failures come from the tests
    assert metadata_jobs(MIXED) == {"title", "PR title"}
    assert metadata_jobs("on: [push]\njobs:\n  a:\n    steps:\n      - run: echo ${{ github.event.pull_request.title }}\n") == set()


def test_flips_are_skipped_per_job_and_never_for_test_reports():
    from stackvitals.ci.analyze import analyze
    wf = ".github/workflows/ci.yml"
    runs = [pr_run(1, 20, "failure", wf), pr_run(2, 20, "success", wf)]
    jobs = [pr_job(11, 1, 20, "failure", "PR title"), pr_job(21, 2, 20, "success", "PR title"),
            pr_job(12, 1, 20, "failure", "test"), pr_job(22, 2, 20, "success", "test")]
    report = lambda rid, failed: {"t": "tests", "run": rid, "att": 1, "art": rid, "name": "junit", "total": 3, "skipped": 0,  # noqa: E731
                                  "failed": failed, "flaky": [], "slow": []}
    data = {"runs": runs, "jobs": jobs, "tests": [report(1, [["t::a", "fp", "boom"]]), report(2, [])]}
    result = analyze(data, NOW, default_branch="main", pr_metadata={wf: {"title", "PR title"}})
    flakes = {j["job"]: j["flake_events"] for j in result["jobs"]}
    assert flakes == {"PR title": 0, "test": 1} and result["tests"][0]["flake_events"] == 1


def test_a_dropped_connection_reading_a_file_is_an_api_error_not_a_crash():
    from stackvitals.ci.api import ActionsAPI, APIError, NotFound
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ReadTimeout("timed out")
    api = ActionsAPI("t", "o/r", client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    try:
        api.file(".github/CODEOWNERS", "main")
        raise AssertionError("expected APIError")
    except NotFound:
        raise AssertionError("a network error is not a missing file")
    except APIError:
        pass
    assert len(calls) == 3


def test_codeowners_moves_on_only_when_a_file_is_missing(tmp_path):
    from stackvitals.ci.api import APIError, NotFound
    from stackvitals.ci.owners import read_codeowners
    from stackvitals.ci.store import DataStore

    class Flaky(FileAPI):
        repo = "o/r"

        def file(self, path, ref, repo=None):
            self.calls.append((path, ref))
            if path == ".github/CODEOWNERS":
                raise APIError("GET contents/.github/CODEOWNERS@main: HTTP 502")
            if path == "CODEOWNERS":
                return b"* @old-root-file\n"
            raise NotFound(path)

        def _get(self, path, params=None):
            return {"errors": []}
    store = DataStore(tmp_path)
    store.save_state({"codeowners": {"checked": "2026-10-18", "text": OWNERS, "unknown": [], "skip": []}})
    co = read_codeowners(Flaky({}), "main", store, "2026-10-19")
    assert co["text"] == OWNERS  # yesterday's answer, not the root file GitHub ignores
    assert store.state()["codeowners"]["checked"] == "2026-10-18"  # not saved: the next run tries again


def test_monorepo_test_paths_are_checked_against_the_repos_files():
    from stackvitals.ci.owners import test_file
    files = ["packages/web/src/calc.test.ts", "backend/test_api.py", "tests/test_api.py", "web/src/calc.test.ts"]
    assert test_file("backend/test_api.py::x", files) == "backend/test_api.py"
    assert test_file("test_api.py::x", files) is None  # two files end like this: no guess
    assert test_file("src/calc.test.ts::adds", ["packages/web/src/calc.test.ts"]) == "packages/web/src/calc.test.ts"
    assert test_file("github.com/acme/repo/pkg::TestX", files) is None and test_file("tests/test_api.py::x", None) is None


def test_a_crafted_path_cannot_break_out_of_the_code_format_in_issues():
    from stackvitals.ci.owners import owners_line
    line = owners_line({"owners": ["@qa"], "owners_from": "a` @acme/everyone `b/x.py"})
    assert "@acme/everyone" not in line.replace("`a @acme/everyone b/x.py`", "")


def test_byte_order_marks_and_other_list_layouts_are_read():
    from stackvitals import codeowners
    from stackvitals.ci.triggers import pr_metadata_triggered
    assert codeowners.owners_for("a.py", codeowners.parse("\ufeff* @a\n")) == ["@a"]
    assert pr_metadata_triggered("\ufeffon:\n  pull_request:\n    types:\n    - edited\n")
    assert pr_metadata_triggered("on:\n  pull_request :\n    types: [labeled]\n")


def test_lines_github_skips_as_invalid_never_decide_owners(tmp_path):
    from stackvitals.ci.owners import attach_owners
    co = {"text": "* @lead\n/tests/[ab]*.py @qa\n", "unknown": set(), "skip": {2}}
    result = shown_result()
    attach_owners(result, co, {"tests.test_calc::test_add": "tests/test_calc.py"})
    assert result["tests"][0]["owners"] == ["@lead"]


def test_history_pages_are_capped():
    from stackvitals.ci.analyze import MAX_HISTORY, analyze
    runs, jobs = [], []
    for k in range(MAX_HISTORY + 5):
        rid = 1000 + k
        runs += [{**pr_run(rid, 20, "failure", ".github/workflows/ci.yml", tree=f"t{k}"), "ev": "push", "br": "main"},
                 {**pr_run(rid, 20, "success", ".github/workflows/ci.yml", tree=f"t{k}"), "att": 2, "ev": "push", "br": "main"}]
        jobs += [pr_job(rid * 10, rid, 20, "failure", f"job {k}"), {**pr_job(rid * 10 + 1, rid, 20, "success", f"job {k}"), "att": 2}]
    result = analyze({"runs": runs, "jobs": jobs}, NOW, default_branch="main")
    assert len(result["history"]["jobs"]) == MAX_HISTORY


_ = iso
