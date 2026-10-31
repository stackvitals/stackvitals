import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import orjson

from mergescout.config import load_config
from mergescout.github.graphql import GitHubGraphQL, GraphQLError
from mergescout.measure.api_cost import measure_repo
from mergescout.measure.count_repos import count_repos, listing_requests
from mergescout.measure.jsonl import append_jsonl, read_jsonl
from mergescout.measure.report import render_markdown, summarize
from mergescout.measure.sample import build_sample_queries, collect_sample


def run_api_cost(gql, sample: list[dict], results_path: Path, now: datetime, limit: int | None = None) -> int:
    done = {r["repo"] for r in read_jsonl(results_path)}
    measured = 0
    for entry in sample:
        if entry["repo"] in done:
            continue
        if limit is not None and measured >= limit:
            break
        try:
            record = measure_repo(gql, entry["repo"], now)
        except GraphQLError as exc:
            # Not recorded, so the next run tries this repo again.
            print(f"{entry['repo']}: failed ({exc})")
            continue
        record["bucket"] = entry.get("bucket")
        append_jsonl(results_path, record)
        measured += 1
        print(f"{entry['repo']}: {record['status']}")
    return measured


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m mergescout.measure", description="Phase 0 measurements.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sample", help="Pick about 300 repos across star ranges")
    api = sub.add_parser("api-cost", help="Measure API points per sampled repo (safe to re-run)")
    api.add_argument("--limit", type=int, default=None)
    sub.add_parser("count-repos", help="Count public repos by star range")
    rep = sub.add_parser("report", help="Print the budget report")
    rep.add_argument("--daily-points", type=int, default=120_000)
    args = parser.parse_args(argv)

    cfg = load_config()
    out = cfg.data_dir / "measure"
    out.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(days=30)).date()

    if args.cmd == "report":
        print(render_markdown(summarize(read_jsonl(out / "api_cost.jsonl"), daily_points=args.daily_points)))
        return 0

    gql = GitHubGraphQL(cfg.require_token())
    if args.cmd == "sample":
        sample = collect_sample(gql, build_sample_queries(recent))
        (out / "sample.json").write_bytes(orjson.dumps(sample, option=orjson.OPT_INDENT_2))
        print(f"Sampled {len(sample)} repos -> {out / 'sample.json'}")
    elif args.cmd == "api-cost":
        sample = orjson.loads((out / "sample.json").read_bytes())
        run_api_cost(gql, sample, out / "api_cost.jsonl", now, args.limit)
    elif args.cmd == "count-repos":
        counts = count_repos(gql, recent)
        counts["listing_requests"] = listing_requests(counts["rows"])
        (out / "count_repos.json").write_bytes(orjson.dumps(counts, option=orjson.OPT_INDENT_2))
        print(orjson.dumps(counts, option=orjson.OPT_INDENT_2).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
