import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from mergescout.config import load_config


def write_extras(con, out: Path, now: datetime, log=lambda msg: print(msg, flush=True)) -> None:
    """Review-flow and community benchmarks, the triage model and the dependency evidence for the suite; a failure here
    never stops the snapshot."""
    import mergescout.signals.bump_ledger as bump_ledger
    import mergescout.signals.flow_bench as flow_bench
    import mergescout.signals.triage as triage
    try:
        bench = flow_bench.flow_benchmarks(con, now)
        # Outside merge odds checked against what happened next, and coding-agent PRs per group, in the same file;
        # their failure never costs the peer comparisons.
        try:
            bench["odds_backtest"] = flow_bench.odds_backtest(con, now)
            bench["agent_prs"] = flow_bench.agent_prs(con, now)
        except Exception as exc:  # noqa: BLE001
            log(f"odds backtest skipped: {exc}")
        # Agents' PRs against people's of the same repo, month and size; older crawls without branch names skip it.
        try:
            bench["agent_matched"] = flow_bench.agent_matched(con, now)
        except Exception as exc:  # noqa: BLE001
            log(f"matched agent gaps skipped: {exc}")
        # Each coding agent on its own across the crawl: the public leaderboard repos compare their own agents with.
        try:
            bench["agent_leaderboard"] = flow_bench.agent_leaderboard(con, now)
        except Exception as exc:  # noqa: BLE001
            log(f"agent leaderboard skipped: {exc}")
        (out / "flow-benchmarks.json").write_text(json.dumps(bench, indent=1, sort_keys=True), encoding="utf-8")
        log(f"flow benchmarks: {bench['repos']} repos, {len(bench['groups'])} groups")
        bt = bench.get("odds_backtest") or {}
        if bt.get("mae"):
            log(f"outside merge odds backtest: {bt['repos']} repos, {bt['prs']} PRs; mean error raw {bt['mae']['raw']:.1%}, "
                f"shrunk {bt['mae']['shrunk']:.1%}, typical only {bt['mae']['typical_only']:.1%}")
    except Exception as exc:  # noqa: BLE001
        log(f"flow benchmarks skipped: {exc}")
    try:
        import mergescout.signals.delivery_bench as delivery_bench
        bench = delivery_bench.delivery_benchmarks(con, now)
        (out / "delivery-benchmarks.json").write_text(json.dumps(bench, indent=1, sort_keys=True), encoding="utf-8")
        mid = (bench["groups"].get("all|all") or {}).get("pickup_p75_hours") or {}
        log(f"delivery benchmarks: {bench['repos']} repos, {len(bench['groups'])} groups; pickup P75 median of all repos "
            f"{mid.get('p50')} h ({mid.get('p50_low')}-{mid.get('p50_high')}), inside LinearB's good band "
            f"{(mid.get('linearb') or {}).get('good')}")
    except Exception as exc:  # noqa: BLE001
        log(f"delivery benchmarks skipped: {exc}")
    try:
        import mergescout.signals.community_bench as community_bench
        bench = community_bench.community_benchmarks(con, now)
        (out / "community-benchmarks.json").write_text(json.dumps(bench, indent=1, sort_keys=True), encoding="utf-8")
        log(f"community benchmarks: {bench['repos']} repos, {len(bench['groups'])} groups")
        # Logged daily so the newcomer lever is checked on the whole crawl, like the upgrade backtest.
        log("newcomers returning by first answer: " + "; ".join(
            f"{b['bucket']} {b['returned']:.1%} (n {b['newcomers']})" for b in bench["newcomers"]["by_answer"]))
    except Exception as exc:  # noqa: BLE001
        log(f"community benchmarks skipped: {exc}")
    try:
        model = triage.build_triage_model(con, now)
        (out / "triage-model.json").write_text(json.dumps(model, indent=1, sort_keys=True), encoding="utf-8")
        log(f"triage model: {model['prs']} PRs, checked on {model['evaluation'].get('test_prs')}")
    except Exception as exc:  # noqa: BLE001
        log(f"triage model skipped: {exc}")
    try:
        prs = bump_ledger.build_bump_prs(con)
        cells = bump_ledger.build_bump_ledger(con, now)
        (out / "deps-ledger.json").write_text(json.dumps(bump_ledger.ledger_json(con, now), sort_keys=True), encoding="utf-8")
        log(f"upgrade ledger: {prs} bot PRs, {cells} cells")
    except Exception as exc:  # noqa: BLE001
        log(f"upgrade ledger skipped: {exc}")
    try:
        # Whether flags on older upgrades predicted later trouble, re-checked daily as titles and CI results accumulate.
        log(f"upgrade backtest: {bump_ledger.bump_backtest(con, now)}")
    except Exception as exc:  # noqa: BLE001
        log(f"upgrade backtest skipped: {exc}")
    try:
        write_package_map(con, out, now, log)
    except Exception as exc:  # noqa: BLE001
        log(f"package map skipped: {exc}")
    try:
        write_trends(con, out, now, log)
    except Exception as exc:  # noqa: BLE001
        log(f"trend lines skipped: {exc}")
    try:
        write_vulns(out, now, log)
    except Exception as exc:  # noqa: BLE001
        log(f"vulnerability history skipped: {exc}")
    try:
        write_owners(out, now, log)
    except Exception as exc:  # noqa: BLE001
        log(f"ownership watch skipped: {exc}")


def write_owners(out: Path, now: datetime, log) -> None:
    """Today's publishers and owners of the mapped packages, with the changes since yesterday's file (fetched by the workflow)."""
    import mergescout.signals.owners_watch as ow
    mapped = json.loads((out / "deps-map.json").read_text(encoding="utf-8")).get("packages", {})
    packages = sorted((*key.split(":", 1), info.get("version")) for key, info in mapped.items())
    path = out / "deps-owners.json"
    previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    state = ow.refresh_owners(packages, previous, now)
    path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    changed = sum(1 for p in state["packages"].values() if p.get("events"))
    log(f"ownership watch: {len(state['packages'])} packages, {changed} with changes since watching began")


def write_vulns(out: Path, now: datetime, log) -> None:
    """OSV history of the mapped packages; yesterday's file (fetched by the workflow) caches unchanged advisories."""
    import mergescout.signals.osv as osv
    from mergescout.signals.exploits import lookup
    mapped = json.loads((out / "deps-map.json").read_text(encoding="utf-8")).get("packages", {})
    packages = sorted(tuple(key.split(":", 1)) for key in mapped)
    path = out / "deps-osv.json"
    previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    # CISA KEV and FIRST's EPSS for the advisories' CVEs: one feed and about 80 requests a day, both free.
    state = osv.refresh_vulns(packages, previous, now, exploits=lookup)
    path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    hit = sum(1 for p in state["packages"].values() if p.get("advisories"))
    ex = state.get("exploits") or {}
    log(f"vulnerability history: {len(state['packages'])} packages, {hit} with advisories, {len(state['records'])} advisories cached; "
        f"{ex.get('scored', 0)} CVEs scored by EPSS, {ex.get('kev', 0)} in CISA KEV")


def write_trends(con, out: Path, now: datetime, log) -> None:
    """Quarterly lines for the watched source repos that the crawl already covers (the rest arrive as it crawls them)."""
    from mergescout.signals.deps_trends import repo_trends
    watch_file = out / "watch-repos.txt"
    watch = watch_file.read_text(encoding="utf-8").split() if watch_file.exists() else []
    trends = repo_trends(con, watch, now)
    (out / "deps-trends.json").write_text(json.dumps({"built_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "repos": trends},
                                                     sort_keys=True), encoding="utf-8")
    log(f"trend lines: {len(trends)} of {len(watch)} watched repos are crawled")


def write_package_map(con, out: Path, now: datetime, log) -> None:
    """Source repos of the ledger's npm and PyPI packages and of the most-used ones; yesterday's file (fetched by the
    workflow) is reused per package."""
    import mergescout.signals.bump_ledger as bump_ledger
    import mergescout.signals.deps_map as deps_map
    import mergescout.signals.top_packages as top_packages
    from mergescout.github.graphql import GitHubGraphQL
    packages = con.execute("SELECT DISTINCT ecosystem, package FROM bump_ledger WHERE ecosystem IN ('npm', 'pypi') "
                           "AND prs >= $min", {"min": bump_ledger.MIN_PUBLISH}).fetchall()
    path = out / "deps-map.json"
    previous = json.loads(path.read_text(encoding="utf-8")).get("packages", {}) if path.exists() else {}
    # A failed download keeps yesterday's top list; the ledger's packages come first within the lookup time budget.
    top = top_packages.fetch_top() or [tuple(k.split(":", 1)) for k, v in previous.items() if v.get("top")]
    # Claimed links are checked against manifests with the workflow's own token (about 1 point per 20 repos).
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("MS_RELEASE_TOKEN")
    gql = GitHubGraphQL(token, max_wait=0, reserve=50) if token else None
    mapped = deps_map.refresh_map(list(dict.fromkeys([tuple(p) for p in packages] + top)), previous, now, gql=gql)
    tops = set(top)
    for key, info in mapped.items():
        info["top"] = tuple(key.split(":", 1)) in tops
    path.write_text(json.dumps({"built_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "packages": mapped}, sort_keys=True),
                    encoding="utf-8")
    links = {}
    for info in mapped.values():
        links[info.get("link")] = links.get(info.get("link"), 0) + 1
    # Source repos the crawler should keep current (seed --watch); only links we can stand behind.
    watch = sorted({i["repo"].lower() for i in mapped.values() if i.get("repo") and i.get("link") in ("verified", "claimed_checked")})
    (out / "watch-repos.txt").write_text("".join(f"{r}\n" for r in watch), encoding="utf-8")
    log(f"package map: {len(mapped)} packages ({len(tops)} most-used), links {links}, {len(watch)} repos to watch")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m mergescout.snapshot", description="Build and publish the snapshot.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="Build signals and mergescout.sqlite from all crawl data")
    b.add_argument("--from-releases", action="store_true")
    b.add_argument("--out", default=None)
    p = sub.add_parser("publish", help="Compress the snapshot and publish it as today's data release")
    p.add_argument("dir")
    p.add_argument("--keep", type=int, default=7)
    p.add_argument("--force", action="store_true", help="Publish even if the snapshot shrank by more than half")
    p.add_argument("--repo", default=os.environ.get("MS_STORE_REPO") or os.environ.get("GITHUB_REPOSITORY"))
    args = parser.parse_args(argv)
    cfg = load_config()
    now = datetime.now(timezone.utc)
    if args.cmd == "build":
        from mergescout.signals.__main__ import prepare, write_bundle
        from mergescout.snapshot.build import build_snapshot
        out = Path(args.out) if args.out else cfg.data_dir / "snapshot"
        con = prepare(cfg, out, args.from_releases, now)
        if con is None:
            return 1
        write_bundle(con, out)
        print(f"snapshot: {build_snapshot(con, out / 'mergescout.sqlite', now)}", flush=True)
        write_extras(con, out, now)
        con.close()
        return 0
    if args.cmd == "publish":
        from mergescout.github.releases import Releases
        from mergescout.snapshot.publish import publish
        token = os.environ.get("MS_RELEASE_TOKEN")
        if not token or not args.repo:
            print("Set MS_RELEASE_TOKEN and MS_STORE_REPO (or GITHUB_REPOSITORY).", file=sys.stderr)
            return 1
        try:
            publish(Releases(token, args.repo), Path(args.dir), now, keep=args.keep, force=args.force)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 1
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
