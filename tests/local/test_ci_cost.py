"""CI cost: billed minutes and money per workflow and job at GitHub's published per-minute prices (each job rounded up
to a whole minute, by its runner), the minutes spent on attempts that failed and then passed on a re-run, and what a
public repo would pay on a private one; self-hosted runners are counted in minutes only."""
from datetime import datetime, timedelta, timezone

from stackvitals.ci import cost

NOW = datetime(2026, 10, 28, tzinfo=timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def job(run, att, name, minutes, labels=("ubuntu-latest",), c="success", day=3):
    st = NOW - timedelta(days=day)
    return {"t": "job", "run": run, "att": att, "id": run * 10 + att, "n": name, "c": c, "st": iso(st),
            "en": iso(st + timedelta(minutes=minutes)), "lb": list(labels)}


def run(rid, att, wf="ci.yml", wfn="CI", day=3, c="success"):
    return {"t": "run", "id": rid, "att": att, "path": f".github/workflows/{wf}", "wfn": wfn, "cr": iso(NOW - timedelta(days=day)), "c": c}


def test_runner_labels_map_to_published_prices():
    assert cost.rate(["ubuntu-latest"]) == ("linux", 0.006)
    assert cost.rate(["ubuntu-24.04-arm"]) == ("linux arm", 0.005)
    assert cost.rate(["windows-2022"]) == ("windows", 0.010)
    assert cost.rate(["macos-14"]) == ("macos", 0.062)
    assert cost.rate(["ubuntu-latest-8-cores"]) == ("linux 8-core", 0.022)
    assert cost.rate(["self-hosted", "linux"]) == ("self-hosted", None)


def test_minutes_and_money_per_workflow_and_job_with_each_job_rounded_up():
    data = {"runs": [run(1, 1), run(2, 1, wf="release.yml", wfn="Release")],
            "jobs": [job(1, 1, "test", 10.2), job(1, 1, "lint", 0.5, labels=("macos-14",)), job(2, 1, "build", 3, labels=("windows-latest",))]}
    got = cost.report(data, NOW, private=True, days=30)
    assert got["minutes"] == 11 + 1 + 3 and got["usd"] == round(11 * 0.006 + 0.062 + 3 * 0.010, 2)
    top = got["workflows"][0]
    assert top["workflow"] == "CI" and top["minutes"] == 12 and top["usd"] == round(11 * 0.006 + 0.062, 2)
    assert got["jobs"][0]["job"] == "test" and got["by_runner"]["linux"] == 11


def test_attempts_that_failed_then_passed_on_a_rerun_are_counted_as_waste():
    data = {"runs": [run(1, 1, c="failure"), run(1, 2)],
            "jobs": [job(1, 1, "test", 8, c="failure"), job(1, 2, "test", 8)]}
    got = cost.report(data, NOW, private=True, days=30)
    assert got["rerun_minutes"] == 8 and got["rerun_usd"] == round(8 * 0.006, 2)


def test_a_public_repo_pays_nothing_for_standard_runners_but_is_told_the_private_price():
    data = {"runs": [run(1, 1)], "jobs": [job(1, 1, "test", 10), job(1, 1, "big", 2, labels=("ubuntu-latest-16-cores",))]}
    got = cost.report(data, NOW, private=False, days=30)
    assert got["usd"] == round(2 * 0.042, 2)  # larger runners are never free
    assert got["private_usd"] == round(10 * 0.006 + 2 * 0.042, 2)


def test_self_hosted_minutes_are_counted_without_a_price_and_old_runs_are_left_out():
    data = {"runs": [run(1, 1), run(2, 1, day=60)],
            "jobs": [job(1, 1, "test", 5, labels=("self-hosted", "linux")), job(2, 1, "test", 99, day=60)]}
    got = cost.report(data, NOW, private=True, days=30)
    assert got["minutes"] == 5 and got["usd"] == 0 and got["self_hosted_minutes"] == 5
