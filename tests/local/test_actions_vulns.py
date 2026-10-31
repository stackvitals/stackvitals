"""Known vulnerabilities in the GitHub Actions a repo's workflows use, matched against OSV's ranges here."""
from stackvitals.deps import actions_vulns as av

WF = """
on: push
jobs:
  a:
    runs-on: ubuntu-latest
    steps:
      - uses: tj-actions/changed-files@v45.0.0
      - uses: tj-actions/changed-files@v46.0.5
      - uses: actions/checkout@692973e3d937129bcbf40652eb9f2f61becf3332
      - uses: ./local
"""
ADV = {"id": "GHSA-mrrh-fwg8-r2c3", "aliases": ["CVE-2025-30066"],
       "affected": [{"package": {"name": "tj-actions/changed-files", "ecosystem": "GitHub Actions"},
                     "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "46.0.1"}]}]}]}


def test_tagged_actions_in_a_vulnerable_range_are_found():
    uses = av.uses_in({".github/workflows/ci.yml": WF})
    assert [(u["action"], u["ref"]) for u in uses] == [("tj-actions/changed-files", "v45.0.0"), ("tj-actions/changed-files", "v46.0.5"),
                                                       ("actions/checkout", "692973e3d937129bcbf40652eb9f2f61becf3332")]
    post = lambda url, body: {"results": [{"vulns": [{"id": "GHSA-mrrh-fwg8-r2c3"}]}]}  # noqa: E731
    found, pinned = av.findings(uses, post, lambda url: ADV)
    assert [(f["package"], f["version"], f["fixed"]) for f in found] == [("tj-actions/changed-files", "v45.0.0", "46.0.1")]
    assert pinned == 1 and found[0]["files"] == [".github/workflows/ci.yml"]


def test_major_only_tags_count_only_when_no_release_of_that_major_is_fixed():
    ranges = ADV["affected"][0]["ranges"]
    assert av.affected("46", ranges) is False and av.affected("45", ranges) is True and av.affected("45.9.9", ranges) is True
