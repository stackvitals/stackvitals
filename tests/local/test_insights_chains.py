from stackvitals.core.insights import evidence_chains

RED = {"rerun_tests": [
    {"test": "tests/test_api.py::test_login", "hours": 12.5, "prs": 3, "pr_list": [4, 9, 12], "runs": [[100, 1]]},
    {"test": "tests/test_db.py::test_pool", "hours": 2.0, "prs": 1, "pr_list": [7], "runs": [[101, 1]]},
    {"test": "gone::test", "hours": 1.0, "prs": 1, "pr_list": [8], "runs": [[102, 1]]}]}
CI = {"tests": [
    {"id": "tests/test_api.py::test_login", "state": "flaky", "flake_events": 6, "runs": 40, "owners": ["@acme/auth"],
     "owners_from": "tests/test_api.py"},
    {"id": "tests/test_db.py::test_pool", "state": "flaky", "flake_events": 2, "runs": 40, "owners": [], "owners_from": None}]}
DECISIONS = {"test:tests/test_api.py::test_login": {"verb": "quarantine", "kind": "test", "id": "tests/test_api.py::test_login",
                                                     "by": "ann", "at": "2026-10-20T10:00:00Z", "until": "2026-11-19",
                                                     "reason": "fix in #15"}}


def test_each_costly_flaky_test_is_traced_to_its_delays_owner_and_decision():
    chains = evidence_chains(RED, CI, DECISIONS)
    assert [c["test"] for c in chains] == ["tests/test_api.py::test_login", "tests/test_db.py::test_pool", "gone::test"]
    first = chains[0]
    assert first["hours"] == 12.5 and first["pr_list"] == [4, 9, 12] and first["flake_events"] == 6
    assert first["owners"] == ["@acme/auth"] and first["decision"]["verb"] == "quarantine" and first["decision"]["by"] == "ann"
    assert chains[1]["owners"] == [] and chains[1]["decision"] is None
    assert chains[2]["state"] is None


def test_no_red_waits_or_no_tests_means_no_chains():
    assert evidence_chains(None, CI, {}) == [] and evidence_chains({"rerun_tests": []}, CI, {}) == []
    assert evidence_chains(RED, None, {})[0]["owners"] == []
