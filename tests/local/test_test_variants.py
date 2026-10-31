"""Matrix variants: a flaky test's flakes are counted by the report they came from (an OS or a version in a matrix), so a
test that only flakes on macOS says so instead of reading as flaky everywhere."""
from datetime import datetime, timedelta, timezone

from stackvitals.ci.analyze import analyze

NOW = datetime(2026, 10, 28, tzinfo=timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_flakes_are_counted_by_the_report_they_came_from():
    runs, tests = [], []
    for i in range(6):
        when = iso(NOW - timedelta(days=i + 1))
        runs.append({"t": "run", "id": i, "att": 1, "wf": 1, "wfn": "CI", "path": ".github/workflows/ci.yml", "ev": "push",
                     "br": "main", "sha": f"s{i}", "tree": f"t{i}", "pr": [], "c": "success", "cr": when, "st": when, "up": when})
        for name in ("test-results-ubuntu", "test-results-macos"):
            flaky = ["t::net"] if name.endswith("macos") and i % 2 == 0 else []
            tests.append({"t": "tests", "run": i, "att": 1, "art": i * 10 + len(name), "name": name, "total": 20,
                          "failed": [], "flaky": flaky, "skipped": [], "slow": []})
    out = analyze({"runs": runs, "jobs": [], "tests": tests}, NOW, 30, default_branch="main")
    t = next(x for x in out["tests"] if x["id"] == "t::net")
    assert t["variants"] == {"test-results-macos": 3}
