"""Coverage from the reports CI already uploads: Cobertura XML (coverage.py, Istanbul, Go's converters), LCOV and JaCoCo
XML, read safely in memory; and patch coverage, the share of a pull request's added lines that ran, from its diff."""
import math
import re

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import ParseError, fromstring

HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
# JaCoCo always names its DTD; a DOCTYPE with no internal subset declares nothing, so it is dropped and the rest is read
# with DTDs forbidden (entity tricks stay impossible).
PLAIN_DOCTYPE = re.compile(rb"<!DOCTYPE[^\[>]*>")
MISSED_KEEP = 50
PROLOG = 4096  # a DOCTYPE only appears before the root element; scanning further was quadratic on crafted files
ABSOLUTE = re.compile(r"^(?:/|[A-Za-z]:/)")


def _xml(data: bytes):
    try:
        return fromstring(PLAIN_DOCTYPE.sub(b"", data[:PROLOG], count=1) + data[PROLOG:], forbid_dtd=True)
    except (DefusedXmlException, ParseError, ValueError):
        return None


def _total(files: dict) -> tuple[int, int]:
    lines = sum(len(hits) for hits in files.values())
    return lines, sum(1 for hits in files.values() for h in hits.values() if h > 0)


def _int(text, default=0) -> int:
    try:
        value = float(text)
    except (TypeError, ValueError, OverflowError):
        return default
    return int(value) if math.isfinite(value) else default


def _cobertura(root) -> dict:
    files = {}
    for cls in root.iter("class"):
        name = cls.get("filename")
        if not name:
            continue
        hits = files.setdefault(name, {})
        for line in cls.iter("line"):
            n = _int(line.get("number"), None)
            if n is not None:
                hits[n] = max(hits.get(n, 0), _int(line.get("hits")))
    return files


def _jacoco(root) -> dict:
    files = {}
    for package in root.iter("package"):
        for source in package.iter("sourcefile"):
            hits = files.setdefault(f"{package.get('name')}/{source.get('name')}".strip("/"), {})
            for line in source.iter("line"):
                n = _int(line.get("nr"), None)
                if n is not None:
                    hits[n] = _int(line.get("ci"))
    return files


def _lcov(text: str) -> dict:
    files, cur = {}, None
    for line in text.split("\n"):
        line = line.rstrip("\r")
        if line.startswith("SF:"):
            cur = files.setdefault(line[3:].strip(), {})
        elif line.startswith("DA:") and cur is not None:
            parts = line[3:].split(",")
            if len(parts) >= 2:
                n = _int(parts[0], None)
                if n is not None:
                    cur[n] = max(cur.get(n, 0), _int(parts[1]))
        elif line.startswith("end_of_record"):
            cur = None
    return files


def parse(name: str, data: bytes) -> dict | None:
    """{"format", "lines", "covered", "files": {path: {line: hits}}} for a coverage report, else None."""
    data = data.removeprefix(b"\xef\xbb\xbf")  # a UTF-8 byte order mark
    low, head = name.lower(), data.lstrip()[:200]
    if low.endswith((".info", ".lcov")) or head.startswith((b"TN:", b"SF:")):
        files, kind = _lcov(data.decode("utf-8", "replace")), "lcov"
    elif head.startswith(b"<"):
        if b"<coverage" not in data[:2000] and b"<report" not in data[:2000]:
            return None
        root = _xml(data)
        if root is None or root.tag not in ("coverage", "report"):
            return None
        files, kind = (_cobertura(root), "cobertura") if root.tag == "coverage" else (_jacoco(root), "jacoco")
    else:
        return None
    files = {path: hits for path, hits in files.items() if hits}
    if not files:
        return None
    lines, covered = _total(files)
    return {"format": kind, "lines": lines, "covered": covered, "files": files}


def added_lines(patch: str | None) -> list[int]:
    """The new file's line numbers of the lines a unified diff adds."""
    out, cur = [], None
    # Only a newline ends a diff line: splitlines() also splits on form feeds and the like inside a line.
    for line in (patch or "").split("\n"):
        line = line.removesuffix("\r")
        found = HUNK.match(line)
        if found:
            cur = int(found.group(1))
        elif cur is None or line.startswith("\\"):
            continue
        elif line.startswith("+"):
            out.append(cur)
            cur += 1
        elif not line.startswith("-"):
            cur += 1
    return out


def _match(name: str, paths: list[str]) -> str | None:
    """The report's path for a repo file: the same path; else an absolute runner path ending with it (the shortest);
    else the longest path it ends with (paths relative to a source folder). A deeper relative path is another file."""
    norm = {p.replace("\\", "/"): p for p in paths}
    if name in norm:
        return norm[name]
    tail = "/" + name
    absolute = [p for p in norm if p.endswith(tail) and ABSOLUTE.match(p)]
    if absolute:
        return norm[min(absolute, key=len)]
    inner = [p for p in norm if name.endswith("/" + p)]
    return norm[max(inner, key=len)] if inner else None


def patch(cov: dict, files: list[dict]) -> dict:
    """{"lines", "covered", "missed": {file: [lines]}} over the added lines the report knows (lines it doesn't list, like
    docs or blank lines, aren't code that could run)."""
    paths = list(cov.get("files") or {})
    lines = covered = 0
    missed = {}
    for f in files:
        name = f.get("filename") or ""
        path = _match(name, paths)
        if not path:
            continue
        hits = cov["files"][path]
        for n in added_lines(f.get("patch")):
            if n in hits:
                lines += 1
                if hits[n] > 0:
                    covered += 1
                else:
                    missed.setdefault(name, []).append(n)
    return {"lines": lines, "covered": covered, "missed": {k: v[:MISSED_KEEP] for k, v in missed.items()}}
