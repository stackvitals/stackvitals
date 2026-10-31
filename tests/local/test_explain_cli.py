import json

from stackvitals.core import explaincli


def docs(tmp_path):
    d = tmp_path / "docs"
    d.mkdir()
    (d / "delivery.json").write_text(json.dumps({"window_days": 90, "dora": {
        "lead_time_hours": 26.5, "lead_time_n": 3, "deployments": 2, "change_failure_rate": 0.5, "failed_deployments": 1,
        "recovery_hours": 1.5, "recovery_n": 1,
        "evidence": {"deployments": [["aaaaaaaaaaaa", "2026-10-01T10:00:00Z"], ["bbbbbbbbbbbb", "2026-10-02T10:00:00Z"]],
                     "lead_time": [[12, "bbbbbbbbbbbb", 3000], [11, "aaaaaaaaaaaa", 1200], [10, "aaaaaaaaaaaa", 90]], "lead_time_total": 3,
                     "failed": [["bbbbbbbbbbbb", "revert", 14]], "recovery": [["bbbbbbbbbbbb", "revert", 14, 90]]}},
        "phases": {"pickup": {"n": 2, "enough": False, "p75_h": None, "evidence": [[12, 30.0], [11, 2.5]]}}}), encoding="utf-8")
    (d / "data.json").write_text(json.dumps({"pushes": {"pushes": 10, "first_try_share": 0.8,
                                                        "not_first_try": [["cccccccccccc", "main", [99]]], "not_first_try_total": 2}}), encoding="utf-8")
    return d


def test_explain_prints_the_number_its_meaning_and_each_item_with_a_link(tmp_path, capsys):
    assert explaincli.main(["o/r", "lead-time", "--docs", str(docs(tmp_path))]) == 0
    out = capsys.readouterr().out
    assert "Change lead time: 26.5 h (median of 3 deployed pull requests" in out
    assert "#12" in out and "https://github.com/o/r/pull/12" in out and "50.0 h" in out
    assert out.index("#12") < out.index("#11")  # longest first


def test_explain_covers_failures_first_try_and_phases_and_json(tmp_path, capsys):
    d = str(docs(tmp_path))
    assert explaincli.main(["o/r", "change-failure", "--docs", d]) == 0
    assert "https://github.com/o/r/pull/14" in capsys.readouterr().out
    assert explaincli.main(["o/r", "first-try", "--docs", d]) == 0
    out = capsys.readouterr().out
    assert "80%" in out and "https://github.com/o/r/actions/runs/99" in out and "1 of 2 shown" in out
    assert explaincli.main(["o/r", "pickup", "--docs", d, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["items"][0]["pr"] == 12


def test_an_unknown_number_lists_what_can_be_explained(tmp_path, capsys):
    assert explaincli.main(["o/r", "happiness", "--docs", str(docs(tmp_path))]) == 2
    assert "lead-time" in capsys.readouterr().err
