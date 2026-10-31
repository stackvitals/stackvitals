import json
import sys

import httpx
from stackvitals.ci.api import ActionsAPI
from stackvitals.ci.automation import alert_message, new_flakes, quarantine_exit, quarantine_list, run_quarantined, should_rerun, sync_issues

ITEMS_FLAKY = [{"kind": "test", "name": "t::a", "verdict": "known flaky"}, {"kind": "job", "name": "CI / e2e",
                                                                            "verdict": "known flaky"}]


AUTO_RESULT = {"tests": [{"id": "t::a", "state": "flaky", "flake_events": 4, "runs": 50, "last_flake": "2026-10-15T00:00:00Z"},
                    {"id": "t::b", "state": "fixed", "flake_events": 0, "runs": 50, "last_flake": "2026-09-01T00:00:00Z"},
                    {"id": "t::c", "state": "suspect", "flake_events": 1, "runs": 50, "last_flake": "2026-10-14T00:00:00Z"}],
          "jobs": [{"workflow": ".github/workflows/ci.yml", "job": "e2e", "state": "flaky", "flake_events": 3, "runs": 40}]}


def test_only_tests_in_the_flaky_state_are_quarantined():
    assert quarantine_list(AUTO_RESULT) == ["t::a"]


def test_the_quarantine_wrapper_runs_the_command_and_reads_its_reports(tmp_path):
    report = tmp_path / "out.xml"
    script = (f"open(r'{report}','w').write('<testsuite><testcase classname=\"t\" name=\"a\"><failure message=\"x\"/>"
              "</testcase></testsuite>'); raise SystemExit(1)")
    code = run_quarantined([sys.executable, "-c", script], [str(tmp_path / "*.xml")], {"t::a"})
    assert code == 0
    assert run_quarantined([sys.executable, "-c", script], [str(tmp_path / "*.xml")], set()) == 1


def test_one_issue_per_flaky_test_is_kept_and_closed_when_fixed():
    issues = [{"number": 3, "title": "Flaky test: t::b", "state": "open", "body": ""},
              {"number": 4, "title": "Flaky test: t::a", "state": "open", "body": "old"}]
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path, json.loads(request.content) if request.content else None))
        if request.method == "GET":
            return httpx.Response(200, json=issues)
        return httpx.Response(200, json={"number": 9})
    api = ActionsAPI("tok", "o/r", client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    out = sync_issues(api, AUTO_RESULT)
    assert out == {"created": 1, "updated": 1, "closed": 1, "reopened": 0, "kept_closed": 0}
    created = [c for c in calls if c[0] == "POST"][0]
    assert created[2]["title"] == "Flaky job: ci.yml / e2e" and created[2]["labels"] == ["flaky-test"]
    assert ("PATCH", "/repos/o/r/issues/3", {"state": "closed", "state_reason": "completed"}) in calls


def test_alerts_name_only_what_newly_turned_flaky():
    old = {"tests": [{"id": "t::a", "state": "flaky"}], "jobs": []}
    assert new_flakes(old, AUTO_RESULT) == ["job ci.yml / e2e"]
    from stackvitals.core.chat import text
    alert = text(alert_message(["job ci.yml / e2e"], "o/r"))
    assert "ci.yml / e2e" in alert and "o/r" in alert
    # The first run after install has nothing to compare with, so it sends no alert.
    assert new_flakes(None, AUTO_RESULT) == []
