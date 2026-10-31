"""Fixes from the Phase 15 whole-phase review."""
import json
from datetime import timedelta

from ci_fake import T0, iso
from stackvitals.ci.feedback import (_detail, classify_run, failing_section, failure_summary, outside_signature,
                                     render_comment, same_error)

STAMP = "2026-10-15T17:50:07.0000000Z "


def _log(*lines):
    return "\n".join(STAMP + x for x in lines)


def test_the_failing_step_starts_at_its_group_line_in_timestamped_logs():
    log = _log("##[group]Run npm ci", "npm WARN retry socket hang up", "added 900 packages", "##[endgroup]",
               "##[group]Run npm run build", "src/a.ts(3,1): error TS2322: Type 'string' is not assignable",
               "##[error]Process completed with exit code 2.")
    section = failing_section(log)
    assert "socket hang up" not in section and "TS2322" in section
    assert outside_signature(log) is None


def test_boilerplate_summary_lines_never_make_two_errors_the_same():
    mine = _log("##[group]Run npm test", "FAIL src/parser.test.js", "  ● parses dates › rejects Feb 30",
                "Test Suites: 1 failed, 40 passed, 41 total", "Tests:       1 failed, 300 passed, 301 total",
                "npm ERR! Failed at the foo@1.2.3 test script.", "##[error]Process completed with exit code 1.")
    theirs = _log("##[group]Run npm test", "FAIL src/network.test.js", "  ● fetches › retries on 503",
                  "Test Suites: 1 failed, 40 passed, 41 total", "Tests:       2 failed, 299 passed, 301 total",
                  "npm ERR! Failed at the foo@1.2.2 test script.", "##[error]Process completed with exit code 1.")
    assert not same_error(mine, theirs)
    assert same_error(mine, mine.replace("17:50", "18:10"))


WF = ".github/workflows/ci.yml"


def _pr_details(log, step="Build"):
    st = iso(T0 + timedelta(days=29))
    data = {"runs": [{"t": "run", "id": 9, "att": 1, "path": WF, "wfn": "CI", "ev": "pull_request", "br": "x",
                      "tree": "t", "pr": [5], "c": "failure", "cr": st}],
            "jobs": [{"t": "job", "run": 9, "att": 1, "id": 91, "n": "build", "c": "failure", "cr": st, "st": st, "en": st,
                      "lb": [], "steps": [[1, step, "failure"]]}]}
    return classify_run(data, {"default_branch": "main", "jobs": [], "tests": [], "pr_edit_workflows": [WF]}, 9,
                        logs={91: log})[0]["verdict"]


def test_pr_details_needs_words_about_the_pr_not_code_errors_that_share_them():
    assert _pr_details(_log("##[group]Run make", "Error: Template rendering failed: missing key", "##[error]exit 1")) == "new"
    assert _pr_details(_log("##[group]Run npx playwright test", "Error: expected checkbox not checked",
                            "1 failed", "##[error]exit 1"), step="Run tests") == "new"
    assert _pr_details(_log("##[group]Run check", "##[error]AI assistance section incomplete: the checkbox \"I read every "
                            "line\" is not checked")) == "PR details"
    assert _pr_details(_log("##[group]Run lint", "##[error]No release type found in pull request title")) == "PR details"


def test_untrusted_text_in_the_comment_neither_pings_people_nor_links_out():
    items = [{"kind": "test", "name": "a`b @team", "verdict": "new",
              "detail": 'no earlier flakes: likely from this change (fails with "ping @octocat see https://evil.example/x")'}]
    body = render_comment(items, "o/r")
    assert "@octocat" not in body and "https://evil.example" not in body and "@team" not in body
    assert "`a'b @​team`" in body


def test_a_job_fixed_with_no_flakes_left_says_so_plainly():
    text = _detail({"state": "fixed", "flake_events": 0, "runs": 30, "flake_steps": []}, "flaked before", step="Test")
    assert "0 times" not in text and "recent fix" in text


def test_the_agent_summary_fits_the_verdicts_it_sums_up():
    assert "nothing failed" in failure_summary([])
    assert "outside" in failure_summary([{"verdict": "outside failure"}])
    assert "already" in failure_summary([{"verdict": "already failing"}, {"verdict": "outside failure"}])
    assert "maybe yours or flaked before" in failure_summary([{"verdict": "new"}, {"verdict": "known flaky"}])


def test_gitlab_runs_take_the_pipelines_own_result_and_merge_request_number():
    from stackvitals.ci.gitlab import records
    base = {"id": 1, "sha": "s", "created_at": "2026-10-20T10:00:00Z", "source": "merge_request_event",
            "ref": "refs/merge-requests/42/head"}
    run = records({**base, "status": "failed"}, [])[0]
    assert run["c"] == "failure" and run["pr"] == [42]
    job = {"id": 5, "name": "test", "status": "success", "created_at": "2026-10-20T10:00:01Z", "stage": "test"}
    assert records({**base, "status": "canceled"}, [job])[0]["c"] == "cancelled"
    assert records({**base, "status": "success"}, [job])[0]["c"] == "success"


def test_a_go_parent_test_failing_on_its_own_is_kept():
    from stackvitals.ci.testreports import parse_report
    lines = [{"Action": "run", "Package": "p", "Test": "TestA"}, {"Action": "run", "Package": "p", "Test": "TestA/ok"},
             {"Action": "pass", "Package": "p", "Test": "TestA/ok", "Elapsed": 0.1},
             {"Action": "output", "Package": "p", "Test": "TestA", "Output": "    a_test.go:9: cleanup failed\n"},
             {"Action": "fail", "Package": "p", "Test": "TestA", "Elapsed": 0.2}]
    got = parse_report("go.json", "\n".join(json.dumps(x) for x in lines).encode())
    assert [f[0] for f in got["failed"]] == ["p::TestA"]


def test_burn_in_finds_jest_folders_and_rspec_files():
    from stackvitals.ci.burnin import TEST_FILE
    assert TEST_FILE.search("src/__tests__/cart.ts") and TEST_FILE.search("spec/models/user_spec.rb")
    assert not TEST_FILE.search("src/cart.ts")


def test_otel_spans_without_a_start_take_their_parents():
    from stackvitals.core.export import otel_traces
    data = {"runs": [{"id": 1, "att": 1, "path": WF, "wfn": "CI", "c": "success", "cr": "2026-10-20T10:00:00Z",
                      "up": "2026-10-20T10:05:00Z"}],
            "jobs": [{"run": 1, "att": 1, "id": 2, "n": "build", "c": "success", "steps": [[1, "Run", "success"]]}]}
    spans = otel_traces("o/r", data)["resourceSpans"][0]["scopeSpans"][0]["spans"]
    assert all(s["startTimeUnixNano"] != "0" and s["endTimeUnixNano"] != "0" for s in spans)


def test_the_models_views_ride_in_the_comment_and_come_back_next_run():
    from stackvitals.ci.feedback import remembered
    view = {"model": "m", "caused_by_change": "no", "cause": "network", "why": "a --> b <!-- c"}
    items = [{"kind": "job", "job_id": 7, "name": "CI / t", "verdict": "new", "detail": "d", "model": view}]
    body = render_comment(items, "o/r")
    assert remembered(body) == {"7": view}
    assert body.count("-->") == 2  # the marker and the note: the model's own text can't close it
    assert remembered("no note") == {} and remembered("<!-- stackvitals:triage {bad -->") == {}


def test_a_fork_pull_request_from_its_main_is_still_compared_with_the_default_branch():
    from stackvitals.ci.feedback import failed_on_default
    st = iso(T0 + timedelta(days=29))
    main_run = {"t": "run", "id": 1, "att": 1, "path": WF, "ev": "push", "br": "main", "c": "failure", "cr": st}
    pr_run = {**main_run, "id": 9, "ev": "pull_request", "cr": iso(T0 + timedelta(days=29, hours=2))}
    job = lambda jid, rid, t: {"t": "job", "run": rid, "att": 1, "id": jid, "n": "build", "c": "failure", "cr": t,
                               "st": t, "en": t, "lb": [], "steps": [[1, "Build", "failure"]]}
    data = {"runs": [main_run, pr_run], "jobs": [job(11, 1, st), job(91, 9, pr_run["cr"])]}
    assert failed_on_default(data, pr_run, data["jobs"][1], "Build", "main")["run"] == 1
