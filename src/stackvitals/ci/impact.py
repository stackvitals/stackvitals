"""Test impact: which test files a change can affect, so the rest can be skipped (Datadog's Test Impact Analysis, without
a coverage agent). A test is picked when it changed, when its name matches a changed file (cart.py and test_cart.py),
or when it failed before on pull requests that changed the same folder; a change to build or settings files picks all.
The rule is replayed on the repo's own past pull requests first, so it is trusted only as far as it would have caught
their real failures.

    stackvitals ci impact --base origin/main --tests 'tests/**/*.py'    # the test files to run, or "all"
"""
import argparse
import glob
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import PurePosixPath

# A change to these can affect any test, so everything runs.
GLOBAL = re.compile(r"(^|/)(package(-lock)?\.json|pnpm-lock\.yaml|yarn\.lock|bun\.lockb?|pyproject\.toml|setup\.(py|cfg)|"
                    r"requirements[^/]*\.txt|uv\.lock|poetry\.lock|Pipfile(\.lock)?|conftest\.py|pytest\.ini|tox\.ini|"
                    r"go\.(mod|sum)|Cargo\.(toml|lock)|pom\.xml|build\.gradle(\.kts)?|settings\.gradle(\.kts)?|Gemfile(\.lock)?|"
                    r"tsconfig[^/]*\.json|(jest|vitest|babel|webpack|vite)\.config\.[cm]?[jt]s|Makefile|Dockerfile|\.github/)")
TEST = re.compile(r"(^|/)(test_[^/]*\.py|[^/]*_test\.(py|go)|[^/]*\.(test|spec)\.[cm]?[jt]sx?|[^/]*Tests?\.(java|kt|cs)|[^/]*_spec\.rb)$")
FOLDER_DEPTH = 2


def _stem(path: str) -> str:
    name = PurePosixPath(path).name
    name = re.sub(r"\.(test|spec)(?=\.)", "", name)
    name = re.sub(r"^test_|_test(?=\.)|_spec(?=\.)|Tests?(?=\.)", "", name)
    return name.rsplit(".", 1)[0].lower()


def _folder(path: str) -> str:
    return "/".join(path.split("/")[:FOLDER_DEPTH]) if "/" in path else ""


def test_file(test_id: str) -> str | None:
    """The file a test id names (pytest and Jest ids start with it), else None."""
    head = test_id.split("::", 1)[0]
    return head if "/" in head or "." in head and TEST.search(head) else None


def learn(history: list[tuple[list[str], list[str]]]) -> dict[str, dict[str, int]]:
    """{changed folder: {test file: times it failed}} from (changed paths, failed test files) of past pull requests."""
    out = defaultdict(Counter)
    for changed, failed in history:
        for folder in {_folder(p) for p in changed if not TEST.search(p)}:
            for f in set(failed):
                out[folder][f] += 1
    return {k: dict(v) for k, v in out.items()}


def select(changed: list[str], tests: list[str], learned: dict | None = None) -> list[str] | None:
    """The test files to run for these changed paths, or None for all of them."""
    if not changed or any(GLOBAL.search(p) for p in changed):
        return None
    picked = {p for p in changed if TEST.search(p) and p in tests}
    stems = {_stem(p) for p in changed if not TEST.search(p)}
    picked |= {t for t in tests if _stem(t) in stems}
    for folder in {_folder(p) for p in changed if not TEST.search(p)}:
        picked |= {t for t in (learned or {}).get(folder, {}) if t in tests}
    return sorted(picked)


def backtest(history: list[tuple[list[str], list[str]]], tests: list[str]) -> dict:
    """Replays the rule on past pull requests, each judged with what was learned before it: how many of their real
    failures it would have run, and the share of test files it would have skipped."""
    caught = missed = 0
    saved = []
    for i, (changed, failed) in enumerate(history):
        picked = select(changed, tests, learn(history[:i]))
        run = set(tests) if picked is None else set(picked)
        for f in set(failed):
            if f in run:
                caught += 1
            else:
                missed += 1
        if tests:
            saved.append(1 - len(run) / len(tests))
    total = caught + missed
    return {"prs": len(history), "failures": total, "caught": caught, "recall": round(caught / total, 4) if total else None,
            "skipped_share": round(sum(saved) / len(saved), 4) if saved else None}


def history_from(data: dict, prs: dict[int, list[str]], flaky: set[str]) -> list[tuple[list[str], list[str]]]:
    """(changed paths, failed test files) per pull request, oldest first, from CI's test reports and Team Flow's PR
    files; flaky tests are left out, since a skipped flake is no miss."""
    runs = {r["id"]: r for r in data.get("runs") or []}
    by_pr = defaultdict(set)
    first = {}
    for rec in data.get("tests") or []:
        run = runs.get(rec.get("run")) or {}
        for n in run.get("pr") or []:
            if n in prs:
                for f in rec.get("failed") or []:
                    if f and f[0] not in flaky and (path := test_file(f[0])):
                        by_pr[n].add(path)
                first.setdefault(n, run.get("cr") or "")
    return [(prs[n], sorted(by_pr[n])) for n in sorted(by_pr, key=lambda n: first[n])]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="stackvitals ci impact", description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", default="origin/main", help="what the change is compared with (git diff BASE...HEAD)")
    ap.add_argument("--tests", action="append", default=[], required=True, help="glob of the repo's test files")
    ap.add_argument("--learned", default="origin/stackvitals-data:ci/impact.json", help="the data branch's learned map")
    a = ap.parse_args(argv)
    diff = subprocess.run(["git", "diff", "--name-only", f"{a.base}...HEAD"], capture_output=True, text=True)
    if diff.returncode != 0:
        print("all")
        return 0
    tests = sorted({p.replace("\\", "/") for g in a.tests for p in glob.glob(g, recursive=True)})
    got = subprocess.run(["git", "show", a.learned], capture_output=True)
    try:
        learned = json.loads(got.stdout).get("learned") if got.returncode == 0 else None
    except ValueError:
        learned = None
    picked = select([p for p in diff.stdout.splitlines() if p.strip()], tests, learned)
    print("all" if picked is None else " ".join(picked))
    return 0


if __name__ == "__main__":
    sys.exit(main())
