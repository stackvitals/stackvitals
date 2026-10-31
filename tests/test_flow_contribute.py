"""Contribute: the repo brief for agents and the public report, end to end."""
import csv
import json
from datetime import datetime, timedelta, timezone

from mergescout.bench.report import MIN_REPOS, build_report
from stackvitals.contribute.brief import build_brief, render, write_files

NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)


def at(days, hours=0):
    return (NOW - timedelta(days=days, hours=-hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def pr(n, au, assoc, days, merged=True, paths=("src/db/pool.py", "tests/test_pool.py", "news/1.bugfix"), lines=40):
    ev = [["review", at(days, 6), "maint", "APPROVED", "MEMBER", "User"]] + ([["merged", at(days, 30), "maint"]] if merged else [])
    return {"t": "pr", "n": n, "ti": f"PR {n}", "draft": False, "st": "MERGED" if merged else "CLOSED", "cr": at(days),
            "up": at(days, 30), "mg": at(days, 30) if merged else None, "cl": at(days, 30), "add": lines, "del": 0,
            "files": len(paths), "au": au, "at": "User", "as": assoc, "rq": [], "ev": ev, "cm": [], "ci": "SUCCESS",
            "lc": at(days), "paths": list(paths)}


def history():
    prs = [pr(i, "dev", "MEMBER", 10 + i) for i in range(12)]
    prs += [pr(100 + i, f"o{i}", "NONE", 20 + i, merged=i < 8, paths=("docs/guide.md",)) for i in range(20)]
    return {"open": [], "closed": prs}


def test_the_brief_is_short_measured_and_written_without_touching_the_rest_of_agents_md(tmp_path):
    ci = {"jobs": [{"workflow": ".github/workflows/ci.yml", "job": "test", "state": "flaky", "flake_events": 9, "runs": 111}]}
    b = build_brief("acme/app", history(), {"codeowners": "/src/db/ @acme/db\n"}, {}, ci, None, NOW)
    text = render(b)
    assert len([x for x in text.splitlines() if x.strip()]) <= 40
    assert "8 of 20" in text and "9 of 111 runs" in text and "@acme/db" in text and "@maint (12 reviews)" in text
    assert "first review: median" not in text  # one reviewer's speed is never shown alone
    # Real data (pypa/pip): a changelog-fragment folder (news/) is one repo-wide line, not a folder of its own.
    assert "news" not in [a["area"] for a in b["areas"]] and "changelog entry" in text.split("###")[0]
    (tmp_path / "AGENTS.md").write_text("# Ours\n", encoding="utf-8")
    write_files(b, tmp_path)
    write_files(b, tmp_path)
    agents = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.startswith("# Ours") and agents.count("<!-- stackvitals:brief -->") == 1
    assert len(list((tmp_path / ".github" / "instructions").glob("stackvitals-src-db-*.instructions.md"))) == 1


def test_the_report_comes_only_from_the_published_files_and_hides_small_groups(tmp_path):
    q = {"repos": 100, "p10": 60, "p25": 120, "p50": 300, "p75": 600, "p90": 1200}
    ci = {"built_at": "2026-10-19T00:00:00Z", "repos": 4025, "definition": "per push", "groups": {
        "all|all": {"repos": 4025, "median_s": q, "first_try_share": {**q, "p50": 0.93}},
        "Rust|all": {"repos": 334, "median_s": {**q, "p50": 424}}, "Zig|all": {"repos": MIN_REPOS - 1, "median_s": q}}}
    (tmp_path / "ci-benchmarks.json").write_text(json.dumps(ci), encoding="utf-8")
    build_report(tmp_path, tmp_path / "out")
    text = (tmp_path / "out" / "report.md").read_text(encoding="utf-8")
    rows = list(csv.DictReader((tmp_path / "out" / "ci.csv").open(encoding="utf-8")))
    assert "4,025 repos" in text and "7.1 min" in text and "Zig" not in text
    assert {r["language"] for r in rows} == {"all", "Rust"}
