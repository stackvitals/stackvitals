"""How much of real repos' dependencies the every-lockfile check covers: lockfiles found by format, packages read,
packages with a known vulnerability, against the ~4,000 packages the crawl's evidence covered before.

    GH_TOKEN=... python bench/accuracy/deps/coverage.py run --scanner <osv-scanner binary> --per-language 10
    python bench/accuracy/deps/coverage.py score

Repos are drawn (seeded) from the MergeScout snapshot: 100+ stars, not archived, by language. Lockfiles are read from
raw.githubusercontent.com at the default branch (two API calls a repo). Results: coverage-results.json."""
import argparse
import json
import os
import random
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

import httpx
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from stackvitals.deps.vulns import MAX_FILES, findings, scannable  # noqa: E402

HERE = Path(__file__).resolve().parent
WORK = HERE.parent / ".work" / "deps-coverage"
# The scanner skips folders whose names start with a dot, so the lockfiles go to a plain temp folder.
FILES = Path(__import__("tempfile").gettempdir()) / "sv-deps-coverage"
LANGUAGES = ("Python", "TypeScript", "JavaScript", "Go", "Rust", "Java", "Kotlin", "C#", "PHP", "Ruby")
SEED = 20261023


def sample(per_language: int) -> list[str]:
    import sqlite3
    db = sqlite3.connect(Path.home() / ".mergescout" / "mergescout.sqlite")
    rng, out = random.Random(SEED), []
    for lang in LANGUAGES:
        names = [r[0] for r in db.execute("select name from repos where language = ? and stars >= 100 and not archived "
                                          "order by name", (lang,))]
        out += [(lang, n) for n in rng.sample(names, min(per_language, len(names)))]
    return out


def fetch(client: httpx.Client, repo: str, dest: Path) -> dict:
    meta = client.get(f"https://api.github.com/repos/{repo}").raise_for_status().json()
    ref = meta["default_branch"]
    tree = client.get(f"https://api.github.com/repos/{repo}/git/trees/{ref}", params={"recursive": "1"}).raise_for_status().json()
    paths = [t["path"] for t in tree.get("tree") or [] if t.get("type") == "blob" and scannable(t["path"])][:MAX_FILES]
    for p in paths:
        r = client.get(f"https://raw.githubusercontent.com/{repo}/{quote(ref, safe='')}/{quote(p)}")
        if r.status_code == 200:
            (dest / p).parent.mkdir(parents=True, exist_ok=True)
            (dest / p).write_bytes(r.content)
    return {"ref": ref, "sha": tree["sha"], "paths": paths, "truncated": bool(tree.get("truncated"))}


def run(scanner: Path, per_language: int) -> None:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    client = httpx.Client(timeout=60, follow_redirects=True, headers={"Authorization": f"Bearer {token}", "User-Agent": "stackvitals-bench"})
    WORK.mkdir(parents=True, exist_ok=True)
    for lang, repo in sample(per_language):
        out = WORK / (repo.replace("/", "__") + ".json")
        if out.exists():
            continue
        dest = FILES / repo.replace("/", "__")
        try:
            got = fetch(client, repo, dest)
        except httpx.HTTPError as exc:
            out.write_text(json.dumps({"repo": repo, "language": lang, "error": str(exc)[:200]}), encoding="utf-8")
            continue
        report = {"results": []}
        if got["paths"] and dest.exists():
            run_ = subprocess.run([str(scanner), "scan", "source", "-r", "--no-call-analysis=go", "--all-packages", "--format", "json", str(dest)],
                                  capture_output=True, timeout=900)
            if run_.returncode in (0, 1) and run_.stdout.strip():
                report = json.loads(run_.stdout.decode("utf-8"))
            else:
                got["scan_error"] = run_.stderr.decode("utf-8", "replace")[-300:]
        base = str(dest.resolve()).replace("\\", "/") + "/"
        files = defaultdict(lambda: {"packages": 0, "vulnerable": 0})
        for r in report.get("results") or []:
            src = str((r.get("source") or {}).get("path") or "").replace("\\", "/")
            f = files[src[len(base):] if src.startswith(base) else src]
            for p in r.get("packages") or []:
                f["packages"] += 1
                f["vulnerable"] += bool(p.get("groups"))
                f.setdefault("ecosystems", Counter())[(p.get("package") or {}).get("ecosystem")] += 1
        rows = findings(report, dest)
        packages = sorted({f"{(p.get('package') or {}).get('ecosystem')}:{(p.get('package') or {}).get('name')}"
                           for r in report.get("results") or [] for p in r.get("packages") or []})
        out.write_text(json.dumps({"repo": repo, "language": lang, **got, "files": files, "packages": packages,
                                   "findings": len(rows), "malware": sum(r["malware"] for r in rows),
                                   "severity": Counter(r["severity"] for r in rows)}, default=dict), encoding="utf-8")
    client.close()


def _format(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    return "requirements*.txt" if name.startswith("requirements") else name


def score() -> dict:
    repos = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(WORK.glob("*.json"))]
    ok = [r for r in repos if "error" not in r]
    try:
        old = json.loads((Path.home() / ".stackvitals" / "deps" / "deps-map.json").read_text(encoding="utf-8"))["packages"]
    except (OSError, ValueError, KeyError):
        old = {}
    eco_name = {"npm": "npm", "PyPI": "pypi"}
    by_format = defaultdict(lambda: {"files": 0, "read": 0, "packages": 0, "vulnerable": 0})
    for r in ok:
        seen = set(r["paths"])
        for path in seen:
            b = by_format[_format(path)]
            b["files"] += 1
            f = r["files"].get(path)
            if f:
                b["read"] += f["packages"] > 0
                b["packages"] += f["packages"]
                b["vulnerable"] += f["vulnerable"]
    packages = Counter()
    covered_before = 0
    for r in ok:
        for key in r["packages"]:
            eco, _, name = key.partition(":")
            packages[eco] += 1
            covered_before += f"{eco_name.get(eco, '?')}:{name.lower()}" in old or f"{eco_name.get(eco, '?')}:{name}" in old
    total = sum(packages.values())
    out = {"repos": len(repos), "read": len(ok), "with_lockfiles": sum(1 for r in ok if r["paths"]),
           "by_language": {lang: {"repos": sum(1 for r in ok if r["language"] == lang),
                                  "with_lockfiles": sum(1 for r in ok if r["language"] == lang and r["paths"]),
                                  "with_findings": sum(1 for r in ok if r["language"] == lang and r["findings"])}
                           for lang in LANGUAGES},
           "by_format": dict(sorted(by_format.items(), key=lambda kv: -kv[1]["files"])),
           "packages": {"total": total, "by_ecosystem": dict(packages.most_common()),
                        "deep_evidence_before": covered_before,
                        "share_with_deep_evidence_before": round(covered_before / total, 4) if total else None},
           "findings": sum(r["findings"] for r in ok), "malware": sum(r["malware"] for r in ok),
           "repos_with_critical_or_high": sum(1 for r in ok if (r.get("severity") or {}).get("critical") or (r.get("severity") or {}).get("high")),
           "scan_errors": [r["repo"] for r in ok if r.get("scan_error")]}
    (HERE / "coverage-results.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--scanner", type=Path, required=True)
    r.add_argument("--per-language", type=int, default=10)
    sub.add_parser("score")
    args = ap.parse_args(argv)
    if args.cmd == "run":
        run(args.scanner, args.per_language)
    else:
        print(json.dumps(score(), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
