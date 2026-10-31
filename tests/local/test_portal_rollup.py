from stackvitals.portal.rollup import org_rollup


def repo(name, facts, archived=False):
    return {"name": name, "archived": archived, "fork": False, "modules": {"facts": facts} if facts is not None else None}


REPOS = [repo("o/a", {"ci_first_try": 0.9, "ci_flaky": 2, "open_prs": 10, "stale_prs": 3, "pickup_p75_h": 5.0, "deployments": 20,
                      "change_failure_rate": 0.1, "findings": 1, "newcomers_waiting": 0}),
         repo("o/b", {"ci_first_try": 0.6, "ci_flaky": 7, "open_prs": 4, "stale_prs": 0, "pickup_p75_h": 30.0, "deployments": None,
                      "change_failure_rate": None, "findings": 4, "newcomers_waiting": 2}),
         repo("o/c", None), repo("o/d", {"ci_flaky": 50}, archived=True)]


def test_the_org_rollup_sums_counts_takes_medians_and_names_the_repos_that_lead():
    got = org_rollup(REPOS)
    assert got["repos"] == 3 and got["running"] == 2
    assert got["totals"]["ci_flaky"] == 9 and got["totals"]["stale_prs"] == 3 and got["totals"]["deployments"] == 20
    assert got["medians"]["ci_first_try"] == 0.75 and got["medians"]["pickup_p75_h"] == 17.5
    assert got["medians"]["change_failure_rate"] == 0.1 and got["counts"]["change_failure_rate"] == 1
    assert got["leaders"]["ci_flaky"][0] == {"repo": "o/b", "value": 7}
    assert got["leaders"]["pickup_p75_h"][0]["repo"] == "o/b"  # the slowest pickup leads (higher is worse)


def test_no_repo_running_the_suite_gives_an_empty_rollup():
    assert org_rollup([repo("o/x", None)])["running"] == 0
