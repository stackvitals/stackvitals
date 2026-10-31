"""`stackvitals sql "<query>"`: SQL over a repo's summaries (its data branch, or a folder) with DuckDB; each summary file
is a table named after it (prs, ci_jobs, tests)."""
import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

from stackvitals.ci import cli as ci_cli
from stackvitals.ci.action import BRANCH
from stackvitals.ci.api import APIError, ActionsAPI
from stackvitals.core.summary import FOLDER, table_types

# A summary file name from a data branch becomes a local file and a table name, so only plain names are taken.
SAFE_NAME = re.compile(r"[a-z0-9_]+\.jsonl")
HELP = "SQL over a repo's StackVitals summaries. Tables: prs, ci_jobs, tests (one row per PR, job or test)."


def _fetch(make_api, tok: str | None, repo: str, into: Path) -> Path | None:
    api = make_api(tok, repo, max_requests=20)
    try:
        manifest = json.loads(api.file(f"{FOLDER}/manifest.json", BRANCH))
    except (APIError, ValueError):
        return None
    folder = (into / FOLDER).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    files = manifest.get("files") if isinstance(manifest, dict) else None
    for name in (files if isinstance(files, (dict, list)) else []):
        target = folder / name if isinstance(name, str) and SAFE_NAME.fullmatch(name) else None
        if target is None or target.resolve().parent != folder:
            print(f"Skipped {name!r} in {repo}'s manifest: not a plain summary file name.", file=sys.stderr)
            continue
        target.write_bytes(api.file(f"{FOLDER}/{name}", BRANCH))
    return into


def _ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def main(argv: list[str] | None = None, make_api=ActionsAPI, tok: str | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stackvitals sql", description=HELP)
    parser.add_argument("query", help="the SQL to run, e.g. \"select repo, role, count(*) from prs group by all\"")
    parser.add_argument("--repo", action="append", default=[],
                        help="owner/name: read the summaries from its stackvitals-data branch (repeat for several repos)")
    parser.add_argument("--dir", action="append", default=[],
                        help="a folder holding summary/ (a clone of the data branch; repeat for several)")
    parser.add_argument("--json", action="store_true", help="print rows as JSON")
    args = parser.parse_args(argv)
    try:
        import duckdb
    except ImportError:
        print("DuckDB is needed for SQL: pip install 'stackvitals[sql]'", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="stackvitals-sql-") as tmp:
        sources = []
        if args.repo:
            tok = tok or ci_cli.token()
        for repo in args.repo:
            root = _fetch(make_api, tok, repo, Path(tmp) / repo.replace("/", "__"))
            if root is None:
                print(f"No summaries found in {repo}'s {BRANCH} branch (does StackVitals run there?).", file=sys.stderr)
                return 1
            sources.append((repo, root))
        for folder in args.dir or ([] if args.repo else ["."]):
            root = Path(folder)
            if not (root / FOLDER).is_dir():
                print(f"No summaries under {root} (expected a {FOLDER}/ folder).", file=sys.stderr)
                return 1
            sources.append((root.resolve().name, root))
        return _run(duckdb, sources, args.query, args.json)


def _run(duckdb, sources: list[tuple[str, Path]], query: str, as_json: bool) -> int:
    con = duckdb.connect()
    tables = sorted({p.stem for _label, root in sources for p in (root / FOLDER).glob("*.jsonl") if SAFE_NAME.fullmatch(p.name)})
    for name in tables:
        # One table per summary over every repo, with a `repo` column; repos missing a column get nulls (BY NAME).
        parts = []
        for label, root in sources:
            path = root / FOLDER / f"{name}.jsonl"
            if path.is_file() and path.stat().st_size:
                # CREATE VIEW takes no bound parameters, so the path and label are quoted as literals.
                literal = str(path).replace("\\", "/").replace("'", "''")
                types = table_types(name)
                spec = ", ".join(f"'{c}': '{t}'" for c, t in types.items()) if types else ""
                reader = (f"read_json('{literal}', format='newline_delimited', columns={{{spec}}})" if types
                          else f"read_json_auto('{literal}')")
                parts.append(f"SELECT '{label.replace(chr(39), chr(39) * 2)}' AS repo, * FROM {reader}")
        body = " UNION ALL BY NAME ".join(parts) if parts else "SELECT NULL AS repo, NULL AS empty WHERE false"
        # Tables, not views: the files are read now, before file access is switched off for the query.
        con.execute(f"CREATE TABLE {_ident(name)} AS {body}")
    # The query can't read, write or attach files, and can't switch that back on.
    con.execute("SET enable_external_access = false")
    con.execute("SET lock_configuration = true")
    try:
        cur = con.execute(query)
    except duckdb.Error as exc:
        print(f"SQL error: {exc}", file=sys.stderr)
        return 1
    columns = [d[0] for d in cur.description]
    rows = cur.fetchall()
    if as_json:
        print(json.dumps([dict(zip(columns, r)) for r in rows], default=str, indent=1))
        return 0
    widths = [max(len(str(c)), *(len(str(r[i])) for r in rows)) if rows else len(str(c)) for i, c in enumerate(columns)]
    print("  ".join(str(c).ljust(w) for c, w in zip(columns, widths)))
    for r in rows:
        print("  ".join(str(v).ljust(w) for v, w in zip(r, widths)))
    return 0
