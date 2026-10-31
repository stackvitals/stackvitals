"""One row per existing feature: what was measured, today's value with its n, how, and the phase that improves it.
Built from the measurement scripts' outputs in a local work folder; only aggregates are published.

    python bench/accuracy/features/scorecard.py --work bench/accuracy/.work

Writes bench/accuracy/features/scorecard.json.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def deps_row(work: Path) -> dict | None:
    m, o = _load(work / "deps" / "deps-map.json"), _load(work / "deps" / "deps-osv.json")
    if not m or not o:
        return None
    pk, op = m["packages"], o["packages"]
    n = len(pk)
    link = lambda v: sum(p.get("link") == v for p in pk.values())  # noqa: E731
    return {"feature": "Dependency evidence", "phase": "P16",
            "metric": "packages covered; source repo known (verified link); licence known; OSV checked",
            "value": f"{n:,} packages; repo {sum(bool(p.get('repo')) for p in pk.values()) / n:.1%} ({link('verified') / n:.0%} verified); "
                     f"licence {sum(bool(p.get('licenses')) for p in pk.values()) / n:.1%}; OSV {'complete' if o.get('complete') else 'partial'}, "
                     f"{sum(v['advisories'] > 0 for v in op.values())} with advisories, {sum(v['malware'] for v in op.values())} malware flags",
            "n": n, "how": f"the crawler's daily files built {m['built_at'][:10]}"}


def reports_row(work: Path) -> dict | None:
    r = _load(work / "features" / "reports-results.json")
    if not r:
        return None
    return {"feature": "Test reports in run artifacts", "phase": "P15",
            "metric": "sampled crawl repos keeping test reports StackVitals can read; files parsed",
            "value": f"{r['with_test_named_artifact']} of {r['repos']} keep report-named artifacts; {r['with_a_report_file']} of "
                     f"the {r['opened']} opened held report files ({', '.join(f'{k} {v}' for k, v in r['repos_by_format'].items())}); "
                     f"{r['files_parsed']} of {r['files']} files parsed. Two more repos ship JUnit inside coverage-named "
                     "artifacts, which are read too; most teams upload no test reports, so job-level history carries CI Health",
            "n": r["repos"], "how": "a seeded sample of crawl repos: artifact lists, the newest report-like artifact opened"}


def catalog_row(work: Path) -> dict | None:
    c = _load(work / "features" / "catalog-results.json")
    if not c:
        return None
    return {"feature": "Portal: catalog-info.yaml", "phase": "P17",
            "metric": "real files read with no problems; entities naming an owner",
            "value": f"{c['parsed_clean']} of {c['files']} clean ({c['clean_share']:.0%}); {c['entities_with_owner']} of "
                     f"{c['entities']} entities name an owner; every flagged file checked by hand had a real fault",
            "n": c["files"], "how": "GitHub code search for root catalog-info.yaml, parsed by Portal's parser"}


def api_row(work: Path) -> dict | None:
    rows = _load(work / "features" / "api-use-results.json")
    if not rows:
        return None
    per_run = [r["requests_per_run"] for r in rows if r.get("requests_per_run")]
    return {"feature": "API use per run", "phase": "P18",
            "metric": "GitHub requests per CI run read (the Action's steady cost)",
            "value": f"{min(per_run):.1f}-{max(per_run):.1f} per run on {len(rows)} repos; a busy repo's day "
                     f"({max(r['runs_read'] for r in rows)}+ runs) needs over {max(r['requests'] for r in rows)} requests cold",
            "n": sum(r["runs_read"] for r in rows), "how": "the CI reader's own request counter, cold read of one day"}


def branch_row(work: Path) -> dict | None:
    default, squash = _load(work / "features" / "sim-default" / "result.json"), _load(work / "features" / "sim-squash" / "result.json")
    if not default:
        return None
    last = default["checkpoints"][-1]
    text = (f"after {last['day']} days: history {last['git_mb']} MB, files {last['tree_mb']} MB without squash "
            f"({default['records_per_day']:,} records a day, {default['runs_per_day']} runs a day)")
    if squash:
        s = squash["checkpoints"][-1]
        text += f"; with squash every {squash['squash_every']} commits: history {s['git_mb']} MB"
    return {"feature": "Data branch size", "phase": "P18", "metric": "git history and files for a very busy repo",
            "value": text, "n": last["commits_made"], "how": "simulated: one real busy day replayed with the Action's write path"}


STATIC = [
    {"feature": "Deployment settings (auto against configured)", "phase": "P16",
     "metric": "repos whose deployment source is right with no setup", "value": "see the DORA card (30 of 35 held out; 53 of 60 with an earlier 25)", "n": 60,
     "how": "bench/accuracy/dora"},
    {"feature": "Regular responders", "phase": "P17", "metric": "project answers caught on held-out repos",
     "value": "see the community card", "n": None, "how": "bench/accuracy/community"},
    {"feature": "MCP answers for agents", "phase": "P15", "metric": "failures right and GitHub calls, with and without StackVitals",
     "value": "91 failures in 44 repos: Sonnet 88 with, 86 without (2.2 and 2.1 calls each); Haiku 43 of 48 with, 44 "
              "without (2.2 and 2.8 calls); no significant difference on single failures inside log retention",
     "n": 91, "how": "bench/accuracy/agents (results2.json)"},
    {"feature": "In-browser SQL (Explore)", "phase": "P18", "metric": "query time on a busy repo's summaries",
     "value": "measured 2026-10-21 on 20,648 pull requests (docs/scaling.md); re-check pending", "n": 20648,
     "how": "DuckDB-WASM in the browser"},
    {"feature": "Comment commands", "phase": "P18", "metric": "who may decide from a GitHub comment",
     "value": "repository permission checked on every command (tests); no live check with an outside account yet",
     "n": None, "how": "unit tests"},
    {"feature": "Chat alerts", "phase": "P16", "metric": "Slack, Discord and Teams payloads accepted",
     "value": "formats tested offline; live delivery not measured (needs a webhook)", "n": None, "how": "unit tests"},
    {"feature": "Test reports from other CI", "phase": "P15", "metric": "JUnit and CTRF uploads joining the history",
     "value": "GitLab CI read live (read-only): gitlab-org/cli, 78 pipelines in 7 days with 80 requests; uploads from "
              "other CI (JUnit, CTRF, Jest/Vitest, Go, TRX) tested offline; a live Jenkins or CircleCI upload needs an "
              "outside account and waits for launch", "n": 78, "how": "stackvitals ci gitlab; unit tests"},
    {"feature": "Test-level quarantine", "phase": "P14 M5", "metric": "failures let through that the change caused",
     "value": "not measurable on public data yet: 4 of 190 sampled repos keep readable test reports. It takes the job "
              "rule's 3-flake bar, whose held-out check found 13 of 81 known-flaky calls were the change's, so quarantine "
              "stays opt-in and the verdict check never passes on a known flake", "n": None,
     "how": "bench/accuracy/features/reports.py; flaky card held-out check"}]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--work", type=Path, required=True)
    args = ap.parse_args(argv)
    rows = [r for r in (deps_row(args.work), reports_row(args.work), catalog_row(args.work), api_row(args.work),
                        branch_row(args.work)) if r]
    out = {"rows": rows + STATIC}
    (HERE / "scorecard.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    for r in out["rows"]:
        print(f"{r['feature']}: {r['value']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
