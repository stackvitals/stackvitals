"""Phase 13 M4: deployments and failures validated: fix-chain linkage beside DevLake's time order."""
from datetime import datetime, timedelta, timezone

from stackvitals.core.config import parse
from stackvitals.core.delivery import dora, find_incidents

NOW = datetime(2026, 10, 21, tzinfo=timezone.utc)


def stamp(days):
    return (NOW - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_a_revert_is_tied_to_the_deployment_that_shipped_what_it_undoes():
    # PR 1 ships in d1 (day 20); d2 (day 10) and d3 (day 5) ship other work; the revert of PR 1 is opened on day 4.
    deps = [{"id": "d0", "finished": stamp(40)}, {"id": "d1", "finished": stamp(20)}, {"id": "d2", "finished": stamp(10)},
            {"id": "d3", "finished": stamp(5)}]
    prs = [{"n": 1, "ti": "Add cache", "cr": stamp(22), "mg": stamp(21)},
           {"n": 2, "ti": "Revert \"Add cache\"", "cr": stamp(4), "mg": stamp(3)}]
    inc = find_incidents(prs, [], deps, parse("")[0])[0]
    # DevLake's time order blames the last deployment before the revert; the fix chain names the one that shipped PR 1.
    assert inc["deployment"] == "d3" and inc["fix_chain_deployment"] == "d1"
    out = dora(deps, [], [inc], NOW - timedelta(days=30), NOW)
    assert out["change_failure_rate"] == round(1 / 3, 4) and out["cfr_fix_chain"] == round(1 / 3, 4)
    assert out["linkage"] == {"reverts": 1, "fix_chain_found": 1, "disagree": 1, "never_shipped": 0}


def test_without_a_target_the_fix_chain_falls_back_to_time_order():
    deps = [{"id": "d1", "finished": stamp(20)}]
    prs = [{"n": 2, "ti": "Revert \"Something long gone\"", "cr": stamp(4), "mg": stamp(3)}]
    inc = find_incidents(prs, [], deps, parse("")[0])[0]
    assert inc["fix_chain_deployment"] is None
    assert dora(deps, [], [inc], NOW - timedelta(days=30), NOW)["linkage"] == {"reverts": 1, "fix_chain_found": 0, "disagree": 0,
                                                                         "never_shipped": 0}


def test_a_change_reverted_before_any_release_shipped_it_is_no_failed_deployment():
    # Real-data finding (2026-10-22): most reverts land before the next release, so the bad change never shipped.
    deps = [{"id": "d0", "finished": stamp(40)}, {"id": "d1", "finished": stamp(20)}, {"id": "d2", "finished": stamp(2)}]
    prs = [{"n": 1, "ti": "Add cache", "cr": stamp(12), "mg": stamp(11)},
           {"n": 2, "ti": "Revert \"Add cache\"", "cr": stamp(6), "mg": stamp(5)}]
    inc = find_incidents(prs, [], deps, parse("")[0])[0]
    # Time order blames d1, which never had PR 1; d2 shipped PR 1 and its revert together.
    assert inc["deployment"] == "d1" and inc["fix_chain_deployment"] is None and inc["never_shipped"] is True
    out = dora(deps, [], [inc], NOW - timedelta(days=30), NOW)
    assert out["change_failure_rate"] == 0.5 and out["cfr_fix_chain"] == 0.0
    assert out["linkage"] == {"reverts": 1, "fix_chain_found": 0, "disagree": 0, "never_shipped": 1}


def test_a_workflow_file_named_deploy_ships_whatever_its_display_name_says():
    # Labelled 2026-10-22: "Check and Publish Chemistry Note" (deploy.yml) deploys every push to master.
    from stackvitals.core.delivery import deploy_kind
    pattern = parse("")[0]["delivery"]["deploy_workflow"]
    assert deploy_kind("Check and Publish Chemistry Note", ".github/workflows/deploy.yml", pattern) == "deploy"
    assert deploy_kind("Release", ".github/workflows/release.yaml", pattern) == "release"
    # Anything else keeps the deny words: these don't ship.
    assert deploy_kind("Release Docs Check", ".github/workflows/release-docs-check.yml", pattern) is None
    assert deploy_kind("Preview release", ".github/workflows/preview-release.yml", pattern) is None
    assert deploy_kind("Deploy docs", ".github/workflows/deploy-docs.yml", pattern) is None


def test_a_revert_before_any_later_deployment_means_the_change_never_shipped():
    # Review finding: with no deployment after the change merged, the revert was still blamed on an older deployment.
    deps = [{"id": "d0", "finished": stamp(40)}, {"id": "d1", "finished": stamp(20)}]
    prs = [{"n": 1, "ti": "Add cache", "cr": stamp(12), "mg": stamp(11)},
           {"n": 2, "ti": "Revert \"Add cache\"", "cr": stamp(6), "mg": stamp(5)}]
    inc = find_incidents(prs, [], deps, parse("")[0])[0]
    assert inc["never_shipped"] is True and inc["fix_chain_deployment"] is None
    assert dora(deps, [], [inc], NOW - timedelta(days=30), NOW)["cfr_fix_chain"] == 0.0
    # Merged before the oldest known deployment: nothing says whether it shipped.
    old = [{"n": 1, "ti": "Add cache", "cr": stamp(52), "mg": stamp(50)}, {"n": 2, "ti": "Revert \"Add cache\"", "cr": stamp(6), "mg": stamp(5)}]
    assert find_incidents(old, [], deps, parse("")[0])[0]["never_shipped"] is False


def test_an_edited_revert_title_still_counts():
    from stackvitals.core.ai_outcomes import is_revert
    assert is_revert({"ti": 'Revert "Add cache" because it broke CI'}) and is_revert({"ti": 'Revert "Add cache"'})


def test_a_plain_deploy_file_named_for_docs_or_previews_is_not_production():
    from stackvitals.core.delivery import deploy_kind
    pattern = parse("")[0]["delivery"]["deploy_workflow"]
    assert deploy_kind("Deploy docs", ".github/workflows/deploy.yml", pattern) is None
    assert deploy_kind("Deploy preview", ".github/workflows/deploy.yml", pattern) is None
    assert deploy_kind("Check and Publish Chemistry Note", ".github/workflows/deploy.yml", pattern) == "deploy"
