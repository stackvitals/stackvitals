"""SQL across several repos at once (an org): each summary table becomes one view over every repo with a `repo` column,
so cross-repo questions (cycle time per repo, an org-wide median) are one query."""
import json

from stackvitals.core import sqlcli
from stackvitals.core.summary import write_pr_summary
from test_core_export import fixture
from test_core_delivery import NOW


def test_several_folders_are_one_table_with_a_repo_column(tmp_path, capsys):
    flow, _repo, _issues = fixture()
    for name, n in (("web", 41), ("api", 20)):
        folder = tmp_path / name
        write_pr_summary(folder, {"closed": flow["closed"][:n], "open": []}, NOW, f"o/{name}")
    query = "select repo, count(*) as prs from prs group by repo order by repo"
    assert sqlcli.main([query, "--dir", str(tmp_path / "web"), "--dir", str(tmp_path / "api"), "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows == [{"repo": "api", "prs": 20}, {"repo": "web", "prs": 41}]
    # One repo still works as before, with the same column.
    assert sqlcli.main(["select distinct repo from prs", "--dir", str(tmp_path / "web"), "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == [{"repo": "web"}]


def test_summary_columns_have_fixed_types_so_repos_combine_even_when_a_column_is_all_empty(tmp_path, capsys):
    from stackvitals.core.summary import TYPES, pr_rows
    flow, _repo, _issues = fixture()
    assert set(pr_rows(flow, NOW, "o/r")[0]) <= set(TYPES["prs"])  # every field the summary writes has a type
    write_pr_summary(tmp_path / "busy", flow, NOW, "o/busy")
    unmerged = [{**p, "mg": None, "cl": None, "st": "OPEN"} for p in flow["closed"][:3]]
    write_pr_summary(tmp_path / "quiet", {"closed": [], "open": unmerged}, NOW, "o/quiet")  # cycle_s all empty
    query = "select repo, round(median(cycle_s) / 3600, 1) as h from prs group by repo order by repo"
    assert sqlcli.main([query, "--dir", str(tmp_path / "busy"), "--dir", str(tmp_path / "quiet"), "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["repo"] == "busy" and rows[0]["h"] is not None and rows[1] == {"repo": "quiet", "h": None}
