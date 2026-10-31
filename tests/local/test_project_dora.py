"""One project across several repos: their DevLake tables pooled and DevLake's own project SQL run on them, so the
project's DORA is what a DevLake project of those repos would show."""
from datetime import timedelta

import pytest

from stackvitals.core import export, projectcli
from stackvitals.core.config import parse
from test_core_delivery import NOW
from test_core_export import fixture

pytest.importorskip("duckdb")


def test_a_project_pools_its_repos_and_counts_every_deployment_once():
    flow, repo, issues = fixture()
    cfg = parse("")[0]
    tables = {r: export.devlake_tables(r, flow, repo, {"runs": []}, issues, cfg) for r in ("o/a", "o/b")}
    pooled = export.pool(tables, "web")
    assert {m["project_name"] for m in pooled["project_mapping"]} == {"web"}
    assert len(pooled["cicd_deployment_commits"]) == 2 * len(tables["o/a"]["cicd_deployment_commits"])
    out = projectcli.project_dora("web", tables, NOW - timedelta(days=90), NOW)
    one = out["repos"]["o/a"]
    assert one == out["repos"]["o/b"]
    # Two identical repos deploy on the same days: the same deployment days, the same lead time and failure rate.
    assert out["project"]["lead_time"] == one["lead_time"]
    assert out["project"]["change_failure_rate"] == one["change_failure_rate"]
