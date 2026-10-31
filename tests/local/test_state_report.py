"""Phase 9 M2: the public report is built only from the published benchmark files, and every number is in a CSV."""
import csv
import json

Q = lambda p50, extra=0: {"repos": 120, "p10": p50 / 2, "p25": p50 * 0.8, "p50": p50, "p75": p50 * 1.2 + extra, "p90": p50 * 2}  # noqa: E731


def bench_dir(tmp_path):
    ci = {"built_at": "2026-10-19T13:00:18Z", "repos": 4025, "definition": "per push ...", "groups": {
        "all|all": {"repos": 4025, "median_s": Q(300), "first_try_share": Q(0.8), "rerun_share": Q(0.02)},
        "Python|all": {"repos": 900, "median_s": Q(240), "first_try_share": Q(0.85), "rerun_share": Q(0.01)},
        "Rust|all": {"repos": 400, "median_s": Q(900), "first_try_share": Q(0.75), "rerun_share": Q(0.03)},
        "all|10k+": {"repos": 300, "median_s": Q(1200), "first_try_share": Q(0.7), "rerun_share": Q(0.05)},
        "Python|10k+": {"repos": 60, "median_s": Q(600), "first_try_share": Q(0.72), "rerun_share": Q(0.04)}}}
    flow = {"built_at": "2026-10-19T07:54:52Z", "repos": 36671, "definition": "per repo ...", "groups": {
        "all|all": {"repos": 36671, "first_review_hours": Q(20), "merge_hours": Q(30), "outsider_merge_rate": Q(0.5),
                    "size_lines": Q(60)},
        "Python|all": {"repos": 5000, "first_review_hours": Q(18), "merge_hours": Q(28), "outsider_merge_rate": Q(0.55),
                       "size_lines": Q(50)}},
        "odds_backtest": {"repos": 4210, "prs": 51000, "typical": 0.5, "mae": {"raw": 0.14, "calibrated": 0.11, "typical_only": 0.2},
                          "calibration": [{"bin": "0.3-0.4", "prs": 900, "predicted": 0.35, "observed": 0.33}]},
        "agent_prs": {"all|all": {"repos_with_agent_prs": 800, "agent": {"decided": 9000, "merged": 0.33},
                                  "outsider": {"decided": 400000, "merged": 0.52}}}}
    community = {"built_at": "2026-10-19T07:54:52Z", "repos": 22958, "definition": "Outside contributors ...", "groups": {
        "all|all": {"repos": 22958, "first_answer_hours": Q(10), "answered_1d_share": Q(0.6)}},
        "newcomers": {"newcomers": 259586, "repos": 48745, "return_days": 90, "by_answer": [
            {"bucket": "within 1 day", "newcomers": 100000, "returned": 0.193, "merged": 0.5},
            {"bucket": "no answer", "newcomers": 20000, "returned": 0.08, "merged": 0.0}]}}
    for name, d in (("ci", ci), ("flow", flow), ("community", community)):
        (tmp_path / f"{name}-benchmarks.json").write_text(json.dumps(d), encoding="utf-8")
    return tmp_path


def test_the_report_states_numbers_from_the_files_with_their_counts(tmp_path):
    from mergescout.bench.report import build_report
    out = tmp_path / "out"
    build_report(bench_dir(tmp_path), out)
    text = (out / "report.md").read_text(encoding="utf-8")
    assert "4,025 repos" in text and "36,671 repos" in text and "259,586 newcomers" in text
    assert "5.0 min" in text and "15.0 min" in text  # the typical push wait overall and for Rust, from the files
    assert "Rust" in text.split("## Review flow")[0] and "CC BY 4.0" in text
    assert "33%" in text and "52%" in text  # coding-agent PRs vs people's outside PRs
    assert "11 points" in text  # the odds backtest


def test_every_number_in_the_tables_is_in_a_csv_that_recomputes_it(tmp_path):
    from mergescout.bench.report import build_report
    out = tmp_path / "out"
    build_report(bench_dir(tmp_path), out)
    rows = list(csv.DictReader((out / "ci.csv").open(encoding="utf-8")))
    rust = next(r for r in rows if r["language"] == "Rust" and r["size"] == "all")
    assert rust["repos"] == "400" and float(rust["median_s_p50"]) == 900.0
    assert not any("/" in v for r in rows for v in r.values() if v)  # no repo names, ever
    assert "pandas" not in (out / "report.md").read_text(encoding="utf-8")  # the recompute snippet needs only the stdlib


def test_small_groups_never_appear(tmp_path):
    from mergescout.bench.report import MIN_REPOS, build_report
    out = tmp_path / "out"
    build_report(bench_dir(tmp_path), out)
    rows = list(csv.DictReader((out / "ci.csv").open(encoding="utf-8")))
    assert all(int(r["repos"]) >= MIN_REPOS for r in rows)
