"""`stackvitals ci retry`: re-run only the tests that failed, inside the same job (Datadog's auto test retries), and never
the ones the data branch calls broken: a test that fails every time is a real failure, and a retry would only hide it.

    stackvitals ci retry --reports 'out/*.xml' -- pytest --junitxml out/r.xml --then pytest --lf --junitxml out/r.xml

The first command runs the suite; when it fails, the reports name what failed. If any of those is known broken, the job
fails at once and says so; otherwise the retry command (your runner's own "only failures": pytest --lf, jest
--onlyFailures, rspec --only-failures) runs up to --times times, and the job passes when a retry does."""
import argparse
import json
import subprocess
import sys

from stackvitals.ci.burnin import _read


def broken_tests(ref: str = "origin/stackvitals-data", run=subprocess.run) -> set[str]:
    """Tests the data branch's published docs/data.json calls broken (failing every time on the default branch)."""
    out = run(["git", "show", f"{ref}:docs/data.json"], capture_output=True)
    if out.returncode != 0:
        return set()
    try:
        return {t["id"] for t in json.loads(out.stdout).get("tests") or [] if t.get("state") == "broken"}
    except ValueError:
        return set()


def retry(first: list[str], again: list[str], report_globs: list[str], times: int, broken: set[str],
          run=subprocess.run) -> tuple[int, dict]:
    """(exit code, what happened): 0 when the suite or a retry passed, the suite's code otherwise."""
    code = run(first).returncode
    if code == 0:
        return 0, {"retried": 0, "failed": []}
    report = _read(report_globs) or {"failed": []}
    failed = sorted({f[0] for f in report["failed"]})
    known = sorted(set(failed) & broken)
    if known or not failed:
        why = f"known broken, not retried: {', '.join(known[:5])}" if known else "no test report named a failed test"
        return code, {"retried": 0, "failed": failed, "why": why}
    for n in range(1, times + 1):
        if run(again).returncode == 0:
            return 0, {"retried": n, "failed": failed, "passed_on_retry": failed}
    return code, {"retried": times, "failed": failed, "why": "still failing after the retries"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="stackvitals ci retry", description=__doc__.split("\n\n")[0])
    ap.add_argument("--reports", action="append", default=[], required=True, help="glob of the report files the suite writes")
    ap.add_argument("--times", type=int, default=1, help="retries at most (default 1)")
    ap.add_argument("command", nargs=argparse.REMAINDER, help="-- the suite command --then the retry command")
    a = ap.parse_args(argv)
    cmd = a.command[1:] if a.command[:1] == ["--"] else a.command
    if "--then" not in cmd:
        print("Give the suite command, then --then and the retry command.", file=sys.stderr)
        return 2
    i = cmd.index("--then")
    code, out = retry(cmd[:i], cmd[i + 1:], a.reports, max(1, min(a.times, 5)), broken_tests())
    if out.get("passed_on_retry"):
        print(f"Passed on retry {out['retried']}: {', '.join(out['passed_on_retry'][:10])} failed, then passed (flaky).")
    elif out.get("why"):
        print(f"Not passed: {out['why']}.", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())

