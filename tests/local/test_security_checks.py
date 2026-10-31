"""The repo's own security checks (OpenSSF Scorecard's, done our way): dangerous workflows with guards recognised,
token permissions, pinning, branch protection tiers with "unknown" when unreadable, and one score with SARIF."""
from stackvitals.security import probes, repo_checks, workflows

DANGEROUS = """
on: pull_request_target
permissions: write-all
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.pull_request.head.sha }}
      - run: echo "${{ github.event.pull_request.title }}"
  labelled:
    if: contains(github.event.pull_request.labels.*.name, 'safe to test')
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@692973e3d937129bcbf40652eb9f2f61becf3332
        with:
          ref: ${{ github.event.pull_request.head.sha }}
      - run: curl -sSL https://example.com/install.sh | bash
"""

SAFE = """
on: [push, pull_request]
permissions:
  contents: read
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@692973e3d937129bcbf40652eb9f2f61becf3332
      - uses: ./local-action
      - run: echo hi
"""


def test_dangerous_workflow_findings_name_the_guard_instead_of_alarming():
    found = workflows.check(".github/workflows/t.yml", DANGEROUS)
    kinds = [(f["probe"], f["job"], bool(f["guarded"])) for f in found]
    assert ("hasDangerousWorkflowUntrustedCheckout", "test", False) in kinds
    assert ("hasDangerousWorkflowUntrustedCheckout", "labelled", True) in kinds
    assert ("hasDangerousWorkflowScriptInjection", "test", False) in kinds
    assert ("pinsDependencies", "test", False) in kinds and ("pinsDependencies", "labelled", False) in kinds  # tag and curl|bash
    assert ("topLevelPermissions", None, False) in kinds
    assert workflows.check(".github/workflows/s.yml", SAFE) == []


def test_branch_tiers_are_unknown_when_unreadable_not_passed():
    assert repo_checks.branch_tiers(None, None) == {"tiers": [{"tier": i, "rule": r, "state": "unknown"} for i, r in enumerate(
        ["no force pushes or deletion", "reviews required", "status checks required", "two reviewers and code owners",
         "stale reviews dismissed, admins included"], 1)], "level": 0, "readable": False}
    rules = [{"type": "non_fast_forward"}, {"type": "deletion"}, {"type": "pull_request", "parameters": {"required_approving_review_count": 1}}]
    got = repo_checks.branch_tiers(None, rules)
    assert got["level"] == 2 and got["tiers"][2]["state"] == "missing"


def test_tree_releases_and_score():
    t = repo_checks.tree_facts(["bin/tool.exe", "gradle/wrapper/gradle-wrapper.jar", "fuzz/parse_fuzzer.cc", "sbom.spdx.json"])
    assert t == {"binaries": ["bin/tool.exe"], "sbom_files": ["sbom.spdx.json"], "fuzzing": ["fuzz/parse_fuzzer.cc"]}
    rel = repo_checks.releases([{"tag_name": "v2", "assets": [{"name": "tool.tar.gz"}, {"name": "tool.tar.gz.sig"}]},
                                {"tag_name": "v1", "assets": [{"name": "tool.tar.gz"}]}])
    assert rel == {"releases": 2, "signed": ["v2"], "sbom": []}
    found = workflows.check(".github/workflows/t.yml", DANGEROUS)
    facts = {"tree": t, "releases": rel, "branch": repo_checks.branch_tiers(None, None), "policy": {"file": None},
             "workflows": {"sast": [], "publish": []}}
    results = probes.verdicts(found, facts)
    by = {r["probe"]: r["result"] for r in results}
    assert by["branchProtectionLevel"] == "unknown" and by["hasBinaryArtifacts"] == "fail" and by["hasSBOM"] == "pass"
    assert 0 <= probes.score(results) < 10
    report = probes.sarif(results)
    assert report["version"] == "2.1.0" and any(h["ruleId"] == "hasDangerousWorkflowScriptInjection" for h in report["runs"][0]["results"])
