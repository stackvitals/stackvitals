from stackvitals.core.config import DELIVERY
from stackvitals.core.delivery import deploy_kind, explain_deployments, find_deployments

CFG = {"delivery": {**DELIVERY, "source": "auto"}}


def run(rid, name, path, ev="push", br="main", c="success", day=1):
    return {"t": "run", "id": rid, "att": 1, "wfn": name, "path": path, "ev": ev, "br": br, "c": c, "sha": f"s{rid}",
            "up": f"2026-10-{day:02d}T10:00:00Z"}


REPO = {"default_branch": "main",
        "deployments": [{"env": "Production", "at": "2026-10-02T10:00:00Z", "done": "2026-10-02T10:05:00Z", "state": "SUCCESS", "sha": "a"},
                        {"env": "Preview", "at": "2026-10-03T10:00:00Z", "state": "SUCCESS", "sha": "b"},
                        {"env": "pypi", "at": "2026-10-04T10:00:00Z", "state": "SUCCESS", "sha": "c"}],
        "releases": [{"tag": "v1.0.0", "at": "2026-10-05T10:00:00Z", "pre": False, "sha": "d"},
                     {"tag": "v1.1.0-rc.1", "at": "2026-10-06T10:00:00Z", "pre": False, "sha": "e"}]}
CI = {"runs": [run(1, "Deploy", ".github/workflows/deploy.yml"), run(2, "Deploy docs", ".github/workflows/docs.yml"),
               run(3, "Release", ".github/workflows/release.yml", ev="release", br="v1.0.0"),
               run(4, "CI", ".github/workflows/ci.yml"), run(5, "Deploy", ".github/workflows/deploy.yml", c="failure", day=2)]}


def test_the_dry_run_names_the_source_used_and_every_one_it_passed_over():
    out = explain_deployments(REPO, CI, CFG)
    found, source = find_deployments(REPO, CI, CFG)
    assert out["source"] == source == "deployments api" and out["deployments"] == len(found) == 1
    assert [c["source"] for c in out["considered"]][:2] == ["deployments api", "deploy workflows"]
    assert out["considered"][0]["used"] and not any(c["used"] for c in out["considered"][1:])


def test_each_workflow_says_whether_it_counts_and_why_not():
    flows = {w["path"]: w for w in explain_deployments(REPO, CI, CFG)["workflows"]}
    assert flows[".github/workflows/deploy.yml"]["kind"] == "deploy" and flows[".github/workflows/deploy.yml"]["counted"] == 1
    assert flows[".github/workflows/deploy.yml"]["skipped"] == 1  # the failed run
    assert flows[".github/workflows/docs.yml"]["kind"] is None and '"docs"' in flows[".github/workflows/docs.yml"]["why"]
    assert "deploy_workflow" in flows[".github/workflows/ci.yml"]["why"]
    assert flows[".github/workflows/release.yml"]["kind"] == "release"


def test_environments_are_shown_as_counted_or_hidden_with_their_kind():
    envs = {e["name"]: e for e in explain_deployments(REPO, CI, CFG)["environments"]}
    assert envs["Production"]["counted"] and envs["Production"]["as"] == "production"
    assert not envs["Preview"]["counted"] and envs["Preview"]["as"] == "staging"
    assert not envs["pypi"]["counted"] and envs["pypi"]["as"] == "publishing"


def test_releases_count_prereleases_apart_and_settings_are_echoed():
    out = explain_deployments(REPO, CI, CFG)
    assert out["releases"] == {"published": 1, "prereleases_skipped": 1}
    assert out["settings"]["production"] == DELIVERY["production"]


def test_deploy_kind_still_answers_as_before():
    assert deploy_kind("Deploy", ".github/workflows/deploy.yml", DELIVERY["deploy_workflow"]) == "deploy"
    assert deploy_kind("Deploy docs", ".github/workflows/docs.yml", DELIVERY["deploy_workflow"]) is None


def test_the_cli_prints_the_dry_run_in_plain_lines():
    from stackvitals.core.deliverycli import deploy_dry_run
    text = deploy_dry_run("o/r", explain_deployments(REPO, CI, CFG))
    assert "1 from deployments api" in text and "passed over" in text
    assert "Deploy docs (.github/workflows/docs.yml)" in text and "pypi: 1 deployments, not counted (publishing)" in text
    assert "[delivery]" in text


def test_no_side_service_reason_without_any_deploy_workflow():
    ci = {"runs": [run(4, "CI", ".github/workflows/ci.yml")]}
    assert explain_deployments(REPO, ci, CFG)["order_reason"] is None


def test_a_deploy_workflow_is_passed_over_when_another_source_counts():
    # Review finding: the dry run said deploy.yml's runs were counted while the Deployments API was the source used.
    flows = {w["path"]: w for w in explain_deployments(REPO, CI, CFG)["workflows"]}
    assert flows[".github/workflows/deploy.yml"]["used"] is False
    from stackvitals.core.deliverycli import deploy_dry_run
    assert "passed over: deployments api is the source used" in deploy_dry_run("o/r", explain_deployments(REPO, CI, CFG))
    only = {**CFG, "delivery": {**CFG["delivery"], "source": "workflows"}}
    assert {w["path"]: w for w in explain_deployments(REPO, CI, only)["workflows"]}[".github/workflows/deploy.yml"]["used"]


def test_one_commit_rolled_out_to_several_regions_or_stages_is_one_deployment():
    # PL11: multi-region and canary-then-full rollouts counted each stage as a deployment, inflating frequency.
    repo = {"default_branch": "main", "deployments": [
        {"env": "production-canary", "at": "2026-10-02T10:00:00Z", "done": "2026-10-02T10:05:00Z", "state": "SUCCESS", "sha": "a"},
        {"env": "production-eu", "at": "2026-10-02T11:00:00Z", "done": "2026-10-02T11:05:00Z", "state": "SUCCESS", "sha": "a"},
        {"env": "production-us", "at": "2026-10-02T12:00:00Z", "done": "2026-10-02T12:05:00Z", "state": "SUCCESS", "sha": "a"},
        {"env": "production", "at": "2026-10-03T10:00:00Z", "done": "2026-10-03T10:05:00Z", "state": "SUCCESS", "sha": "b"}],
        "releases": []}
    found, source = find_deployments(repo, {"runs": []}, CFG)
    assert source == "deployments api" and len(found) == 2
    first = next(d for d in found if d["sha"] == "a")
    assert first["finished"] == "2026-10-02T10:05:00Z" and first["stages"] == 3


def test_a_rollback_to_an_earlier_commit_is_its_own_deployment():
    # Review finding: de-duplicating by commit across all time merged A, B, back to A into two deployments.
    dep = lambda sha, at: {"env": "production", "at": at, "done": at, "state": "SUCCESS", "sha": sha}  # noqa: E731
    repo = {"default_branch": "main", "releases": [], "deployments": [
        dep("a", "2026-10-05T10:00:00Z"), dep("b", "2026-10-06T10:00:00Z"), dep("a", "2026-10-07T10:00:00Z"),
        # The same commit again days later with nothing between: a redeploy, counted again.
        dep("a", "2026-10-10T10:00:00Z"),
        # A stage without a finish time never stands in for its group.
        {"env": "production-eu", "at": None, "done": None, "state": "SUCCESS", "sha": "c"},
        dep("c", "2026-10-11T10:00:00Z")]}
    found, _ = find_deployments(repo, {"runs": []}, CFG)
    assert [(d["sha"], d["finished"][:10]) for d in found] == [
        ("a", "2026-10-05"), ("b", "2026-10-06"), ("a", "2026-10-07"), ("a", "2026-10-10"), ("c", "2026-10-11")]
