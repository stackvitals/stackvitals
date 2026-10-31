"""CODEOWNERS read the way GitHub reads it, shared by CI Health, Team Flow and Portal: gitignore-style patterns, the last
matching line wins, a line without owners leaves its paths without owners."""
import re
from functools import lru_cache

# GitHub's lookup order: the first file found is the one it uses.
PATHS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")


def parse(text: str | None, skip=frozenset()) -> list[tuple[str, list[str]]]:
    """(pattern, owners) per rule line; comments, blank lines, "!" lines (unsupported by GitHub) and the line numbers in
    `skip` (lines GitHub's error check calls invalid, which GitHub skips) are left out."""
    rules = []
    for n, raw in enumerate((text or "").lstrip("\ufeff").splitlines(), 1):
        line = raw.strip()
        if n in skip:
            continue
        if not line or line.startswith(("#", "!")):
            continue
        # A space inside a path is written "\ ".
        pattern, *rest = re.split(r"(?<!\\)\s+", line)
        owners = []
        for token in rest:
            if token.startswith("#"):
                break
            owners.append(token)
        rules.append((pattern.replace("\\ ", " "), owners))
    return rules


def _glob(segment: str) -> str:
    return "".join("[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c) for c in segment)


@lru_cache(maxsize=65536)
def _regex(pattern: str) -> re.Pattern:
    # A slash at the start or in the middle ties the pattern to the repo root; otherwise it matches at any depth.
    anchored = pattern.startswith("/") or "/" in pattern.strip("/")
    segs = pattern.strip("/").split("/")
    rx = "" if anchored else "(?:.*/)?"
    for i, seg in enumerate(segs):
        first, last = i == 0, i == len(segs) - 1
        if seg == "**":
            rx += (".*" if first else "/.*") if last else ("(?:.*/)?" if first else "/(?:.*/)?")
            continue
        if not first and segs[i - 1] != "**":
            rx += "/"
        rx += _glob(seg)
    if segs[-1] == "**":
        pass
    elif pattern.endswith("/"):
        rx += "/.*"  # a folder: everything inside it
    elif not (segs[-1] == "*" and len(segs) > 1):
        rx += "(?:/.*)?"  # a file, or a folder and everything inside it; "docs/*" stays one level deep
    return re.compile(rx)


def matches(pattern: str, path: str) -> bool:
    return bool(_regex(pattern).fullmatch(path.lstrip("/")))


def owners_for(path: str, rules: list[tuple[str, list[str]]], unknown=frozenset()) -> list[str]:
    """The owners GitHub would request for this path, as written (@user, @org/team, email). Owners GitHub ignores
    (`unknown`, lowercase, from its error check) are left out; the matching line still decides, as on GitHub."""
    found = []
    for pattern, owners in rules:
        if matches(pattern, path):
            found = owners
    return [o for o in found if o.lower() not in unknown]
