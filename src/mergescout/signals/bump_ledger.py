"""The upgrade ledger: how Dependabot and Renovate PRs for each package ended across the crawl (merged, failed CI
against these repos' usual, needed extra commits, closed, reverted), with counts so readers can judge the evidence."""
import re
from datetime import datetime, timedelta

import duckdb
import pyarrow as pa

from mergescout.signals.bumps import MANAGERS, _norm, parse_bump

WINDOW_DAYS = 180
REVERT_DAYS = 14
# Backtest flags. Closed matches the dossier (40% predicted 3x later closes on the crawl sample); CI uses the raw
# failure share until enough CI results exist to test the dossier's comparison with each repo's usual rate.
CLOSED_FLAG = 0.40
CI_FLAG = 0.40
CUTOFFS = (0.30, 0.40, 0.50, 0.60)
# Cells this thin are left out of the published file; readers see "not enough evidence" below 30 PRs from 10 repos.
MIN_PUBLISH = 3
DEFINITION = ("Dependabot and Renovate PRs opened in the last 180 days in crawled repos, per ecosystem, package and step "
              "(major, minor, patch; 0.x minor steps count as major). Merged; closed without merging (a bot closing its own "
              "PR for a newer version is not counted); CI failed on the last commit, next to the failures these repos' "
              "other bot PRs would predict; needed extra commits; reverted or rolled back within 14 days (a revert PR, GitHub's "
              "revert branch, or a branch naming the rollback). Repos that never merge bot PRs "
              "are left out. Package and versions come from titles, or from Dependabot branch names for older PRs.")
SUPERSEDE = timedelta(days=2)
# Renovate's "update dependency X" does not say npm or PyPI; the repo's main language does (marked as inferred).
LANGUAGE_ECOSYSTEM = {"Python": "pypi", "JavaScript": "npm", "TypeScript": "npm", "Vue": "npm", "Svelte": "npm",
                      "Astro": "npm", "CoffeeScript": "npm"}
# Renovate also names runners, runtimes and Docker images this way ("update dependency ubuntu to v24"): never guessed.
NOT_PACKAGES = {"ubuntu", "debian", "alpine", "centos", "fedora", "windows", "macos", "node", "nodejs", "node.js", "python",
                "golang", "go", "rust", "ruby", "java", "openjdk", "temurin", "dotnet", "nginx", "httpd", "postgres",
                "postgresql", "redis", "mysql", "mariadb", "mongo", "mongodb", "busybox", "docker", "kubernetes", "terraform"}
REVERT = re.compile(r'^\s*revert\s+"(?P<inner>.+)"\s*$', re.I)
BRANCH_VERSION = re.compile(r"^(?P<pkg>.+?)-(?P<ver>v?\d+(?:\.\d+)+[\w.+-]*)$")
RANGE_OPERATOR = re.compile(r"(?:-(?:gte|lte|gt|lt|neq|eq|tw|approx))+$")
# Names that can exist in each registry; anything else (a hook URL, "jdx/mise" read as PyPI) is not attributed.
VALID_NAME = {"pypi": re.compile(r"^[a-z0-9]([a-z0-9._-]*[a-z0-9])?$", re.I),
              "npm": re.compile(r"^(@[a-z0-9][\w.~-]*/)?[a-z0-9~][\w.~-]*$", re.I)}
FAILED = ("FAILURE", "ERROR")


def parse_branch(head: str | None) -> tuple[str, str, str] | None:
    """(ecosystem, package, new version) from a Dependabot branch, only where it can't be misread: PyPI names never
    contain "/", and an npm branch without folders; scoped npm names and folders look alike, so those are skipped."""
    parts = (head or "").split("/")
    if len(parts) < 3 or parts[0].lower() != "dependabot" or parts[-1].startswith("multi-"):
        return None
    eco, m = MANAGERS.get(parts[1]), BRANCH_VERSION.match(parts[-1])
    if not m or eco not in ("pypi", "npm") or (eco == "npm" and len(parts) != 3):
        return None
    # Range updates put the operator in the branch: "setuptools-scm-gte-8.0.0", "boto3-approx-eq-1.35.0"; extras
    # ("uvicorn[standard]" -> "uvicorn-standard-") can't be told apart from the name, so those are skipped.
    name = RANGE_OPERATOR.sub("", m["pkg"])
    return (eco, _norm(eco, name), m["ver"]) if valid_name(eco, name) and not name.endswith("-") else None


def valid_name(eco: str | None, name: str | None) -> bool:
    rule = VALID_NAME.get(eco or "")
    return bool(name) and (rule is None or bool(rule.match(name)))


def _key(name: str | None) -> str:
    # Names compared loosely when matching a revert to its bump (the revert title has no ecosystem).
    return re.sub(r"[-_.]+", "-", (name or "").lower())


def build_bump_prs(con: duckdb.DuckDBPyConnection) -> int:
    """One row per dependency-bot PR: parsed from its title, else from its branch (crawl files before titles were kept)."""
    rows = con.execute("""
        SELECT p.repo_id, p.number, p.created_at, p.merged_at, p.closed_at, p.state, p.author_login, p.head_ref, p.title,
               p.ci_state, p.commit_count, rm.language
        FROM prs p LEFT JOIN repo_meta rm USING (repo_id)
        WHERE regexp_matches(lower(coalesce(p.author_login, '')), '^(dependabot|renovate)')
           OR regexp_matches(lower(coalesce(p.head_ref, '')), '^(dependabot|renovate)')""").fetchall()
    out = []
    for repo, number, created, merged, closed, state, login, head, title, ci, commits, lang in rows:
        if title:
            b, source = parse_bump(title, head, login), "title"
            if b is None:
                continue  # Renovate's setup and pin PRs are not upgrades
        else:
            found = parse_branch(head)
            if not found:
                continue
            b = {"bot": "dependabot", "ecosystem": found[0], "package": found[1], "from_version": None,
                 "to_version": found[2], "bump": None, "grouped": False, "security": False, "closed_by_bot": False}
            source = "branch"
        inferred = b["ecosystem"] is None and b["package"] is not None and lang in LANGUAGE_ECOSYSTEM \
            and b["package"].lower() not in NOT_PACKAGES
        eco = LANGUAGE_ECOSYSTEM[lang] if inferred else b["ecosystem"]
        if b["package"] and not valid_name(eco, b["package"]):
            b = {**b, "package": None}
        out.append({"repo_id": repo, "number": number, "created_at": created, "merged_at": merged, "closed_at": closed,
                    "state": state, "bot": b["bot"], "ecosystem": eco, "package": _norm(eco, b["package"]) if b["package"] else None,
                    "from_version": b["from_version"], "to_version": b["to_version"], "bump": b["bump"],
                    "grouped": b["grouped"], "security": b["security"], "ci_state": ci, "commit_count": commits,
                    "superseded": bool(b["closed_by_bot"]), "reverted": False, "eco_inferred": inferred, "source": source})
    _mark_superseded(out)
    _mark_reverts(con, out)
    con.register("bump_prs_rows", pa.Table.from_pylist(out, schema=SCHEMA))
    con.execute("CREATE OR REPLACE TABLE bump_prs AS SELECT * FROM bump_prs_rows")
    con.unregister("bump_prs_rows")
    return len(out)


def _mark_superseded(rows: list[dict]) -> None:
    # A bot closes its own PR when a newer version arrives: a close next to a new PR for the same package isn't a rejection.
    opened = {}
    for r in rows:
        if r["package"]:
            opened.setdefault((r["repo_id"], r["package"]), []).append(r["created_at"])
    for r in rows:
        if r["package"] and r["merged_at"] is None and r["closed_at"] is not None:
            later = [t for t in opened[(r["repo_id"], r["package"])] if t > r["created_at"]]
            if any(abs(t - r["closed_at"]) <= SUPERSEDE for t in later):
                r["superseded"] = True


def _mark_reverts(con: duckdb.DuckDBPyConnection, rows: list[dict]) -> None:
    # A merged 'Revert "Bump X from A to B"' within 14 days of the bump's merge is the strongest sign it broke something.
    reverts = con.execute("""SELECT repo_id, merged_at, title FROM prs
                             WHERE merged_at IS NOT NULL AND title IS NOT NULL AND lower(title) LIKE 'revert%'""").fetchall()
    by_bump = {}
    for r in rows:
        if r["package"] and r["merged_at"] is not None:
            by_bump.setdefault((r["repo_id"], _key(r["package"]), r["to_version"]), []).append(r)
    for repo, when, title in reverts:
        m = REVERT.match(title)
        inner = parse_bump(m["inner"], "dependabot/", "dependabot") if m else None
        if not inner or not inner["package"]:
            continue
        for r in by_bump.get((repo, _key(inner["package"]), inner["to_version"]), []):
            if r["merged_at"] <= when <= r["merged_at"] + timedelta(days=REVERT_DAYS):
                r["reverted"] = True
    _mark_branch_rollbacks(con, rows)


# GitHub's Revert button names the branch after the PR it undoes: revert-<number>-<that PR's branch>.
REVERT_BRANCH = re.compile(r"(?i)^revert-(\d+)-")


def _branch_name(package: str) -> str:
    """How a branch names the package: a scoped npm name needs both parts (@types/node as types-node, never node), a Go
    module its last part without a /v2 suffix, any other name all of it."""
    parts = package.lstrip("@").split("/")
    if len(parts) > 1 and re.fullmatch(r"v\d+", parts[-1]):
        parts = parts[:-1]
    if package.startswith("@"):
        return "[-/_]".join(re.escape(p) for p in parts)
    return re.escape(parts[-1])


def _mark_branch_rollbacks(con: duckdb.DuckDBPyConnection, rows: list[dict]) -> None:
    """Rollbacks the crawl keeps no title for, from the merged PR's branch: GitHub's revert-<number> branches, and
    branches naming a rollback of the package followed by a version or nothing (rollback-litellm, downgrade-esbuild-0.24);
    on the crawl's sample this found 27 against the titles' 6 (bench/accuracy/deps)."""
    merged = {(r["repo_id"], r["number"]): r for r in rows if r["merged_at"] is not None}
    by_repo = {}
    for r in merged.values():
        if r["package"]:
            by_repo.setdefault(r["repo_id"], []).append(r)
    found = con.execute("""SELECT repo_id, merged_at, head_ref FROM prs
                           WHERE merged_at IS NOT NULL AND head_ref IS NOT NULL
                             AND regexp_matches(lower(head_ref), '(revert|downgrade|roll-?back)')""").fetchall()
    window = timedelta(days=REVERT_DAYS)
    for repo, when, ref in found:
        if m := REVERT_BRANCH.match(ref):
            r = merged.get((repo, int(m[1])))
            if r and r["merged_at"] <= when <= r["merged_at"] + window:
                r["reverted"] = True
            continue
        for r in by_repo.get(repo, ()):
            name = _branch_name(r["package"])
            if r["merged_at"] <= when <= r["merged_at"] + window and re.search(
                    rf"(?i)(revert|downgrade|roll-?back)[-/_]+{name}([-/_]v?\d|$)", ref):
                r["reverted"] = True


SCHEMA = pa.schema([
    ("repo_id", pa.int64()), ("number", pa.int32()), ("created_at", pa.timestamp("us", tz="UTC")),
    ("merged_at", pa.timestamp("us", tz="UTC")), ("closed_at", pa.timestamp("us", tz="UTC")), ("state", pa.string()),
    ("bot", pa.string()), ("ecosystem", pa.string()), ("package", pa.string()), ("from_version", pa.string()),
    ("to_version", pa.string()), ("bump", pa.string()), ("grouped", pa.bool_()), ("security", pa.bool_()),
    ("ci_state", pa.string()), ("commit_count", pa.int32()), ("superseded", pa.bool_()), ("reverted", pa.bool_()),
    ("eco_inferred", pa.bool_()), ("source", pa.string())])


def build_bump_ledger(con: duckdb.DuckDBPyConnection, now: datetime, window_days: int = WINDOW_DAYS) -> int:
    """Per ecosystem, package and step size over the window: outcomes with counts, and the CI failures these repos' other
    bot PRs would predict (each PR's repo rate, leaving the PR out), so a flaky repo doesn't blame a package."""
    con.execute("""
        CREATE OR REPLACE TABLE bump_ledger AS
        WITH quiet AS (
            -- Repos that never merge bot PRs ignore them; their closes say nothing about the package.
            SELECT repo_id FROM bump_prs GROUP BY repo_id HAVING count(*) >= 10 AND count(merged_at) = 0),
        base AS (
            SELECT repo_id, count(ci_state) AS n, count(*) FILTER (WHERE ci_state IN ('FAILURE', 'ERROR')) AS f
            FROM bump_prs GROUP BY repo_id),
        b AS (
            SELECT p.*, (p.ci_state IN ('FAILURE', 'ERROR'))::INT AS failed, base.n, base.f
            FROM bump_prs p JOIN base USING (repo_id)
            WHERE p.package IS NOT NULL AND p.created_at >= $since AND p.repo_id NOT IN (SELECT repo_id FROM quiet))
        SELECT ecosystem, package, coalesce(bump, 'unknown') AS bump,
               count(*) AS prs, count(DISTINCT repo_id) AS repos,
               count(merged_at) AS merged,
               count(*) FILTER (WHERE merged_at IS NULL AND state = 'CLOSED' AND NOT superseded) AS closed_unmerged,
               count(ci_state) AS ci_known, sum(failed) FILTER (WHERE ci_state IS NOT NULL) AS ci_failed,
               sum((f - failed)::DOUBLE / (n - 1)) FILTER (WHERE ci_state IS NOT NULL AND n > 1) AS expected_failed,
               count(*) FILTER (WHERE commit_count > 1) AS extra_commits,
               count(*) FILTER (WHERE reverted) AS reverted,
               bool_or(eco_inferred) AS eco_inferred, min(created_at) AS first_at, max(created_at) AS last_at
        FROM b GROUP BY ALL""", {"since": now - timedelta(days=window_days)})
    return con.execute("SELECT count(*) FROM bump_ledger").fetchall()[0][0]


def ledger_json(con: duckdb.DuckDBPyConnection, now: datetime) -> dict:
    """The ledger as the published file: every cell with a few PRs, with its counts."""
    cols = ("ecosystem", "package", "bump", "prs", "repos", "merged", "closed_unmerged", "ci_known", "ci_failed",
            "expected_failed", "extra_commits", "reverted", "eco_inferred")
    rows = con.execute(f"SELECT {', '.join(cols)} FROM bump_ledger WHERE prs >= $min ORDER BY ecosystem, package, bump",
                       {"min": MIN_PUBLISH}).fetchall()
    cells = [{k: (round(v, 2) if isinstance(v, float) else v) for k, v in zip(cols, r)} for r in rows]
    return {"built_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "definition": DEFINITION, "window_days": WINDOW_DAYS,
            "cells": cells}


def bump_backtest(con: duckdb.DuckDBPyConnection, now: datetime) -> dict:
    """Did packages flagged on older upgrades (opened 360-120 days ago) see more trouble on later ones (90-30 days ago)?
    Logged by the daily build so the dossier's thresholds are checked as evidence grows."""
    def cells(lo: int, hi: int) -> dict:
        rows = con.execute("""
            SELECT ecosystem, package, count(*), count(DISTINCT repo_id),
                   count(*) FILTER (WHERE merged_at IS NULL AND state = 'CLOSED' AND NOT superseded),
                   count(*) FILTER (WHERE merged_at IS NOT NULL OR (state = 'CLOSED' AND NOT superseded)),
                   count(ci_state), count(*) FILTER (WHERE ci_state IN ('FAILURE', 'ERROR'))
            FROM bump_prs WHERE package IS NOT NULL AND created_at >= $lo AND created_at < $hi GROUP BY ALL""",
            {"lo": now - timedelta(days=lo), "hi": now - timedelta(days=hi)}).fetchall()
        return {(r[0], r[1]): r[2:] for r in rows}
    early, later = cells(360, 120), cells(90, 30)
    strong = {k for k, v in early.items() if v[0] >= 30 and v[1] >= 10}
    out = {}
    for name, cut, flag, num, den in (("closed", CLOSED_FLAG, lambda v, c: v[3] and v[2] / v[3] >= c, 2, 3),
                                      ("ci", CI_FLAG, lambda v, c: v[4] >= 20 and v[5] / v[4] >= c, 5, 4)):
        def share(keys, num=num, den=den):
            d = sum(later[k][den] for k in keys if k in later)
            return round(sum(later[k][num] for k in keys if k in later) / d, 3) if d else None

        def run(c, flag=flag):
            flagged = {k for k in strong if flag(early[k], c)}
            f, o = share(flagged), share(strong - flagged)
            return {"flagged": len(flagged), "later_flagged": f, "later_others": o,
                    "ratio": round(f / o, 2) if f is not None and o else None}
        # Every cutoff, so the dossier's threshold is picked from data (40% gave 1.72x on 2026-10-19, below the 2x bar).
        out[name] = {"strong": len(strong), **run(cut),
                     "by_cutoff": {f"{int(c * 100)}%": {k: v for k, v in run(c).items() if k in ("flagged", "ratio")}
                                   for c in CUTOFFS}}
    return out
