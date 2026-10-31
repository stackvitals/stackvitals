"""`stackvitals ci validate FILE...`: whether a test report will be read the way you expect (Trunk's `validate`), before
it ever reaches CI: it is read as the Action reads it, then checked for what quietly breaks features (no tests, no file
names for owners and shards, no durations, timestamps from another day, counts that don't add up)."""
import argparse
import glob
import sys
from datetime import datetime, timedelta, timezone

from stackvitals.ci import testreports

ERROR, WARN = "error", "warning"


def _when(stamp: str | None) -> datetime | None:
    try:
        t = datetime.fromisoformat((stamp or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _junit_checks(data: bytes, now: datetime) -> list[tuple[str, str]]:
    from defusedxml import ElementTree
    out = []
    try:
        root = ElementTree.fromstring(data)
    except Exception:  # noqa: BLE001 - parse_report already said whether it reads
        return out
    cases = list(root.iter("testcase"))
    nameless = sum(1 for c in cases if not c.get("name"))
    if nameless:
        out.append((ERROR, f"{nameless} test case(s) have no name; they are all read as one test called '?'"))
    no_file = sum(1 for c in cases if not c.get("file") and not c.get("classname"))
    if cases and no_file:
        out.append((WARN, f"{no_file} of {len(cases)} test cases name neither a file nor a class: owners, shards and "
                          "test impact can't place them"))
    for suite in root.iter("testsuite"):
        stated, actual = suite.get("tests"), sum(1 for _ in suite.iter("testcase"))
        if stated and stated.isdigit() and int(stated) != actual and actual:
            out.append((WARN, f"suite {suite.get('name') or '?'} says tests=\"{stated}\" but lists {actual}"))
        t = _when(suite.get("timestamp"))
        if t and t < now - timedelta(days=7):
            out.append((WARN, f"suite {suite.get('name') or '?'} has a timestamp from {t.date()}: an old report left in the folder?"))
        elif t and t > now + timedelta(hours=1):
            out.append((WARN, f"suite {suite.get('name') or '?'} has a timestamp in the future ({t.isoformat()[:16]})"))
    return out


def check(name: str, data: bytes, now: datetime | None = None) -> dict:
    """{"file", "tests", "failed", "flaky", "problems": [(level, text)], "ok"}: ok unless an error was found."""
    now = now or datetime.now(timezone.utc)
    got = testreports.parse_report(name, data)
    if got is None:
        return {"file": name, "tests": 0, "problems": [(ERROR, "not a report StackVitals reads (JUnit XML, TRX, CTRF, "
                                                               "Jest or Vitest JSON, go test -json), or unsafe to read")], "ok": False}
    problems = []
    if not got["total"]:
        problems.append((ERROR, "no tests in it: the run that wrote it may have stopped before any test ran"))
    elif all(ms == 0 for _tid, ms in got.get("all") or []):
        problems.append((WARN, "every test took 0 seconds: durations are missing, so shards and slow tests can't use it"))
    if data.lstrip()[:1] == b"<":
        problems += _junit_checks(data, now)
    return {"file": name, "tests": got["total"], "failed": len(got["failed"]), "flaky": len(got["flaky"]),
            "problems": problems, "ok": not any(level == ERROR for level, _ in problems)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="stackvitals ci validate", description=__doc__.split("\n\n")[0])
    ap.add_argument("files", nargs="+", help="report files or globs (quote globs), like 'build/test-results/**/*.xml'")
    a = ap.parse_args(argv)
    paths = sorted({p for pat in a.files for p in (glob.glob(pat, recursive=True) or [pat])})
    bad = 0
    for path in paths:
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError as exc:
            print(f"{path}: can't read it ({exc.strerror})")
            bad += 1
            continue
        r = check(path, data)
        print(f"{path}: {r['tests']} tests" + (f", {r.get('failed', 0)} failed, {r.get('flaky', 0)} flaky" if r["tests"] else ""))
        for level, text in r["problems"]:
            print(f"  {level}: {text}")
        bad += not r["ok"]
    print(f"{len(paths) - bad} of {len(paths)} report(s) will be read as expected." if paths else "No files matched.")
    return 1 if bad or not paths else 0


if __name__ == "__main__":
    sys.exit(main())
