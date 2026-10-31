"""CI depth: skipped and new tests named per report, daily duration trends, test shards split by recorded time, and a
copyable investigation prompt per failure group."""
from datetime import timedelta

from ci_fake import T0, FakeGitHub, Run, iso, job
from stackvitals.ci.analyze import analyze
from stackvitals.ci.collect import collect
from stackvitals.ci.store import DataStore
from stackvitals.ci.testreports import parse_report
from test_ci_analyze_tests import NOW, rep, trun
from test_ci_artifacts import art_api_for, junit


def test_reports_name_skipped_tests_and_time_every_test():
    xml = b'<testsuite><testcase classname="t" name="a" time="1.5"/><testcase classname="t" name="b" time="0"><skipped/></testcase></testsuite>'
    r = parse_report("r.xml", xml)
    assert r["sk"] == ["t::b"] and r["all"] == [["t::a", 1500], ["t::b", 0]]


def test_new_tests_are_named_once_a_first_collect_has_set_the_baseline(tmp_path):
    arts = {1: [(101, "test-results", junit(("a", 1, None), ("b", 1, None)), T0 + timedelta(minutes=2))]}
    fake = FakeGitHub([Run(1, T0, [("success", [job(11, "test", "success", T0, 60)])])], artifacts=arts)
    store = DataStore(tmp_path)
    collect(art_api_for(fake), store, T0 + timedelta(hours=1), days=5, tests=True)
    assert all(not r.get("new") for r in store.load()["tests"])
    later = T0 + timedelta(hours=2)
    fake.runs[2] = Run(2, later, [("success", [job(21, "test", "success", later, 60)])])
    arts[2] = [(201, "test-results", junit(("a", 1, None), ("b", 1, None), ("c", 1, "boom")), later + timedelta(minutes=2))]
    collect(art_api_for(fake), store, T0 + timedelta(hours=3), days=5, tests=True)
    reports = store.load()["tests"]
    assert [r["new"] for r in reports if r.get("new")] == [["t::c"]]
    # Every test's time is read for the baseline and the shards, never stored per report.
    assert all("all" not in r for r in reports)


def test_new_tests_list_what_was_added_recently_and_how_it_has_done_since():
    runs = [trun(k, 1, 20 + k, "failure" if k == 2 else "success", tree=f"x{k}") for k in range(4)]
    tests = [rep(100, 0, 1), {**rep(101, 1, 1), "new": ["t::n"]}, rep(102, 2, 1, failed=["t::n"]), rep(103, 3, 1)]
    out = analyze({"runs": runs, "jobs": [], "tests": tests}, NOW, default_branch="main")
    assert [(t["id"], t["runs"], t["failures"]) for t in out["new_tests"]] == [("t::n", 3, 1)]
    assert out["new_tests"][0]["first"][:10] == iso(T0 + timedelta(days=21))[:10]


def test_skipped_tests_say_since_when_and_only_reports_with_a_skip_list_count():
    runs = [trun(k, 1, k, "success", tree=f"x{k}") for k in range(0, 30, 3)]
    # The first report predates skip lists: it proves nothing about t::old.
    tests = [rep(100, 0, 1)] + [{**rep(100 + k, k, 1), "sk": ["t::old"] + (["t::new"] if k >= 24 else [])}
                                for k in range(3, 30, 3)]
    out = analyze({"runs": runs, "jobs": [], "tests": tests}, NOW, default_branch="main")
    sk = {t["id"]: t for t in out["skipped_tests"]}
    assert sk["t::old"]["since"][:10] == iso(T0 + timedelta(days=3))[:10] and sk["t::old"]["days"] == 27
    assert sk["t::new"]["new"] and not sk["t::old"]["new"]


def test_jobs_and_slow_tests_carry_a_daily_duration_trend():
    runs, jobs, tests = [], [], []
    for k in range(5):
        start = T0 + timedelta(days=20 + k)
        runs.append(trun(k, 1, 20 + k, "success", tree=f"x{k}"))
        jobs.append({"t": "job", "run": k, "att": 1, "n": "test", "c": "success", "st": iso(start),
                     "en": iso(start + timedelta(seconds=60 * (k + 1)))})
        tests.append(rep(100 + k, k, 1, slow=[["t::s", 1000 * (k + 1)]]))
    out = analyze({"runs": runs, "jobs": jobs, "tests": tests}, NOW, default_branch="main")
    assert [v for _, v in out["jobs"][0]["trend"]] == [60, 120, 180, 240, 300]
    assert [v for _, v in out["slow_tests"][0]["trend"]] == [1000, 2000, 3000, 4000, 5000]


def test_shards_split_test_files_by_recorded_time_and_stay_balanced():
    from stackvitals.ci.shards import split
    times = [["tests/a.py::t1", 60000], ["tests/a.py::t2", 30000], ["tests/b.py::t", 50000], ["tests/c.py::t", 20000],
             ["tests/d.py::t", 10000]]
    out = split(times, 2)
    assert sorted(f for s in out for f in s["files"]) == ["tests/a.py", "tests/b.py", "tests/c.py", "tests/d.py"]
    assert sorted(s["ms"] for s in out) == [80000, 90000]
    # Files with no recorded time still land somewhere, on the lightest shard.
    assert any("tests/new.py" in s["files"] for s in split(times, 2, extra=["tests/new.py"]))


def test_a_failure_group_gives_a_prompt_an_agent_can_act_on_without_secrets():
    from stackvitals.ci.investigate import prompt
    group = {"id": "g1", "type": "TimeoutError", "where": "tests/test_db.py:41", "message": "timed out after 30s @alice",
             "failures": 7, "tests": 2, "runs": 5, "first": "2026-10-01T10:00:00Z", "last": "2026-10-20T10:00:00Z",
             "top_tests": ["tests/test_db.py::test_pool"], "examples": [{"run": 9, "att": 1, "test": "tests/test_db.py::test_pool"}]}
    text = prompt("o/r", group, [{"id": "tests/test_db.py::test_pool", "state": "flaky", "flake_rate": 0.2}])
    assert "o/r" in text and "TimeoutError" in text and "tests/test_db.py:41" in text and "7 failures" in text
    assert "https://github.com/o/r/actions/runs/9/attempts/1" in text and "flaky" in text
    assert "@alice" not in text


def test_the_shards_command_reads_local_reports_and_prints_one_shard_for_a_matrix(tmp_path, capsys):
    from stackvitals.ci.cli import main
    (tmp_path / "a.xml").write_bytes(b'<testsuite><testcase classname="tests.test_a" name="x" time="9"/>'
                                     b'<testcase classname="tests.test_b.TestB" name="y" time="5"/>'
                                     b'<testcase classname="tests.test_c" name="z" time="4"/></testsuite>')
    assert main(["shards", "--reports", str(tmp_path / "*.xml"), "--n", "2", "--index", "2", "--py-paths"], tok="") == 0
    assert capsys.readouterr().out.split() == ["tests/test_b.py", "tests/test_c.py"]
    assert main(["shards", "--reports", str(tmp_path / "*.xml"), "--n", "2", "--index", "3"], tok="") == 2


def test_shards_from_a_repo_use_the_newest_green_run_that_kept_test_reports():
    from stackvitals.ci.shards import latest_times
    zipped = junit(("a", 2, None), ("b", 3, None))

    class Api:
        repo = "o/r"

        def _get(self, path, params=None):
            assert params["branch"] == "main" and params["status"] == "success"
            return {"workflow_runs": [{"id": 2, "html_url": "u2"}, {"id": 1, "html_url": "u1"}]}

        def artifacts(self, run_id):
            return [{"id": 9, "name": "coverage"}] if run_id == 2 else [{"id": 10, "name": "test-results", "size_in_bytes": 10}]

        def download(self, art_id):
            assert art_id == 10
            return zipped

    times, run = latest_times(Api(), "main")
    assert run["id"] == 1 and sorted(times) == [["t::a", 2000], ["t::b", 3000]]


def test_the_published_data_carries_a_prompt_for_the_biggest_failure_groups(tmp_path):
    import json
    from stackvitals.ci.action import write_outputs
    groups = [{"id": f"g{k}", "type": "E", "where": "x.py:1", "message": "m", "failures": 1, "tests": 1, "runs": 1,
               "first": "2026-10-01T00:00:00Z", "last": "2026-10-02T00:00:00Z", "top_tests": [], "examples": []} for k in range(12)]
    result = analyze({"runs": [], "jobs": [], "tests": []}, NOW)
    result["failure_groups"] = groups
    write_outputs(tmp_path, result, "o/r")
    data = json.loads((tmp_path / "docs" / "data.json").read_text(encoding="utf-8"))
    prompts = [g.get("prompt") for g in data["failure_groups"]]
    assert all(p and "o/r" in p for p in prompts[:10]) and prompts[10:] == [None, None]


def test_the_printable_page_and_the_text_report_list_new_and_skipped_tests():
    from stackvitals.ci.report import render_html, render_text
    result = analyze({"runs": [], "jobs": [], "tests": []}, NOW)
    result["new_tests"] = [{"id": "t::<n>", "suite": "s", "first": "2026-10-15T00:00:00Z", "runs": 3, "failures": 1,
                            "flake_events": 0, "state": "broken"}]
    result["skipped_tests"] = [{"id": "t::old", "suite": "s", "since": "2026-09-01T00:00:00Z", "days": 50, "new": False}]
    result["runs"] = 1
    page = render_html(result, "o/r")
    assert "New tests" in page and "t::&lt;n&gt;" in page and "Skipped" in page and "50 days" in page
    text = render_text(result, "o/r")
    assert "New tests" in text and "t::old" in text


def test_a_test_skipped_in_several_matrix_jobs_is_one_row_with_its_job_count():
    runs = [trun(k, 1, 20 + k, "success", tree=f"x{k}") for k in range(2)]
    tests = [{**rep(100 + k, k, 1, name=name), "sk": ["t::s"]} for k in range(2) for name in ("results-linux", "results-windows")]
    for i, r in enumerate(tests):
        r["art"] = 200 + i
    out = analyze({"runs": runs, "jobs": [], "tests": tests}, NOW, default_branch="main")
    assert [(t["id"], t["suites"]) for t in out["skipped_tests"]] == [("t::s", 2)]


def test_the_prompt_names_each_run_once_and_the_error_type_once():
    from stackvitals.ci.investigate import prompt
    group = {"id": "g", "type": "ValueError", "where": "x.py:f", "message": "ValueError: bad payload", "failures": 4, "tests": 2,
             "runs": 1, "first": "2026-10-13T00:00:00Z", "last": "2026-10-20T00:00:00Z", "top_tests": ["t::a", "t::b"],
             "examples": [{"run": 9, "att": 1, "test": "t::a"}, {"run": 9, "att": 1, "test": "t::b"}, {"run": 9, "att": 1, "test": "t::a"}]}
    text = prompt("o/r", group, [])
    assert "ValueError: ValueError" not in text and "ValueError: bad payload" in text
    assert text.count("actions/runs/9/attempts/1") == 1 and "(t::a, t::b)" in text
