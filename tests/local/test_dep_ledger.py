from datetime import datetime, timedelta, timezone

import duckdb

from mergescout.signals.bump_ledger import build_bump_ledger, build_bump_prs, parse_branch

NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
COLS = ("repo_id", "number", "created_at", "merged_at", "closed_at", "state", "author_login", "head_ref", "title",
        "ci_state", "commit_count")


def day(d):
    return NOW - timedelta(days=d)


def con_with(prs, langs=None):
    con = duckdb.connect()
    con.execute("""CREATE TABLE prs (repo_id BIGINT, number INT, created_at TIMESTAMPTZ, merged_at TIMESTAMPTZ,
        closed_at TIMESTAMPTZ, state VARCHAR, author_login VARCHAR, head_ref VARCHAR, title VARCHAR, ci_state VARCHAR,
        commit_count INT)""")
    con.executemany("INSERT INTO prs VALUES (?,?,?,?,?,?,?,?,?,?,?)", prs)
    con.execute("CREATE TABLE repo_meta (repo_id BIGINT, language VARCHAR)")
    if langs:
        con.executemany("INSERT INTO repo_meta VALUES (?,?)", list(langs.items()))
    return con


def bot(repo, n, pkg, old, new, d=20, merged=True, ci="SUCCESS", commits=1, eco="pip"):
    title = f"Bump {pkg} from {old} to {new}"
    return [repo, n, day(d), day(d - 1) if merged else None, day(d - 1), "MERGED" if merged else "CLOSED", "dependabot",
            f"dependabot/{eco}/{pkg}-{new}", title, ci, commits]


def test_older_prs_fall_back_to_unambiguous_dependabot_branch_names():
    assert parse_branch("dependabot/pip/backend/requests-2.32.3") == ("pypi", "requests", "2.32.3")
    assert parse_branch("dependabot/npm_and_yarn/lodash-4.17.21") == ("npm", "lodash", "4.17.21")
    # A folder or an npm scope look the same in a branch name, and group branches end in a hash: not guessed.
    assert parse_branch("dependabot/npm_and_yarn/frontend/babel/core-7.24.0") is None
    assert parse_branch("dependabot/npm_and_yarn/npm_and_yarn-903ed42b99") is None


def test_bump_prs_parse_titles_infer_renovate_ecosystems_and_mark_superseded_closes():
    rows = [bot(1, 1, "requests", "2.31.0", "2.32.0", d=30, merged=False),
            bot(1, 2, "requests", "2.31.0", "2.32.3", d=29),  # opened right after #1 closed: #1 was superseded
            [2, 5, day(10), day(9), day(9), "MERGED", "renovate[bot]", "renovate/react-19.x", "Update dependency react to v19",
             "FAILURE", 1],
            [3, 7, day(10), None, None, "MERGED", "dependabot", "dependabot/pip/flask-3.1.0", None, None, None]]
    con = con_with(rows, {2: "TypeScript"})
    build_bump_prs(con)
    got = {(r[0], r[1]): r for r in con.execute(
        "SELECT repo_id, number, ecosystem, package, bump, superseded, eco_inferred, source FROM bump_prs").fetchall()}
    assert got[(1, 1)][5] is True and got[(1, 2)][5] is False and got[(1, 2)][4] == "minor"
    assert got[(2, 5)][2:4] == ("npm", "react") and got[(2, 5)][6] is True
    assert got[(3, 7)][3] == "flask" and got[(3, 7)][7] == "branch"


def test_the_ledger_counts_outcomes_against_these_repos_usual_ci_and_finds_reverts():
    rows = []
    # 12 repos take the same django minor bump; in 6 of them it fails CI, while their other bot PRs pass.
    for r in range(1, 13):
        rows.append(bot(r, 1, "django", "5.1.0", "5.2.0", ci="FAILURE" if r <= 6 else "SUCCESS", commits=3 if r <= 4 else 1))
        rows += [bot(r, 10 + k, f"other{k}", "1.0.0", "1.0.1") for k in range(4)]
    # Repo 1 reverted the bump four days later.
    rows.append([1, 50, day(16), day(15), day(15), "MERGED", "ann", "revert-1-django", 'Revert "Bump django from 5.1.0 to 5.2.0"',
                 None, None])
    con = con_with(rows)
    build_bump_prs(con)
    build_bump_ledger(con, NOW)
    cell = con.execute("""SELECT prs, repos, merged, ci_known, ci_failed, expected_failed, extra_commits, reverted
                          FROM bump_ledger WHERE package = 'django' AND bump = 'minor'""").fetchone()
    prs, repos, merged, ci_known, ci_failed, expected, extra, reverted = cell
    assert (prs, repos, merged, ci_known, ci_failed, extra, reverted) == (12, 12, 12, 12, 6, 4, 1)
    assert expected < 1.5  # these repos' other bot PRs pass, so 6 failures are far above their usual


def test_repos_that_never_merge_bot_prs_are_left_out():
    rows = [bot(9, k, f"p{k}", "1.0.0", "1.1.0", merged=False) for k in range(12)]
    rows += [bot(1, 1, "p0", "1.0.0", "1.1.0")]
    con = con_with(rows)
    build_bump_prs(con)
    build_bump_ledger(con, NOW)
    assert con.execute("SELECT repos FROM bump_ledger WHERE package = 'p0'").fetchone()[0] == 1


def test_the_daily_snapshot_writes_the_ledger_file_and_survives_its_failure(tmp_path, monkeypatch):
    import json

    import mergescout.signals.bump_ledger as bl
    import mergescout.signals.deps_map as dm
    import mergescout.signals.osv as osv
    from mergescout.snapshot.__main__ import write_extras
    # The later extras ask deps.dev and OSV; a unit test never goes to the network.
    monkeypatch.setattr(dm, "refresh_map", lambda packages, previous, now, **kw: {})
    monkeypatch.setattr(osv, "refresh_vulns", lambda packages, previous, now, **kw: {"records": {}, "packages": {}})
    rows = [bot(r, 1, "django", "5.1.0", "5.2.0") for r in range(1, 5)]
    said = []
    write_extras(con_with(rows), tmp_path, NOW, log=said.append)
    data = json.loads((tmp_path / "deps-ledger.json").read_text(encoding="utf-8"))
    cell = next(c for c in data["cells"] if c["package"] == "django")
    assert cell["prs"] == 4 and cell["bump"] == "minor" and data["definition"] and any("upgrade ledger" in s for s in said)

    def boom(*a, **k):
        raise RuntimeError("bad batch")
    monkeypatch.setattr(bl, "build_bump_prs", boom)
    said.clear()
    write_extras(con_with(rows), tmp_path / "x", NOW, log=said.append)
    assert any("upgrade ledger skipped" in s for s in said)


def test_range_update_branches_drop_the_operator_from_the_name():
    # "Update setuptools-scm requirement from >=7 to >=8" lives on dependabot/pip/setuptools-scm-gte-8.0.0.
    assert parse_branch("dependabot/pip/setuptools-scm-gte-8.0.0") == ("pypi", "setuptools-scm", "8.0.0")
    assert parse_branch("dependabot/pip/pandas-gte-1.5-and-lt-2.3")[1] == "pandas"


def test_the_daily_snapshot_refreshes_the_package_map_from_yesterdays_file(tmp_path, monkeypatch):
    import json

    import mergescout.signals.deps_map as dm
    from mergescout.snapshot.__main__ import write_extras
    (tmp_path / "deps-map.json").write_text(json.dumps({"packages": {"pypi:django": {"repo": "django/django"}}}), encoding="utf-8")
    seen = {}

    def fake_refresh(packages, previous, now, gql=None, **kw):
        seen.update(packages=sorted(packages), previous=previous)
        return {"pypi:django": {"repo": "django/django", "link": "verified", "fetched_at": "x"}}
    monkeypatch.setattr(dm, "refresh_map", fake_refresh)
    import mergescout.signals.osv as osv
    monkeypatch.setattr(osv, "refresh_vulns", lambda packages, previous, now, **kw: {"records": {}, "packages": {}})
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("MS_RELEASE_TOKEN", raising=False)
    said = []
    write_extras(con_with([bot(r, 1, "django", "5.1.0", "5.2.0") for r in range(1, 5)]), tmp_path, NOW, log=said.append)
    assert seen["packages"] == [("pypi", "django")] and seen["previous"] == {"pypi:django": {"repo": "django/django"}}
    data = json.loads((tmp_path / "deps-map.json").read_text(encoding="utf-8"))
    assert data["packages"]["pypi:django"]["link"] == "verified" and any("package map" in s for s in said)
    # The crawler reads this list to crawl package source repos first (verified or checked links only).
    assert (tmp_path / "watch-repos.txt").read_text(encoding="utf-8").split() == ["django/django"]


def test_branch_names_with_compound_ranges_or_extras_are_not_misread():
    # Real data: "boto3-approx" and "uvicorn-standard-" reached the package map.
    assert parse_branch("dependabot/pip/boto3-approx-eq-1.35.0")[1] == "boto3"
    assert parse_branch("dependabot/pip/uvicorn-standard--0.30.0") is None


def test_names_that_cannot_exist_in_the_registry_are_not_attributed():
    # Real data: a pre-commit hook URL, "jdx/mise" and "keycloak/keycloak" were read as PyPI or npm packages.
    rows = [[1, k, day(10), day(9), day(9), "MERGED", "renovate[bot]", f"renovate/x-{k}", title, None, None]
            for k, title in enumerate(["Update dependency jdx/mise to v2024.1.0",
                                       "Update dependency https://github.com/astral-sh/ruff-pre-commit to v0.6.0",
                                       "Update dependency requests to v2.32.3"])]
    con = con_with(rows, {1: "Python"})
    build_bump_prs(con)
    assert [r[0] for r in con.execute("SELECT package FROM bump_prs ORDER BY number").fetchall()] == [None, None, "requests"]


def test_a_not_equal_range_in_the_branch_is_dropped_too():
    # Real data: "websocket-client-neq" reached the map ("!=" is written "neq").
    assert parse_branch("dependabot/pip/websocket-client-neq-1.8.0")[1] == "websocket-client"


def test_the_daily_backtest_says_whether_early_flags_predicted_later_trouble():
    from mergescout.signals.bump_ledger import bump_backtest
    rows = []
    # Package "bad": closed in 2 of 3 PRs early and later; "good": merged; 12 repos each, so cells are strong.
    for r in range(12):
        for k, d in enumerate((300, 250, 200)):
            rows.append(bot(r, 100 + k, "bad", "1.0.0", f"1.{k + 1}.0", d=d, merged=k == 0))
            rows.append(bot(r, 200 + k, "good", "1.0.0", f"1.{k + 1}.0", d=d))
        rows.append(bot(r, 300, "bad", "1.0.0", "1.9.0", d=60, merged=False))
        rows.append(bot(r, 301, "good", "1.0.0", "1.9.0", d=60))
    con = con_with(rows)
    build_bump_prs(con)
    out = bump_backtest(con, NOW)
    assert {k: out["closed"][k] for k in ("strong", "flagged", "later_flagged", "later_others", "ratio")} ==         {"strong": 2, "flagged": 1, "later_flagged": 1.0, "later_others": 0.0, "ratio": None}
    assert out["ci"]["strong"] == 2


def test_runtime_and_os_images_are_never_guessed_as_npm_or_pypi_packages():
    # Hand-check: Renovate's "Update dependency ubuntu to v24" (a runner or Docker image) counted as npm's "ubuntu".
    rows = [[1, n, day(10), day(9), day(9), "MERGED", "renovate[bot]", f"renovate/{pkg}-{n}.x", f"Update dependency {pkg} to v{n}",
             "SUCCESS", 1] for n, pkg in ((24, "ubuntu"), (22, "node"), (3, "python"), (2, "react-query"))]
    con = con_with(rows, {1: "TypeScript"})
    build_bump_prs(con)
    got = dict(con.execute("SELECT number, ecosystem FROM bump_prs").fetchall())
    assert got[24] is None and got[22] is None and got[3] is None and got[2] == "npm"


def test_a_failed_backtest_is_logged_as_the_backtest_not_the_ledger(tmp_path, monkeypatch):
    import mergescout.signals.bump_ledger as bl
    import mergescout.signals.deps_map as dm
    import mergescout.signals.osv as osv
    from mergescout.snapshot.__main__ import write_extras
    monkeypatch.setattr(dm, "refresh_map", lambda packages, previous, now, **kw: {})
    monkeypatch.setattr(osv, "refresh_vulns", lambda packages, previous, now, **kw: {"records": {}, "packages": {}})

    def boom(*a, **k):
        raise RuntimeError("thin window")
    monkeypatch.setattr(bl, "bump_backtest", boom)
    said = []
    write_extras(con_with([bot(1, 1, "django", "5.1.0", "5.2.0")]), tmp_path, NOW, log=said.append)
    assert (tmp_path / "deps-ledger.json").exists() and any("upgrade backtest skipped" in s for s in said)
    assert not any("upgrade ledger skipped" in s for s in said)


def test_the_backtest_reports_each_cutoff_so_the_dossier_threshold_comes_from_data():
    # Real data: at 40% closed the flagged packages saw 1.72x the later trouble, below the 2x bar; other cutoffs may clear it.
    from mergescout.signals.bump_ledger import bump_backtest
    rows = []
    for r in range(12):
        for k, d in enumerate((300, 250, 200)):
            rows.append(bot(r, 100 + k, "bad", "1.0.0", f"1.{k + 1}.0", d=d, merged=k == 0))  # 2 of 3 closed early
            rows.append(bot(r, 200 + k, "mid", "1.0.0", f"1.{k + 1}.0", d=d, merged=k != 0))  # 1 of 3 closed early
            rows.append(bot(r, 300 + k, "good", "1.0.0", f"1.{k + 1}.0", d=d))
        rows.append(bot(r, 400, "bad", "1.0.0", "1.9.0", d=60, merged=False))
        rows.append(bot(r, 401, "mid", "1.0.0", "1.9.0", d=60, merged=r % 2 == 0))
        rows.append(bot(r, 402, "good", "1.0.0", "1.9.0", d=60, merged=r % 4 != 0))
    con = con_with(rows)
    build_bump_prs(con)
    cuts = bump_backtest(con, NOW)["closed"]["by_cutoff"]
    assert cuts["30%"] == {"flagged": 2, "ratio": 3.0} and cuts["40%"] == {"flagged": 1, "ratio": 2.67}
    assert set(cuts) == {"30%", "40%", "50%", "60%"}


def _rows_of(con):
    return {(r[0], r[1]): r[2] for r in con.execute("SELECT repo_id, number, reverted FROM bump_prs").fetchall()}


def test_github_revert_branches_and_named_rollbacks_count_with_no_title():
    rows = [bot(1, 10, "requests", "2.31.0", "2.32.0"), bot(2, 20, "litellm", "1.0.0", "1.1.0"),
            bot(3, 30, "django", "5.1.0", "5.2.0"), bot(4, 40, "tar", "6.0.0", "7.0.0"),
            bot(5, 50, "uuid", "10.0.0", "11.0.0", d=40)]
    rows += [
        # GitHub's Revert button names the branch after the PR it undoes; older crawl files kept no title for it.
        [1, 11, day(17), day(16), day(16), "MERGED", "ann", "revert-10-dependabot/pip/requests-2.32.0", None, None, 1],
        [2, 21, day(17), day(16), day(16), "MERGED", "bo", "igitman/rollback-litellm", None, None, 1],
        # Another package that starts with the same name, and a revert of an unrelated PR: neither counts.
        [3, 31, day(17), day(16), day(16), "MERGED", "cy", "revert-django-csp", None, None, 1],
        [4, 41, day(17), day(16), day(16), "MERGED", "di", "revert-4447-fix-pipe-start", None, None, 1],
        # A rollback long after the bump says nothing about it.
        [5, 51, day(5), day(4), day(4), "MERGED", "ed", "revert-50-dependabot/npm_and_yarn/uuid-11.0.0", None, None, 1]]
    con = con_with(rows)
    build_bump_prs(con)
    got = _rows_of(con)
    assert got[(1, 10)] and got[(2, 20)]
    assert not got[(3, 30)] and not got[(4, 40)] and not got[(5, 50)]
