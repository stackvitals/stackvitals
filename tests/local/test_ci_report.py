from stackvitals.ci.report import render_html, render_markdown, render_text

RESULT = {
    "window_days": 30, "generated": "2026-10-16T12:00:00Z", "runs": 120, "rerun_share": 0.1, "infra_events": 1,
    "queue": {"median_s": 12, "p95_s": 90}, "minutes": {"linux": 900, "windows": 0, "macos": 40, "other": 0},
    "jobs": [
        {"workflow": ".github/workflows/ci.yml", "job": "test (3.12) <script>alert(1)</script>", "runs": 80,
         "failures": 9, "flake_events": 6, "flake_rate": 0.075, "rate_low": 0.03, "rate_high": 0.15, "state": "flaky",
         "last_flake": "2026-10-15T09:00:00Z", "top_step": "Install dependencies", "retry_minutes": 42.5,
         "prs_affected": [3, 4], "median_s": 400, "p95_s": 700, "slower": None},
        {"workflow": ".github/workflows/ci.yml", "job": "lint", "runs": 80, "failures": 5, "flake_events": 0,
         "flake_rate": 0, "rate_low": 0, "rate_high": 0.05, "state": "broken", "last_flake": None, "top_step": None,
         "retry_minutes": 0, "prs_affected": [], "median_s": 60, "p95_s": 80, "slower": None},
        {"workflow": ".github/workflows/ci.yml", "job": "docs", "runs": 40, "failures": 0, "flake_events": 0,
         "flake_rate": 0, "rate_low": 0, "rate_high": 0.09, "state": "ok", "last_flake": None, "top_step": None,
         "retry_minutes": 0, "prs_affected": [], "median_s": 300, "p95_s": 320,
         "slower": {"before_s": 150, "after_s": 300, "pct": 100}}]}


def test_text_report_leads_with_what_to_act_on():
    text = render_text(RESULT, "octo/app")
    assert text.index("Flaky") < text.index("Slowest")
    assert "6 flakes in 80 runs" in text and "Install dependencies" in text and "42 min lost" in text
    assert "lint" in text and "keeps failing" in text and "docs" in text and "2x slower" in text


def test_an_empty_history_says_so_plainly():
    empty = {**RESULT, "runs": 0, "jobs": []}
    assert "No completed CI runs" in render_text(empty, "octo/app")
    assert "No completed CI runs" in render_html(empty, "octo/app")


# Real run (ruff, 2026-10-16): a dozen jobs with one flake each buried the real flaky ones.
def test_many_one_off_flakes_are_collapsed_into_one_line():
    one = {**RESULT["jobs"][2], "state": "suspect", "flake_events": 1, "slower": None, "median_s": None}
    many = {**RESULT, "jobs": [RESULT["jobs"][0]] + [{**one, "job": f"bench {i}"} for i in range(9)]}
    text = render_text(many, "octo/app")
    assert "bench 0" in text and "bench 8" not in text and "4 more jobs with one flake each" in text


TESTS = {**RESULT, "has_test_reports": True, "test_outages": 0,
         "tests": [{"id": "tests/test_api.py::test_retry[<b>]", "suite": "test-results", "runs": 60, "failures": 4,
                    "flake_events": 3, "flake_rate": 0.05, "rate_low": 0.02, "rate_high": 0.14, "state": "flaky",
                    "last_flake": "2026-10-15T00:00:00Z", "message": "AssertionError: assert 502 == 200", "prs_affected": [9]},
                   {"id": "tests/test_db.py::test_pool", "suite": "test-results", "runs": 60, "failures": 3,
                    "flake_events": 0, "flake_rate": 0, "rate_low": 0, "rate_high": 0.06, "state": "broken",
                    "last_flake": None, "message": "TimeoutError", "prs_affected": []}],
         "slow_tests": [{"id": "tests/test_e2e.py::test_checkout", "median_ms": 42000, "p95_ms": 61000, "samples": 30,
                         "slower": {"before_ms": 20000, "after_ms": 42000, "pct": 110}}]}


def test_flaky_tests_come_first_with_their_failure_message():
    text = render_text(TESTS, "octo/app")
    assert text.index("Flaky tests") < text.index("Flaky jobs")
    assert "test_retry[<b>]: 3 flakes in 60 runs" in text and "AssertionError: assert 502 == 200" in text
    assert "test_pool" in text and "Slowest tests" in text and "42.0s" in text
    page = render_html(TESTS, "octo/app")
    assert "test_retry[&lt;b&gt;]" in page and "Flaky tests" in page and "Slowest tests" in page


def test_without_test_reports_the_report_says_how_to_add_them():
    text = render_text({**RESULT, "has_test_reports": False, "tests": [], "slow_tests": []}, "octo/app")
    assert "No test reports found" in text and "upload-artifact" in text
