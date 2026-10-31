"""`stackvitals ci burn-in`: run the tests a pull request adds or changes several times before it merges, and fail when
one of them both passed and failed (early flake detection, as Datadog does it, from your own CI with no service).

    stackvitals ci burn-in --base origin/main --times 5 --reports 'out/*.xml' -- pytest {files}

`{files}` becomes the added or changed test files; with none, nothing runs. A test failing every time is listed, but the
normal CI run is the one that fails for it."""
import glob
import os
import re
import subprocess

from stackvitals.ci.testreports import merge, parse_report

# Test files by the usual names: pytest, Go, Jest/Vitest/Mocha, JUnit-style Java, Kotlin and C#.
TEST_FILE = re.compile(r"(^|/)(test_[^/]*\.py|[^/]*_test\.(py|go)|[^/]*\.(test|spec)\.[cm]?[jt]sx?|[^/]*Tests?\.(java|kt|cs)"
                       r"|__tests__/(.*/)?[^/]+\.[cm]?[jt]sx?|[^/]*_spec\.rb)$")


def changed_tests(base: str, run=subprocess.run) -> list[str]:
    """Test files added or changed since `base` (git diff BASE...HEAD)."""
    out = run(["git", "diff", "--name-only", "--diff-filter=AM", f"{base}...HEAD"], capture_output=True, text=True)
    return [f for f in (out.stdout or "").splitlines() if TEST_FILE.search(f.strip())] if out.returncode == 0 else []


def _read(report_globs: list[str], keep: bool = False) -> dict | None:
    parts = []
    for pattern in report_globs:
        for path in glob.glob(pattern, recursive=True):
            with open(path, "rb") as f:
                parsed = parse_report(path, f.read())
            if parsed:
                parts.append(parsed)
            if not keep:
                os.remove(path)  # each repeat must write its own report, never be read twice
    return merge(parts) if parts else None


def known_tests(ref: str = "origin/stackvitals-data", run=subprocess.run) -> set | None:
    """Every test id the default branch's runs have reported, from the data branch (git fetch origin stackvitals-data
    first); None when it can't be read."""
    import gzip
    import json

    from stackvitals.ci.store import KNOWN
    out = run(["git", "show", f"{ref}:ci/{KNOWN}"], capture_output=True)
    if out.returncode != 0:
        return None
    try:
        return set(json.loads(gzip.decompress(out.stdout)))
    except (OSError, ValueError, EOFError):
        return None


def flaky_rates(ref: str = "origin/stackvitals-data", run=subprocess.run) -> dict[str, float]:
    """{test id: failure rate} of the tests the data branch calls flaky, from its published docs/data.json."""
    import json
    out = run(["git", "show", f"{ref}:docs/data.json"], capture_output=True)
    if out.returncode != 0:
        return {}
    try:
        tests = json.loads(out.stdout).get("tests") or []
    except ValueError:
        return {}
    return {t["id"]: float(t.get("failure_rate") or 0) for t in tests if t.get("state") == "flaky" and t.get("failure_rate")}


def proofs(passed: set, failed: set, times: int, rates: dict[str, float]) -> list[dict]:
    """Known flaky tests that passed every repeat, with the chance they would have anyway at their old failure rate;
    a fix counts as shown when that chance is under 5%."""
    out = []
    for tid in sorted((passed - failed) & rates.keys()):
        chance = (1 - rates[tid]) ** times
        out.append({"id": tid, "passes": times, "rate": rates[tid], "chance": round(chance, 4), "shown": chance < 0.05})
    return out


def burn_in(command: list[str], report_globs: list[str], times: int, files: list[str], run=subprocess.run,
            known: set | None = None, only_new: bool = False, rates: dict | None = None) -> tuple[int, dict]:
    """(exit code, summary): 1 when a test both passed and failed over the repeats (with only_new, a test the default
    branch never reported), 2 when a repeat wrote no report. With the known tests, the new ones are named."""
    if not files:
        return 0, {"runs": 0, "tests": 0, "flaky": [], "always_failed": [], "files": []}
    cmd = [part for c in command for part in (files if c == "{files}" else [c])]
    passed, failed = set(), set()
    for n in range(times):
        run(cmd)
        # The last repeat's reports stay, for an upload step after this one.
        report = _read(report_globs, keep=n == times - 1)
        if report is None:
            return 2, {"runs": n + 1, "problem": f"repeat {n + 1} wrote no test report matching {', '.join(report_globs)}"}
        bad = {f[0] for f in report["failed"]}
        failed |= bad | set(report["flaky"])
        passed |= {tid for tid, _ms in report["all"]} - bad
    flaky = sorted(passed & failed)
    new = sorted(t for t in passed | failed if known is not None and t not in known)
    new_flaky = [t for t in flaky if t in new]
    code = 1 if (new_flaky if only_new and known is not None else flaky) else 0
    return code, {"runs": times, "tests": len(passed | failed), "flaky": flaky, "always_failed": sorted(failed - passed),
                  "files": files, "new": new if known is not None else None, "new_flaky": new_flaky,
                  # A known flaky test that passed every repeat: its fix, shown on the PR itself.
                  "fix_proofs": proofs(passed, failed, times, rates or {})}
