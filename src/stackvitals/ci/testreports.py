import hashlib
import io
import json
import math
import re
import zipfile

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import ParseError, fromstring

from stackvitals.ci import coverage
from stackvitals.ci.fingerprint import analyse

SLOW_KEEP = 200
SKIP_KEEP = 200
# Caps per report: a hostile or giant report can't bloat the data branch (ids longer than this are cut).
MAX_ID, MAX_ROWS, MAX_ALL = 300, 500, 50_000
FAIL_TAGS = {"failure", "error"}
FLAKY_TAGS = {"flakyFailure", "flakyError"}
REPORT_FILES = (".xml", ".trx", ".json", ".jsonl", ".ndjson")
# A random test order's seed, so a flaky failure can be replayed: Surefire's runOrder seed, `go test -shuffle`.
SEED_PROPERTY = re.compile(r"seed|randomly", re.I)
GO_SEED = re.compile(r"-test\.shuffle (\d+)")
GO_LINE = re.compile(r"^\s*([\w.\-]+\.go:\d+: .*)$")
# Hosted runners' checkout folders (Linux and macOS, Windows, containers), so a test file reads as a repo path.
RUNNER_ROOT = re.compile(r"^(?:.*?[\\/]runner[\\/]work[\\/][^\\/]+[\\/][^\\/]+|[A-Za-z]:[\\/]a[\\/][^\\/]+[\\/][^\\/]+"
                         r"|/github/workspace)[\\/]")
TRX_FAILED = {"failed", "error", "timeout", "aborted"}
TRX_SKIPPED = {"notexecuted", "inconclusive", "pending", "notrunnable", "disconnected"}
JEST_SKIPPED = {"pending", "skipped", "todo", "disabled"}


def _failure(tid: str, type_attr: str | None, message: str | None, text: str | None, ms: int | None) -> list:
    """[test id, per-test key, short message, cause, where, type, ms]: older records hold only the first three."""
    f = analyse(type_attr, message, text)
    shown = message or (f"{f.type}: {f.message}" if f.type else f.message) or text
    return [tid, f.key(tid), _short(shown), f.cause, f.where, f.type, ms]


def _short(message: str | None) -> str:
    text = (message or "").strip()
    return text.splitlines()[0][:200] if text else ""


def _cap_id(tid: str) -> str:
    # A long id is cut, with a short hash of the whole so two long ids never become one test.
    return tid if len(tid) <= MAX_ID else f"{tid[:MAX_ID - 9]}~{hashlib.sha1(tid.encode()).hexdigest()[:8]}"


def _millis(value, scale: float = 1) -> int:
    # Report numbers are untrusted: anything not finite or beyond a few months of run time counts as 0.
    try:
        ms = float(value) * scale
    except (TypeError, ValueError, OverflowError):
        return 0
    return round(ms) if math.isfinite(ms) and 0 <= ms < 1e10 else 0


def _text(value) -> str | None:
    return value if isinstance(value, str) else None


def _repo_path(path) -> str | None:
    return RUNNER_ROOT.sub("", path).replace("\\", "/") if isinstance(path, str) and path else None


def _empty() -> dict:
    # "all" (every test and its time) is read for new-test detection and shards, and never stored per report.
    return {"total": 0, "skipped": 0, "failed": [], "flaky": [], "slow": [], "sk": [], "all": []}


def _case() -> dict:
    return {"fail": None, "passed": False, "flaky": False, "skipped": False, "ms": 0, "detail": None}


def _outcomes(seen: dict[str, dict]) -> dict:
    """Each test's outcomes, gathered over every time the report lists it, as one report: a failure that also passed
    (a retry inside the same job) is a flake."""
    out = _empty()
    for tid, info in seen.items():
        out["total"] += 1
        if info["fail"] is not None and info["passed"] or info["flaky"]:
            # Failed, then passed on a retry inside the same job (Gradle test-retry, pytest-rerunfailures, Surefire).
            out["flaky"].append(tid)
        elif info["fail"] is not None:
            out["failed"].append(_failure(tid, *info["detail"], info["ms"]))
        elif info["skipped"] and not info["passed"]:
            out["skipped"] += 1
    out["slow"] = sorted(([tid, i["ms"]] for tid, i in seen.items()), key=lambda x: -x[1])[:SLOW_KEEP]
    out["sk"] = [tid for tid, i in seen.items() if i["skipped"] and not i["passed"] and i["fail"] is None and not i["flaky"]][:SKIP_KEEP]
    out["all"] = [[tid, i["ms"]] for tid, i in seen.items()]
    return out


def _junit(root) -> dict:
    # A test can appear several times when a retry plugin re-ran it, so outcomes are gathered per test first.
    seen: dict[str, dict] = {}
    for case in root.iter("testcase"):
        name, cls, file = case.get("name") or "?", case.get("classname"), case.get("file")
        info = seen.setdefault(_cap_id("::".join(p for p in (file, cls, name) if p)), _case())
        tags = {child.tag: child for child in case}
        failure = next((tags[t] for t in FAIL_TAGS if t in tags), None)
        if failure is not None:
            info["fail"] = info["fail"] or (failure.get("message") or failure.text or "")
            # The body holds the stack the fingerprint needs; only its result is kept.
            info["detail"] = info["detail"] or (failure.get("type"), failure.get("message"), failure.text)
        elif FLAKY_TAGS & tags.keys():
            info["flaky"] = True
        elif "skipped" in tags:
            info["skipped"] = True
        else:
            info["passed"] = True
        info["ms"] = max(info["ms"], _millis(case.get("time") or 0, 1000))
    out = _outcomes(seen)
    seed = next((p.get("value") for p in root.iter("property") if SEED_PROPERTY.search(p.get("name") or "") and p.get("value")), None)
    return {**out, "seed": seed[:40]} if seed else out


def _span(value) -> int:
    # TRX durations read "00:00:01.5000000".
    m = re.match(r"^(\d+):(\d+):(\d+(?:\.\d+)?)$", value or "")
    return _millis(int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]), 1000) if m else 0


def _trx(root) -> dict:
    """A .NET TRX file (dotnet test --logger trx): each result named by its class and test name, parameters included."""
    ns = root.tag[:root.tag.index("}") + 1] if root.tag.startswith("{") else ""
    classes = {}
    for unit in root.iter(f"{ns}UnitTest"):
        method = unit.find(f"{ns}TestMethod")
        if method is not None:
            classes[unit.get("id")] = method.get("className")
    seen: dict[str, dict] = {}
    for result in root.iter(f"{ns}UnitTestResult"):
        name = result.get("testName") or "?"
        info = seen.setdefault(_cap_id("::".join(p for p in (classes.get(result.get("testId")), name) if p)), _case())
        outcome = (result.get("outcome") or "").lower()
        if outcome in TRX_FAILED:
            error = result.find(f"{ns}Output/{ns}ErrorInfo")
            message = (error.findtext(f"{ns}Message") or "").strip() if error is not None else ""
            trace = error.findtext(f"{ns}StackTrace") if error is not None else None
            info["fail"] = info["fail"] or message
            info["detail"] = info["detail"] or (None, message or None, trace or message)
        elif outcome == "passed":
            info["passed"] = True
        elif outcome in TRX_SKIPPED:
            info["skipped"] = True
        info["ms"] = max(info["ms"], _span(result.get("duration")))
    return _outcomes(seen)


def _xml(data: bytes) -> dict | None:
    try:
        root = fromstring(data, forbid_dtd=True)
    except (DefusedXmlException, ParseError, ValueError):
        return None
    return _trx(root) if root.tag.rsplit("}", 1)[-1] == "TestRun" else _junit(root)


def _ctrf(doc: dict) -> dict | None:
    try:
        tests = doc["results"]["tests"]
    except (KeyError, TypeError):
        return None
    out, slow = _empty(), []
    for t in tests if isinstance(tests, list) else []:
        if not isinstance(t, dict):
            continue
        tid = _cap_id("::".join(str(p) for p in (t.get("filePath") or t.get("suite"), t.get("name") or "?") if p))
        out["total"] += 1
        status = t.get("status")
        retries = t.get("retries")
        if status == "failed":
            ms = _millis(t["duration"]) if isinstance(t.get("duration"), (int, float)) else None
            message = _text(t.get("message"))
            out["failed"].append(_failure(tid, None, message, _text(t.get("trace")) or message, ms))
        elif status == "passed" and (t.get("flaky") is True or isinstance(retries, (int, float)) and retries > 0):
            out["flaky"].append(tid)
        elif status in ("skipped", "pending"):
            out["skipped"] += 1
            if len(out["sk"]) < SKIP_KEEP:
                out["sk"].append(tid)
        ms = _millis(t["duration"]) if isinstance(t.get("duration"), (int, float)) else 0
        out["all"].append([tid, ms])
        if isinstance(t.get("duration"), (int, float)):
            slow.append([tid, ms])
    out["slow"] = sorted(slow, key=lambda x: -x[1])[:SLOW_KEEP]
    return out


def _jest(doc: dict) -> dict:
    """Jest's --json and Vitest's json reporter: each test named by its file and full name; a test that passed after
    retries (jest.retryTimes, Vitest retry) is a flake."""
    out, slow = _empty(), []
    for suite in doc.get("testResults") or []:
        if not isinstance(suite, dict):
            continue
        file = _repo_path(suite.get("name") or suite.get("testFilePath"))
        for t in suite.get("assertionResults") or []:
            if not isinstance(t, dict):
                continue
            name = t.get("fullName") or " ".join([*(str(a) for a in t.get("ancestorTitles") or []), str(t.get("title") or "?")])
            tid = _cap_id("::".join(p for p in (file, str(name)) if p))
            out["total"] += 1
            status = t.get("status")
            ms = _millis(t["duration"]) if isinstance(t.get("duration"), (int, float)) else 0
            retried = (isinstance(t.get("invocations"), int) and t["invocations"] > 1) or bool(t.get("retryReasons"))
            if status == "failed":
                text = next((m for m in t.get("failureMessages") or [] if isinstance(m, str)), None)
                out["failed"].append(_failure(tid, None, text, text, ms))
            elif status == "passed" and retried:
                out["flaky"].append(tid)
            elif status in JEST_SKIPPED:
                out["skipped"] += 1
                if len(out["sk"]) < SKIP_KEEP:
                    out["sk"].append(tid)
            out["all"].append([tid, ms])
            if isinstance(t.get("duration"), (int, float)):
                slow.append([tid, ms])
    out["slow"] = sorted(slow, key=lambda x: -x[1])[:SLOW_KEEP]
    return out


def _go(data: bytes) -> dict | None:
    """`go test -json` (and gotestsum): one test per package and full name, subtests apart from their parents (a parent
    fails whenever a subtest does); a test that failed and then passed in the same stream (a rerun) is a flake."""
    seen: dict[str, dict] = {}
    parents, seed, events = set(), None, 0
    for line in data.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue  # build output can sit between the events
        if not isinstance(e, dict) or not isinstance(e.get("Action"), str):
            continue
        events += 1
        output, name, pkg = _text(e.get("Output")), _text(e.get("Test")), _text(e.get("Package")) or ""
        if output and seed is None and (m := GO_SEED.search(output)):
            seed = m[1]
        if not name:
            continue
        parts = name.split("/")
        parents.update(f"{pkg}::{'/'.join(parts[:n])}" for n in range(1, len(parts)))
        info = seen.setdefault(_cap_id(f"{pkg}::{name}" if pkg else name), {**_case(), "lines": []})
        action = e["Action"]
        if action == "output" and output:
            info["lines"] = (info["lines"] + [output.rstrip("\n")])[-50:]
        elif action == "fail":
            found = next((m[1] for x in info["lines"] if (m := GO_LINE.match(x))), None)
            info["fail"] = info["fail"] or found or ""
            info["detail"] = info["detail"] or (None, found, "\n".join(info["lines"]))
        elif action == "pass":
            info["passed"] = True
        elif action == "skip":
            info["skipped"] = True
        if action in ("pass", "fail", "skip"):
            info["ms"] = max(info["ms"], _millis(e.get("Elapsed") or 0, 1000))
    if not events:
        return None
    # A parent fails whenever a subtest does, so it is left out then; failing with every subtest passing, it is its own.
    failed_below = {p for p in parents if any(t.startswith(p + "/") and i["fail"] is not None for t, i in seen.items())}
    out = _outcomes({tid: i for tid, i in seen.items()
                     if tid not in parents or (i["fail"] is not None and tid not in failed_below)})
    return {**out, "seed": seed} if seed else out


def _json(data: bytes) -> dict | None:
    try:
        doc = json.loads(data)
    except ValueError:
        return _go(data)  # an event stream, one JSON object per line
    if not isinstance(doc, dict):
        return None
    if "results" in doc:
        return _ctrf(doc)
    if isinstance(doc.get("testResults"), list):
        return _jest(doc)
    return _go(data) if isinstance(doc.get("Action"), str) else None


def parse_report(name: str, data: bytes) -> dict | None:
    """One JUnit XML, TRX, CTRF JSON, Jest or Vitest JSON, or `go test -json` file; None when it is none of them or is
    unsafe to read."""
    head = data.lstrip()[:1]
    low = name.lower()
    if low.endswith((".xml", ".trx")) or head == b"<":
        return _xml(data)
    if low.endswith((".json", ".jsonl", ".ndjson")) or head == b"{":
        return _json(data)
    return None


def merge(parts: list[dict]) -> dict:
    out = _empty()
    for p in parts:
        out["total"] += p["total"]
        out["skipped"] += p["skipped"]
        out["failed"] += p["failed"]
        out["flaky"] += p["flaky"]
        out["slow"] += p["slow"]
        out["sk"] += p.get("sk") or []
        out["all"] += p.get("all") or []
    out["slow"] = sorted(out["slow"], key=lambda x: -x[1])[:SLOW_KEEP]
    out["sk"] = out["sk"][:SKIP_KEEP]
    out["failed"], out["flaky"], out["all"] = out["failed"][:MAX_ROWS], out["flaky"][:MAX_ROWS], out["all"][:MAX_ALL]
    seed = next((p["seed"] for p in parts if p.get("seed")), None)
    return {**out, "seed": seed} if seed else out


def parse_archive(data: bytes, max_file_bytes: int = 20_000_000, max_total_bytes: int = 200_000_000,
                  max_files: int = 500) -> dict:
    """Every report inside an Actions artifact zip, read in memory with size limits (nothing is extracted)."""
    parts, skipped, total, cov = [], 0, 0, None
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist()[:max_files]:
            if info.is_dir() or not info.filename.lower().endswith(REPORT_FILES + (".info", ".lcov")):
                continue
            # Sizes are checked before reading, so a zip bomb is skipped, not unpacked.
            if info.file_size > max_file_bytes or total + info.file_size > max_total_bytes:
                skipped += 1
                continue
            total += info.file_size
            body = z.read(info)
            found = coverage.parse(info.filename, body) if info.filename.lower().endswith((".xml", ".info", ".lcov")) else None
            if found:
                cov = _merge_cov(cov, found)
                continue
            if info.filename.lower().endswith((".info", ".lcov")):
                continue
            parsed = parse_report(info.filename, body)
            if parsed is None:
                if info.filename.lower().endswith((".xml", ".trx")):
                    skipped += 1
                continue
            parts.append(parsed)
    # "cov" (coverage with its line hits) is read for patch coverage and never stored per report.
    return {**merge(parts), "skipped_files": skipped, **({"cov": cov} if cov else {})}


def _merge_cov(a: dict | None, b: dict) -> dict:
    """Two coverage files of one artifact as one: a line ran if it ran in either."""
    if a is None:
        return b
    files = a["files"]  # merged in place: copying everything again for each further file cost minutes on big reports
    for path, hits in b["files"].items():
        mine = files.setdefault(path, {})
        for n, h in hits.items():
            mine[n] = max(mine.get(n, 0), h)
    lines = sum(len(h) for h in files.values())
    covered = sum(1 for h in files.values() for x in h.values() if x > 0)
    return {"format": a["format"] if a["format"] == b["format"] else "mixed", "lines": lines, "covered": covered, "files": files}
