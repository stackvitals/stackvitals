import json
import os
import subprocess
import sys

from stackvitals.ci.automation import quarantine_list
from stackvitals.ci.quarantine_runtime import runtime_args


def test_each_runner_gets_flags_that_leave_quarantined_tests_out():
    ids = {"web/a.test.js::adds numbers", "pkg/x::TestFlaky", "pkg/x::TestOther/sub", "tests.test_a::test_slow"}
    assert runtime_args(ids, "pytest") == ["-p", "stackvitals.ci.quarantine_runtime"]
    flag, pattern = runtime_args(ids, "jest")
    assert flag == "--testNamePattern" and "adds\ numbers" in pattern and pattern.startswith("^(?!")
    assert runtime_args(ids, "vitest")[0] == "-t"
    assert runtime_args(ids, "go") == ["-skip", "^(?:TestFlaky)$"]  # subtests aren't listed: a parent would be skipped too
    assert runtime_args(set(), "jest") == []


def test_pytest_runs_a_quarantined_failing_test_without_failing_the_suite(tmp_path):
    (tmp_path / "test_demo.py").write_text("def test_flaky():\n    assert False\n\ndef test_fine():\n    assert True\n")
    listing = tmp_path / "q.json"
    listing.write_text(json.dumps(["tests.test_demo::test_flaky"]))
    env = {**os.environ, "STACKVITALS_QUARANTINE": str(listing), "PYTHONPATH": os.pathsep.join(sys.path)}
    run = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "stackvitals.ci.quarantine_runtime", "-p", "no:cacheprovider",
                          str(tmp_path)], capture_output=True, text=True, env=env, cwd=tmp_path)
    assert run.returncode == 0 and "1 xfailed" in run.stdout and "1 passed" in run.stdout
    listing.write_text("not json")
    run = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "stackvitals.ci.quarantine_runtime", "-p", "no:cacheprovider",
                          str(tmp_path)], capture_output=True, text=True, env=env, cwd=tmp_path)
    assert run.returncode == 1  # an unreadable list quarantines nothing


def test_a_broken_test_is_never_quarantined_automatically():
    result = {"tests": [{"id": "a::flaky", "state": "flaky", "flake_events": 4},
                        {"id": "a::broken", "state": "broken", "flake_events": 9}]}
    assert quarantine_list(result) == ["a::flaky"]


def test_print_for_pytest_writes_the_list_the_plugin_reads(tmp_path, monkeypatch, capsys):
    from stackvitals.ci import cli
    src = tmp_path / "list.json"
    src.write_text('["tests/test_a.py::test_flaky"]', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert cli.main(["quarantine", "--list", str(src), "--print", "pytest"]) == 0
    assert capsys.readouterr().out.split() == ["-p", "stackvitals.ci.quarantine_runtime"]
    assert (tmp_path / ".stackvitals-quarantine.json").read_text(encoding="utf-8").strip() == '["tests/test_a.py::test_flaky"]'


def test_the_name_pattern_skips_a_quarantined_test_inside_describe_blocks_too():
    import re
    _flag, pattern = runtime_args({"web/a.test.js::adds numbers"}, "jest")
    keep = lambda name: re.match(pattern, name) is not None  # noqa: E731
    assert not keep("adds numbers") and not keep("math suite adds numbers")
    assert keep("adds numbers twice") and keep("subtracts")


def test_print_gives_one_argument_per_line_for_a_shell_array(tmp_path, capsys):
    from stackvitals.ci import cli
    src = tmp_path / "list.json"
    src.write_text('["web/a.test.js::adds numbers"]', encoding="utf-8")
    assert cli.main(["quarantine", "--list", str(src), "--print", "jest"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "--testNamePattern" and lines[1] == runtime_args({"web/a.test.js::adds numbers"}, "jest")[1]


def test_pytest_matching_needs_the_same_file_and_class_not_a_similar_one():
    from stackvitals.ci.quarantine_runtime import _matches
    assert _matches("tests.test_api::test_get", "tests/test_api.py::test_get", "test_get")
    assert not _matches("tests.test_api::test_get", "tests/test_api_v2.py::test_get", "test_get")
    assert _matches("tests.test_a.TestCls::test_x", "tests/test_a.py::TestCls::test_x", "test_x")
    assert not _matches("tests.test_a.TestCls::test_x", "tests/test_b.py::TestCls::test_x", "test_x")
    assert _matches("pkg.tests.test_a::test_x", "tests/test_a.py::test_x", "test_x")  # rootdir differs
    assert _matches("tests/test_a.py::test_x", "tests/test_a.py::test_x", "test_x")
