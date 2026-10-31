from pathlib import Path

import duckdb
import pyarrow as pa

from mergescout.crawl.writer import SCHEMAS

# One row per key survives: the most recently fetched copy.
KEYS = {"repo_meta": ["repo_id"], "prs": ["repo_id", "number"], "issues": ["repo_id", "number"],
        "comments": ["repo_id", "number", "comment_id", "created_at"], "closed_issues": ["repo_id", "number"],
        "issue_events": ["repo_id", "number", "event", "observed_at"]}


def load_silver(con: duckdb.DuckDBPyConnection, roots: list[Path]) -> dict[str, int]:
    con.execute("SET TimeZone = 'UTC'")  # day counts must not depend on the machine's clock zone
    counts = {}
    for table, key in KEYS.items():
        files = sorted(str(p) for root in roots for p in (root / "crawl" / table).glob("*.parquet"))
        con.register(f"{table}_empty", pa.Table.from_pylist([], schema=SCHEMAS[table]))
        source = f"SELECT * FROM {table}_empty"
        if files:
            con.read_parquet(files, union_by_name=True).create_view(f"{table}_raw", replace=True)
            # BY NAME fills columns that older batches do not have with nulls.
            source += f" UNION ALL BY NAME SELECT * FROM {table}_raw"
        con.execute(f"""
            CREATE OR REPLACE TABLE {table} AS
            SELECT * EXCLUDE (rn) FROM (
                SELECT *, row_number() OVER (PARTITION BY {", ".join(key)}
                                             ORDER BY fetched_at DESC NULLS LAST, run_id DESC) AS rn
                FROM ({source})) WHERE rn = 1""")
        # fetchall, not fetchone: DuckDB 2 refuses any other work while a result is half read.
        counts[table] = con.execute(f"SELECT count(*) FROM {table}").fetchall()[0][0]
    return counts
