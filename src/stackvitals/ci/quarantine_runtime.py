"""Quarantine at test time, so a flaky test stops failing the suite without wrapping the CI command.

    stackvitals ci quarantine --print jest     # flags for the test runner, from the quarantine list
    pytest $(stackvitals ci quarantine --print pytest)   # writes .stackvitals-quarantine.json, prints -p ...

pytest runs a quarantined test as an expected failure (it still runs and reports, but can't fail the suite); Jest,
Vitest, go test, Playwright, Maven Surefire and dotnet test leave it out by name. Other runners (RSpec, Gradle): wrap the
command with `stackvitals ci quarantine -- <command>`. Only tests on the list are touched, and an empty or unreadable list touches none.
"""
import json
import os
import re
from pathlib import Path


def _parts(tid: str) -> tuple[str, str]:
    # "file::class::name" (JUnit, Jest) or "pkg::TestName/sub" (Go): what's before the last part, and the last part.
    head, _, name = tid.rpartition("::")
    return head, name


def runtime_args(ids: list[str] | set[str], runner: str) -> list[str]:
    """The command-line arguments that keep quarantined tests from failing a run of `runner`."""
    ids = sorted(ids or [])
    if not ids:
        return []
    if runner == "pytest":
        return ["-p", "stackvitals.ci.quarantine_runtime"]
    if runner in ("jest", "vitest"):
        names = sorted({re.escape(_parts(t)[1]) for t in ids if _parts(t)[1]})
        flag = "--testNamePattern" if runner == "jest" else "-t"
        # Runners match the full name (describe blocks first), so the test's own name is matched at the end.
        return [flag, f"^(?!.*(?:{'|'.join(names)})$).*"]
    if runner == "go":
        # go test -skip takes one pattern per level; only top-level tests can be listed together safely.
        tops = sorted({re.escape(_parts(t)[1]) for t in ids
                       if re.fullmatch(r"(Test|Fuzz|Example)[A-Z0-9_]\w*", _parts(t)[1] or "")})
        return ["-skip", f"^(?:{'|'.join(tops)})$"] if tops else []
    if runner == "playwright":
        # The full title ends with the test's own name; --grep-invert leaves those out.
        names = sorted({re.escape(_parts(t)[1]) for t in ids if _parts(t)[1]})
        return ["--grep-invert", f"(?:{'|'.join(names)})$"]
    if runner == "maven":
        # Surefire 2.19+: exclusion-only patterns run everything else; the class is the last part of the classname.
        pats = sorted({f"!{_parts(t)[0].split('::')[-1].split('.')[-1]}#{_parts(t)[1]}" for t in ids if _parts(t)[0] and _parts(t)[1]})
        return [f"-Dtest={','.join(pats)}", "-Dsurefire.failIfNoSpecifiedTests=false"] if pats else []
    if runner == "dotnet":
        fqns = sorted({f"{_parts(t)[0].split('::')[-1]}.{_parts(t)[1]}" for t in ids if _parts(t)[0] and _parts(t)[1]})
        return ["--filter", "&".join(f"FullyQualifiedName!={f}" for f in fqns)] if fqns else []
    raise ValueError(f"runner is one of pytest, jest, vitest, go, playwright, maven, dotnet, not {runner!r}")


LIST_FILE = ".stackvitals-quarantine.json"  # written by `stackvitals ci quarantine --print pytest`


def _quarantined() -> set[str]:
    src = os.environ.get("STACKVITALS_QUARANTINE") or LIST_FILE
    try:
        items = json.loads(Path(src).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {str(i) for i in items} if isinstance(items, list) else set()


def _tokens(text: str) -> list[str]:
    # "tests.test_a.TestCls" and "tests/test_a.py::TestCls" both read as tests, test_a, TestCls.
    return [p for p in re.split(r"[./:\\]+", text) if p and p != "py"]


def _matches(tid: str, nodeid: str, name: str) -> bool:
    # Same test name, and the report's module and class end the same way as the node id's file and class (either may
    # carry more folders in front, since the two can start from different roots).
    head, last = _parts(tid)
    if last != name:
        return False
    a, b = _tokens(head), _tokens(nodeid.rpartition("::")[0])
    if not a or not b:
        return not a
    n = min(len(a), len(b))
    return a[-n:] == b[-n:]


def pytest_collection_modifyitems(config, items):  # pragma: no cover - exercised through pytest itself
    import pytest
    ids = _quarantined()
    if not ids:
        return
    for item in items:
        if any(_matches(t, item.nodeid, item.name) for t in ids):
            item.add_marker(pytest.mark.xfail(reason="quarantined by StackVitals (known flaky)", strict=False))
