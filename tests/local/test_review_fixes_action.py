"""Fixes from the Phase 11 whole-phase review (Action side), each reproduced first."""
import pytest

from stackvitals.core.tomledit import EditError, apply


@pytest.mark.parametrize("value", ["six", [1, 2], {"a": 1}])
def test_a_wrongly_typed_value_is_refused_politely(value):
    with pytest.raises(EditError):
        apply("", {"alerts.pickup_p75_hours": value})


def test_an_issue_closed_as_done_reopens_only_after_a_new_flake():
    from test_ci_issue_lifecycle import Api, flaky, result
    from stackvitals.ci.automation import sync_issues
    closed_after = Api([{"number": 8, "title": "Flaky test: t::b", "state": "closed", "state_reason": "completed",
                         "closed_at": "2026-10-20T12:00:00Z"}])
    assert sync_issues(closed_after, result(flaky("t::b")))["reopened"] == 0 and closed_after.sent == []
    flaked_since = Api([{"number": 8, "title": "Flaky test: t::b", "state": "closed", "state_reason": "completed",
                         "closed_at": "2026-10-19T12:00:00Z"}])
    assert sync_issues(flaked_since, result(flaky("t::b")))["reopened"] == 1


def _job_without_repo_info(tmp_path):
    import json
    from test_core_appdata import NOW, modules, show
    from stackvitals.core.config import parse
    from stackvitals.core.workspace import run_job
    bare = tmp_path / "remote.git"
    env = {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": bare.as_uri(),
           "RUNNER_TEMP": str(tmp_path / "tmp")}
    run_job(env, [("CI Health", modules)], NOW, prepare=lambda ws: ws.cache.update(settings=parse("")[0]))
    return show(bare, "docs/summary/prs.jsonl"), json.loads(show(bare, "docs/app.json"))["visibility"]


def test_a_failed_repo_lookup_never_publishes_the_tables(tmp_path):
    from test_core_appdata import remote
    remote(tmp_path)
    assert _job_without_repo_info(tmp_path) == (None, "private")


def test_a_repo_known_to_be_public_keeps_its_tables_when_one_lookup_fails(tmp_path):
    from test_core_appdata import run
    run(tmp_path)
    assert _job_without_repo_info(tmp_path) == ('{"number":1}\n', "public")


def test_the_digest_leaves_out_findings_people_set_aside():
    from datetime import datetime, timezone
    from stackvitals.core.digest import compose
    docs = {"insights": {"findings": [{"title": "Snoozed one", "hours": 50, "n": 9, "decision": {"verb": "snooze"}},
                                      {"title": "Open one", "hours": 5, "n": 4}]}}
    text, _ = compose("o/r", datetime(2026, 10, 19, 6, tzinfo=timezone.utc), docs, None, [], None)
    assert "Open one" in text and "Snoozed one" not in text and "1 set aside" in text


def test_the_digest_says_the_window_of_its_deployment_count_and_a_missing_source():
    from datetime import datetime, timezone
    from stackvitals.core.digest import compose
    now = datetime(2026, 10, 19, 6, tzinfo=timezone.utc)
    found = {"window_days": 90, "deploy_source": "releases", "dora": {"deployments": 3}}
    assert "3 deployments in 90 days" in compose("o/r", now, {"delivery": found}, None, [], None)[0]
    none = {"window_days": 90, "deploy_source": None, "dora": {"deployments": 0}}
    text = compose("o/r", now, {"delivery": none}, None, [], None)[0]
    assert "no deployment source found yet" in text and "0 deployments" not in text


def test_a_digest_slot_between_scheduled_runs_still_goes_out_once():
    from datetime import datetime, timezone
    from stackvitals.core.digest import slot
    sunday_late = (6, 22)
    # Sunday 22:00 falls between the 21:17 and 00:17 runs: Monday 00:17 sends last week's digest.
    week, _when = slot(datetime(2026, 10, 26, 0, 17, tzinfo=timezone.utc), *sunday_late)
    assert week == "2026-W43"
    assert slot(datetime(2026, 10, 25, 21, 17, tzinfo=timezone.utc), *sunday_late) is None
    # Before this week's Monday slot, last week's (a week old) is not sent late.
    assert slot(datetime(2026, 10, 26, 5, tzinfo=timezone.utc), 0, 6) is None
    assert slot(datetime(2026, 10, 27, 9, tzinfo=timezone.utc), 0, 6)[0] == "2026-W44"
    assert slot(datetime(2026, 10, 26, 6, 17, tzinfo=timezone.utc), 0, 6)[0] == "2026-W44"


def test_a_local_report_without_the_app_has_no_links_to_it(tmp_path):
    from stackvitals import shell
    assert "index.html" not in shell.nav("ci.html", {"ci.html"})
    assert "index.html#/ci" in shell.nav("ci.html", {"ci.html", "index.html"})
    (tmp_path / "ci.html").write_text("x", encoding="utf-8")
    assert shell.present(tmp_path) == {"ci.html"}
    (tmp_path / "index.html").write_text("app", encoding="utf-8")
    assert shell.present(tmp_path) == {"ci.html", "index.html"}


class ChecksApi:
    repo = "o/r"

    def __init__(self, running=()):
        self.running, self.sent = list(running), []

    def _get(self, path, params=None):
        if path.endswith("/actions/runs"):
            return {"workflow_runs": self.running}
        return []

    def send(self, method, path, body=None):
        self.sent.append((method, path, body))
        return {}


def _feedback(api, runs):
    from stackvitals.ci.action import _pr_feedback
    latest = {r["id"]: r for r in runs}
    data = {"runs": runs, "jobs": [], "tests": []}
    return _pr_feedback(runs, latest, None, api, data, {"jobs": [], "tests": []}, "o/r", comments=False, verdict=True, notes=[])


def checks(api):
    return [b for m, p, b in api.sent if p == "/repos/o/r/check-runs"]


def test_a_cancelled_run_never_passes_the_verdict():
    api = ChecksApi()
    _feedback(api, [{"id": 1, "att": 1, "ev": "pull_request", "pr": [4], "sha": "s1", "c": "cancelled", "cr": "t", "wfn": "CI"}])
    assert checks(api)[0]["conclusion"] == "failure"


def test_the_verdict_waits_while_other_workflows_on_the_commit_still_run():
    api = ChecksApi(running=[{"status": "in_progress", "path": ".github/workflows/slow.yml", "head_sha": "s1"}])
    _feedback(api, [{"id": 1, "att": 1, "ev": "pull_request", "pr": [4], "sha": "s1", "c": "success", "cr": "t", "wfn": "Lint"}])
    posted = checks(api)[0]
    assert posted["status"] == "in_progress" and "conclusion" not in posted


def test_a_merge_queue_commit_gets_its_verdict():
    api = ChecksApi()
    _feedback(api, [{"id": 2, "att": 1, "ev": "merge_group", "sha": "mq1", "c": "success", "cr": "t", "wfn": "CI"}])
    posted = checks(api)
    assert posted and posted[0]["head_sha"] == "mq1" and posted[0]["conclusion"] == "success"


def test_a_replaced_value_keeps_its_comment():
    out = apply('[alerts]\npickup_p75_hours = 5  # tuned for the night shift\nlabel = "a # b"  # kept\n',
                {"alerts.pickup_p75_hours": 8})
    assert "pickup_p75_hours = 8.0  # tuned for the night shift" in out or "pickup_p75_hours = 8  # tuned for the night shift" in out
    assert 'label = "a # b"  # kept' in out


def test_propose_refuses_a_wrong_type_instead_of_crashing(capsys):
    from stackvitals.cli import main
    assert main(["propose", "o/r", "--set", "alerts.pickup_p75_hours=six"]) == 1
    assert "Not proposed" in capsys.readouterr().err
