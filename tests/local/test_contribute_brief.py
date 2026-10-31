"""Phase 9 M1: a short repo brief for agents, built only from measured history."""
from datetime import datetime, timedelta, timezone

NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)


def at(days, hours=0):
    return (NOW - timedelta(days=days, hours=-hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def pr(n, au, assoc, days, merged=True, paths=("src/db/pool.py", "tests/test_pool.py"), lines=40, reviewer="maint",
       review_after=6, kind="User"):
    ev = [["review", at(days, review_after), reviewer, "APPROVED", "MEMBER", "User"]] if reviewer else []
    if merged:
        ev.append(["merged", at(days, 30), reviewer or "maint"])
    return {"t": "pr", "n": n, "ti": f"PR {n}", "draft": False, "st": "MERGED" if merged else "CLOSED", "cr": at(days),
            "up": at(days, 30), "mg": at(days, 30) if merged else None, "cl": at(days, 30), "add": lines, "del": 0,
            "files": len(paths), "au": au, "at": kind, "as": assoc, "rq": [], "ev": ev, "cm": [], "ci": "SUCCESS",
            "lc": at(days), "paths": list(paths)}


def history():
    prs = [pr(i, "dev", "MEMBER", 10 + i) for i in range(12)]
    # Outside contributors: 8 of 20 merged; the big ones mostly closed.
    prs += [pr(100 + i, f"o{i}", "NONE", 20 + i, merged=i < 8, lines=60 if i < 10 else 900,
               paths=("docs/guide.md",)) for i in range(20)]
    prs += [pr(200, "dependabot[bot]", "NONE", 5, kind="Bot", paths=("requirements.txt",))]
    return {"open": [], "closed": prs}


CI = {"jobs": [{"workflow": ".github/workflows/ci.yml", "job": "test (windows)", "state": "flaky", "flake_events": 9,
                "runs": 111, "owners": ["@acme/ci"]},
               {"workflow": ".github/workflows/ci.yml", "job": "lint", "state": "ok", "flake_events": 0, "runs": 111}],
      "tests": [{"id": "tests/test_net.py::test_fetch", "state": "flaky", "flake_events": 4, "runs": 60}]}


def test_the_brief_holds_measured_facts_each_with_its_sample_size():
    from stackvitals.contribute.brief import build_brief
    b = build_brief("acme/app", history(), {"codeowners": "/src/db/ @acme/db\n", "language": "Python", "stars": 5000},
                    {}, CI, None, NOW)
    o = b["outside"]
    assert (o["closed"], o["merged"], o["rate"]) == (20, 8, 0.4) and o["low_sample"] is True
    assert [s["size"] for s in o["by_size"]] == ["under 150 lines", "over 500 lines"] and o["by_size"][1]["rate"] == 0.0
    db = next(a for a in b["areas"] if a["area"] == "src/db")
    assert db["merged_prs"] == 12 and db["include"]["tests"] == 1.0 and db["owners"] == ["@acme/db"]
    # One reviewer only: the folder's review speed would be one person's, so it is left out.
    assert db["reviewers"][0] == {"login": "maint", "reviews": 12} and db["first_review_hours"] is None
    assert [f["name"] for f in b["flaky"]] == ["ci.yml / test (windows)", "tests/test_net.py::test_fetch"]


def test_the_brief_is_short_and_says_where_each_number_comes_from():
    from stackvitals.contribute.brief import build_brief, render
    b = build_brief("acme/app", history(), {"codeowners": "/src/db/ @acme/db\n", "language": "Python", "stars": 5000},
                    {}, CI, None, NOW)
    text = render(b)
    lines = [x for x in text.splitlines() if x.strip()]
    assert len(lines) <= 40
    assert "8 of 20" in text and "src/db" in text and "@acme/db" in text and "9 of 111 runs" in text
    assert "re-run" in text.lower() and "StackVitals" in text


def test_peer_context_places_the_repo_among_similar_repos():
    from stackvitals.contribute.brief import build_brief
    bench = {"built_at": "2026-10-19", "groups": {"Python|1k-10k": {"repos": 400, "outsider_merge_rate": {
        "repos": 400, "p10": 0.2, "p25": 0.4, "p50": 0.6, "p75": 0.75, "p90": 0.9}}}}
    o = build_brief("acme/app", history(), {"language": "Python", "stars": 5000}, {}, None, bench, NOW)["outside"]
    assert o["peers"]["typical"] == 0.6 and "Python repos with 1k-10k stars" in o["peers"]["group"]
    # Pulling toward similar repos made estimates worse on the crawl (13,011 repos), so there is no shrunk rate.
    assert "shrunk" not in o and "estimate" not in o


def test_thin_history_says_so_instead_of_guessing():
    from stackvitals.contribute.brief import build_brief, render
    b = build_brief("acme/new", {"open": [], "closed": [pr(1, "o1", "NONE", 3)]}, {}, {}, None, None, NOW)
    assert b["areas"] == [] and b["outside"]["closed"] == 1
    assert "not enough history" in render(b).lower()


def test_writing_the_brief_keeps_the_rest_of_agents_md_and_adds_path_files(tmp_path):
    from stackvitals.contribute.brief import build_brief, write_files
    b = build_brief("acme/app", history(), {"codeowners": "/src/db/ @acme/db\n"}, {}, CI, None, NOW)
    (tmp_path / "AGENTS.md").write_text("# Our own notes\n\nRun make test.\n", encoding="utf-8")
    written = write_files(b, tmp_path)
    write_files(b, tmp_path)  # a second run replaces its section, never adds another
    agents = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.startswith("# Our own notes") and agents.count("<!-- stackvitals:brief -->") == 1
    path_file = next((tmp_path / ".github" / "instructions").glob("stackvitals-src-db-*.instructions.md"))
    assert 'applyTo: "src/db/**"' in path_file.read_text(encoding="utf-8")
    assert str(path_file.relative_to(tmp_path)).replace("\\", "/") in written


def test_the_command_prints_the_brief_and_writes_files_only_when_asked(tmp_path, capsys):
    from stackvitals.contribute.cli import main
    fake = lambda repo, tok, now, months, ci_days: (history(), {"codeowners": "/src/db/ @acme/db\n"}, {}, CI, None, "test")  # noqa: E731
    assert main(["acme/app"], now=NOW, tok="t", gather_fn=fake) == 0
    assert "## How changes get merged in acme/app" in capsys.readouterr().out and not (tmp_path / "AGENTS.md").exists()
    assert main(["acme/app", "--write", str(tmp_path)], now=NOW, tok="t", gather_fn=fake) == 0
    assert (tmp_path / "AGENTS.md").exists()


def test_stackvitals_contribute_brief_is_routed_and_mergescout_commands_still_work(monkeypatch):
    import stackvitals.contribute.cli as brief_cli
    from stackvitals import cli
    seen = {}
    monkeypatch.setattr(brief_cli, "main", lambda rest: seen.setdefault("brief", rest) and 0)
    cli.main(["contribute", "brief", "acme/app"])
    assert seen["brief"] == ["acme/app"]
    import mergescout.cli as ms
    monkeypatch.setattr(ms, "main", lambda rest: seen.setdefault("ms", rest) and 0)
    cli.main(["contribute", "find", "--lang", "python"])
    assert seen["ms"] == ["find", "--lang", "python"]


def test_changelog_folders_become_one_repo_line_and_weak_asks_are_dropped():
    # Real data (pypa/pip): "news/" (changelog fragments) showed as a folder with "a changelog entry (100%)",
    # and "tests (9% of 305 reviewed PRs)" was shown as something maintainers "most often ask for".
    from stackvitals.contribute.brief import build_brief, render
    data = history()
    for p in data["closed"][:12]:
        p["paths"] = p["paths"] + [f"news/{p['n']}.bugfix.rst"]
    asks = {p["n"]: [["tests", "src/db"]] for p in data["closed"][:1]}
    b = build_brief("acme/app", data, {}, asks, None, None, NOW)
    assert "news" not in [a["area"] for a in b["areas"]] and b["repo_habits"]["include"]["changelog"] > 0.3
    text = render(b)
    assert "changelog entry" in text.split("###")[0]  # said once, at the top
    assert "Maintainers most often ask for" not in text  # 1 of 12 PRs is not a habit


def test_the_brief_quotes_how_good_its_estimate_is_and_how_agent_prs_fare_nearby():
    from stackvitals.contribute.brief import build_brief, render
    bench = {"built_at": "2026-10-19", "groups": {"Python|1k-10k": {"repos": 400, "outsider_merge_rate": {
        "repos": 400, "p10": 0.2, "p25": 0.4, "p50": 0.6, "p75": 0.75, "p90": 0.9}}},
        "odds_backtest": {"repos": 4210, "prs": 51000, "mae": {"raw": 0.12, "calibrated": 0.09, "typical_only": 0.16},
                          "calibration_raw": [{"bin": "0.4-0.5", "prs": 900, "predicted": 0.44, "observed": 0.3}]},
        "agent_prs": {"Python|1k-10k": {"repos_with_agent_prs": 120, "agent": {"decided": 900, "merged": 0.33},
                                        "outsider": {"decided": 30000, "merged": 0.52}}}}
    b = build_brief("acme/app", history(), {"language": "Python", "stars": 5000}, {}, None, bench, NOW)
    text = render(b)
    assert "about 30% get merged within 3 months" in text and "4210 repos" in text and "9 points" in text
    assert "often started by the repos' own maintainers" in text
    assert "coding agents" in text and "33%" in text and "n=900" in text and "52%" in text


def test_the_estimate_is_the_repos_own_rate_corrected_by_the_crawl():
    from stackvitals.contribute.brief import build_brief, render
    bench = {"odds_backtest": {"repos": 13011, "prs": 136629, "mae": {"calibrated": 0.18},
                               "calibration_raw": [{"bin": "0.4-0.5", "prs": 9000, "predicted": 0.45, "observed": 0.31}]}}
    b = build_brief("acme/app", history(), {}, {}, None, bench, NOW)
    assert b["outside"]["estimate"] == 0.31
    text = render(b)
    assert "about 31% get merged within 3 months" in text and "13011 repos" in text and "18 points" in text
