import argparse
import os
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from mergescout.config import load_config
from mergescout.github.releases import Releases
from mergescout.signals.evidence import TABLES, build_all
from mergescout.signals.silver import load_silver
from mergescout.store.sync import fetch_bronze


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m mergescout.signals", description="Build Tier 1 signals.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="Read all crawl batches and write signal tables as Parquet")
    b.add_argument("--from-releases", action="store_true", help="Download crawl bundles from releases first")
    b.add_argument("--out", default=None)
    c = sub.add_parser("check", help="Hand-check identity on 30 repos against owner files and public org members")
    c.add_argument("--signals", required=True)
    c.add_argument("--out", required=True)
    o = sub.add_parser("opendigger", help="Compare review times with OpenDigger")
    o.add_argument("--signals", required=True)
    o.add_argument("--repos", type=int, default=100)
    args = parser.parse_args(argv)

    if args.cmd in ("check", "opendigger"):
        return _validate(args)

    cfg = load_config()
    out = Path(args.out) if args.out else cfg.data_dir / "signals"
    con = prepare(cfg, out, args.from_releases, datetime.now(timezone.utc))
    if con is None:
        return 1
    write_bundle(con, out)
    con.close()
    return 0


def prepare(cfg, out: Path, from_releases: bool, now: datetime) -> duckdb.DuckDBPyConnection | None:
    # Silver + every signal table; None when there is no crawl data to build from.
    out.mkdir(parents=True, exist_ok=True)
    if from_releases:
        # Same store as the crawler's `store` command: MS_STORE_REPO, else the running repo.
        token = os.environ.get("MS_RELEASE_TOKEN")
        repo = os.environ.get("MS_STORE_REPO") or os.environ.get("GITHUB_REPOSITORY")
        if not token or not repo:
            print("Set MS_RELEASE_TOKEN and MS_STORE_REPO (or GITHUB_REPOSITORY) to read crawl releases.",
                  file=sys.stderr)
            return None
        fetch_bronze(Releases(token, repo), cfg.data_dir, log=lambda msg: print(msg, flush=True))
    # A file database lets DuckDB spill to disk instead of running out of memory on the runner.
    con = duckdb.connect(str(out / "work.duckdb"))
    con.execute("SET memory_limit = '4GB'")
    silver = load_silver(con, [cfg.data_dir, cfg.data_dir / "bronze"])
    print(f"silver: {silver}", flush=True)
    empty = [t for t in ("repo_meta", "prs", "issues") if not silver.get(t)]
    if empty:
        # A wrong store repo or token finds nothing; publishing that would replace the good bundle.
        print(f"No crawl data for {', '.join(empty)}; not building signals.", file=sys.stderr)
        con.close()
        return None
    print(f"signals: {build_all(con, now)}", flush=True)
    return con


def write_bundle(con: duckdb.DuckDBPyConnection, out: Path) -> Path:
    with tarfile.open(out / "signals.tar", "w") as tar:
        for table in TABLES:
            path = out / f"{table}.parquet"
            quoted = path.as_posix().replace("'", "''")
            con.execute(f"COPY {table} TO '{quoted}' (FORMAT parquet, COMPRESSION zstd)")
            tar.add(path, arcname=path.name)
    return out / "signals.tar"


def _validate(args) -> int:
    import httpx

    from mergescout.github.graphql import GitHubGraphQL
    from mergescout.signals.check import run_check, run_opendigger
    if args.cmd == "opendigger":
        with httpx.Client(timeout=60) as http:
            return 0 if run_opendigger(Path(args.signals), args.repos, http)["n"] else 1
    token = load_config().require_token().strip()
    with httpx.Client(timeout=60, headers={"Authorization": f"Bearer {token}"}) as http:
        run_check(Path(args.signals), Path(args.out), GitHubGraphQL(token, max_wait=120), http)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
