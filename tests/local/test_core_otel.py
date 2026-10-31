from stackvitals.core.export import otel_traces

DATA = {"runs": [{"t": "run", "id": 9, "att": 1, "path": ".github/workflows/ci.yml", "wfn": "CI", "ev": "pull_request", "br": "fix",
                  "sha": "abc", "tree": "t", "pr": [5], "c": "failure", "cr": "2026-10-20T10:00:00Z",
                  "st": "2026-10-20T10:00:05Z", "up": "2026-10-20T10:06:00Z"}],
        "jobs": [{"t": "job", "run": 9, "att": 1, "id": 91, "n": "test", "c": "failure", "cr": "2026-10-20T10:00:05Z",
                  "st": "2026-10-20T10:00:10Z", "en": "2026-10-20T10:05:00Z", "lb": ["ubuntu-latest"],
                  "steps": [[1, "Set up job", "success", "2026-10-20T10:00:10Z", "2026-10-20T10:00:20Z"],
                            [2, "Run tests", "failure", "2026-10-20T10:00:20Z", "2026-10-20T10:05:00Z"]]}],
        "tests": [{"t": "tests", "run": 9, "att": 1, "art": 1, "name": "results", "total": 3, "skipped": 0,
                   "failed": [["t::a", "fp", "assert 3 == 4"]], "flaky": ["t::b"], "slow": [["t::a", 1200]]}]}


def _attrs(span):
    return {a["key"]: next(iter(a["value"].values())) for a in span["attributes"]}


def test_each_run_attempt_is_a_trace_with_job_and_step_spans():
    out = otel_traces("o/r", DATA)
    spans = out["resourceSpans"][0]["scopeSpans"][0]["spans"]
    run, job, setup, tests = spans
    assert {s["traceId"] for s in spans} == {run["traceId"]} and len(run["traceId"]) == 32 and len(run["spanId"]) == 16
    assert "parentSpanId" not in run and job["parentSpanId"] == run["spanId"] and tests["parentSpanId"] == job["spanId"]
    assert _attrs(run)["cicd.pipeline.name"] == "CI" and _attrs(run)["vcs.change.id"] == "5"
    assert run["status"]["code"] == 2 and setup["status"]["code"] == 1
    assert int(job["endTimeUnixNano"]) - int(job["startTimeUnixNano"]) == 290 * 10 ** 9
    assert _attrs(job)["cicd.pipeline.task.name"] == "test" and tests["name"] == "Run tests"
    events = {e["name"]: {a["key"]: a["value"]["stringValue"] for a in e["attributes"]} for e in run["events"]}
    assert events["test.failed"]["test.case.name"] == "t::a" and events["test.flaky"]["test.case.name"] == "t::b"


def test_the_same_data_gives_the_same_ids():
    assert otel_traces("o/r", DATA) == otel_traces("o/r", DATA)
