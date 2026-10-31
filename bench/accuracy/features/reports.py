"""How many public repos keep test reports StackVitals can read: a seeded sample of crawl repos, their artifact lists, and
the newest report-like artifact of each repo opened and parsed.

    GH_TOKEN=... python bench/accuracy/features/reports.py --records <ci records> --work <work folder> [--repos 200]

One request per repo for its artifact list and one per downloaded artifact (at most 20 MB); progress is kept in the
work folder, so it resumes. Writes reports-results.json in the work folder (counts only; the scorecard reads it).
"""
import argparse
import gzip
import io
import json
import os
import random
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path

import httpx

from stackvitals.ci.collect import TEST_REPORTS
from stackvitals.ci.testreports import REPORT_FILES, parse_report

API = "https://api.github.com"
MAX_BYTES = 20_000_000
COVERAGE = re.compile(r"lcov|jacoco|cobertura|coverage(?![-_ ]?html)", re.I)
# Names a report artifact may carry that the default pattern misses, to see what it costs.
LOOSE = re.compile(r"test|junit|report|result|spec", re.I)


def kind(name: str, data: bytes) -> str | None:
    """Which report format a file is: junit, trx, ctrf, jest, go, or None."""
    head = data.lstrip()[:200]
    if name.lower().endswith((".xml", ".trx")) or head[:1] == b"<":
        return "trx" if b"TestRun" in head and b"TeamTest" in data[:2000] else "junit"
    try:
        doc = json.loads(data)
    except ValueError:
        return "go" if b'"Action"' in head else None
    if not isinstance(doc, dict):
        return None
    return "ctrf" if "results" in doc else "jest" if "testResults" in doc else "go" if "Action" in doc else None


def frame(records: Path, n: int, seed: int) -> list[str]:
    latest = {}
    for path in sorted(records.glob("ci-*.ndjson.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    latest[r["repo"].lower()] = r
    pool = sorted(r["repo"] for r in latest.values() if r["pushes"] >= 10)
    return random.Random(seed).sample(pool, min(n, len(pool)))


def look(client: httpx.Client, repo: str) -> dict:
    resp = client.get(f"{API}/repos/{repo}/actions/artifacts", params={"per_page": 100})
    if resp.status_code != 200:
        return {"repo": repo, "error": resp.status_code}
    arts = [a for a in resp.json().get("artifacts") or [] if not a.get("expired")]
    names = [a.get("name") or "" for a in arts]
    tests = [a for a in arts if re.search(TEST_REPORTS, a.get("name") or "", re.I)]
    out = {"repo": repo, "artifacts": len(arts), "test_named": len(tests),
           "coverage_named": sum(bool(COVERAGE.search(x)) for x in names),
           "loose_named": sum(bool(LOOSE.search(x)) and not re.search(TEST_REPORTS, x, re.I) for x in names)}
    small = [a for a in tests if (a.get("size_in_bytes") or 0) <= MAX_BYTES]
    if not small:
        return out
    newest = max(small, key=lambda a: a.get("created_at") or "")
    got = client.get(f"{API}/repos/{repo}/actions/artifacts/{newest['id']}/zip")
    if got.status_code != 200:
        return {**out, "download": got.status_code}
    kinds, parsed, files = Counter(), 0, 0
    try:
        with zipfile.ZipFile(io.BytesIO(got.content)) as z:
            for info in z.infolist()[:200]:
                if info.is_dir() or not info.filename.lower().endswith(REPORT_FILES) or info.file_size > MAX_BYTES:
                    continue
                body = z.read(info)
                files += 1
                k = kind(info.filename, body)
                kinds[k or "other"] += 1
                parsed += k is not None and parse_report(info.filename, body) is not None
    except zipfile.BadZipFile:
        return {**out, "download": "bad zip"}
    return {**out, "files": files, "kinds": dict(kinds), "parsed": parsed}


def summarise(rows: list[dict]) -> dict:
    ok = [r for r in rows if "error" not in r]
    opened = [r for r in ok if "files" in r]
    kinds = Counter()
    for r in opened:
        kinds.update({k: 1 for k in r["kinds"]})
    return {"repos": len(ok), "with_any_artifact": sum(r["artifacts"] > 0 for r in ok),
            "with_test_named_artifact": sum(r["test_named"] > 0 for r in ok),
            "with_only_loosely_named": sum(r["test_named"] == 0 and r["loose_named"] > 0 for r in ok),
            "opened": len(opened), "with_a_report_file": sum(r["files"] > 0 for r in opened),
            "repos_by_format": dict(kinds.most_common()),
            "files": sum(r["files"] for r in opened), "files_parsed": sum(r["parsed"] for r in opened),
            "files_of_a_known_format": sum(r["files"] - r["kinds"].get("other", 0) for r in opened)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--records", type=Path, required=True)
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--repos", type=int, default=200)
    ap.add_argument("--seed", type=int, default=17)
    args = ap.parse_args(argv)
    args.work.mkdir(parents=True, exist_ok=True)
    cache = args.work / "reports-cache.jsonl"
    done = {json.loads(x)["repo"]: json.loads(x) for x in cache.read_text(encoding="utf-8").splitlines() if x.strip()} \
        if cache.exists() else {}
    client = httpx.Client(timeout=120, follow_redirects=True, headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}",
                                                                       "Accept": "application/vnd.github+json"})
    with cache.open("a", encoding="utf-8") as f:
        for repo in frame(args.records, args.repos, args.seed):
            if repo in done:
                continue
            try:
                row = look(client, repo)
            except httpx.HTTPError as exc:
                row = {"repo": repo, "error": type(exc).__name__}
            done[repo] = row
            f.write(json.dumps(row) + "\n")
            f.flush()
    out = summarise(list(done.values()))
    (args.work / "reports-results.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
