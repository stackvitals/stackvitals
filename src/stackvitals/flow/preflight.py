import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from mergescout.github.graphql import GraphQLError, RateLimited
from stackvitals.flow.analyze import INSIDERS, _iso, _pct
from stackvitals.flow.knowledge import _areas, area
from stackvitals.flow.store import FlowStore

# What maintainers bring up in reviews, in plain categories. Only the categories are kept, never the text.
CATEGORIES = {
    "tests": r"\btests?\b|\btest cases?\b|\bcoverage\b",
    "docs": r"\bdocs?\b|\bdocumentation\b|\breadme\b|\bdocstrings?\b",
    "changelog": r"\bchange ?log\b|\bnews (entry|fragment)\b|\brelease notes?\b|\bchangesets?\b|\btowncrier\b",
    "style": r"\bnit\b|\blint\w*\b|\bformat\w*\b|\btypos?\b|\brename\b|\bnaming\b|\bwhitespace\b|\bstyle\b",
    "types": r"\btype (hint|annotation)s?\b|\btyping\b|\bmypy\b|\bpyright\b|\btype-?check\w*\b",
    "compatibility": r"\bbreaking\b|\bbackwards?[- ]compat\w*\b|\bdeprecat\w*\b",
    "performance": r"\bperformance\b|\bperf\b|\bslow(er)?\b|\ballocat\w*\b|\bbenchmark\w*\b",
    "scope": r"\bseparate pr\b|\bsplit (this|the|it)\b|\bout of scope\b|\bunrelated\b|\bsmaller prs?\b|\btoo (big|large)\b",
    "rebase": r"\brebase\b|\bmerge conflicts?\b|\bconflicts?\b",
    "description": r"\bpr description\b|\bdescription\b|\blink(ed)? (the |an |to the )?issue\b|\bmotivation\b",
    "security": r"\bsecurity\b|\bvulnerab\w*\b|\binjection\b|\bsanitiz\w*\b",
}
PATTERNS = {name: re.compile(rx, re.I) for name, rx in CATEGORIES.items()}
MIN_SCOPE_PRS = 10


def categories(text: str | None) -> set[str]:
    return {name for name, rx in PATTERNS.items() if text and rx.search(text)}


def _by_maintainer(item: dict, author: str | None) -> bool:
    who = item.get("author") or {}
    return item.get("authorAssociation") in INSIDERS and who.get("__typename") == "User" and who.get("login") != author


def asks_from(node: dict, author: str | None, paths: list[str]) -> list[list[str]]:
    """[category, area] pairs a PR's maintainers raised: review bodies apply to all its areas, line comments to their file's."""
    found = set()
    areas = _areas(paths) or {"(root)"}
    for review in (node.get("reviews") or {}).get("nodes") or []:
        if review and _by_maintainer(review, author):
            found |= {(c, a) for c in categories(review.get("body")) for a in areas}
    for thread in (node.get("reviewThreads") or {}).get("nodes") or []:
        where = area(thread.get("path") or "") if thread and thread.get("path") else None
        for comment in ((thread or {}).get("comments") or {}).get("nodes") or []:
            if comment and _by_maintainer(comment, author):
                found |= {(c, a) for c in categories(comment.get("body")) for a in ([where] if where else areas)}
    return [list(x) for x in sorted(found)]


def _query(numbers: list[int]) -> str:
    parts = "\n".join(
        f"  p{n}: pullRequest(number:{n}) {{ number\n"
        "    reviews(first:20) { nodes { body authorAssociation author { __typename login } } }\n"
        "    reviewThreads(first:30) { nodes { path comments(first:3) { nodes { body authorAssociation author { __typename login } } } } } }"
        for n in numbers)
    return f"query($owner:String!,$name:String!) {{ rateLimit {{ cost remaining resetAt }} repository(owner:$owner,name:$name) {{\n{parts}\n}} }}"


def _reviewed(p: dict) -> bool:
    return any(e[0] == "review" and e[4] in INSIDERS and e[2] != p.get("au") for e in p["ev"]) or \
        any(c[2] in INSIDERS and c[1] != p.get("au") for c in p["cm"])


def collect_asks(gql, store: FlowStore, owner: str, name: str, prs: list[dict], batch: int = 20, cap: int = 1000) -> dict:
    """Read review comments of closed PRs that maintainers commented on, once each, newest first, at most `cap` per run."""
    done = store.asks()
    todo = sorted((p for p in prs if p.get("st") != "OPEN" and p["n"] not in done and _reviewed(p)),
                  key=lambda p: p.get("cl") or "", reverse=True)
    take, read = todo[:cap], 0
    for i in range(0, len(take), batch):
        chunk = take[i:i + batch]
        try:
            repo = gql.query(_query([p["n"] for p in chunk]), {"owner": owner, "name": name}).data["repository"]
        except (GraphQLError, RateLimited):
            # The hourly limit or a slow page: keep what was read, the next run continues.
            break
        store.put_asks({p["n"]: asks_from(repo.get(f"p{p['n']}") or {}, p.get("au"), p.get("paths") or []) for p in chunk})
        read += len(chunk)
    return {"read": read, "left": len(todo) - read}


def preflight(prs: list[dict], asks: dict[int, list], paths: list[str], now: datetime, months: int = 12) -> dict:
    """What maintainers usually ask for on PRs touching these paths, with counts; the whole repo when history is thin."""
    since = _iso(now - timedelta(days=30 * months))
    read = [p for p in prs if p["n"] in asks and (p.get("cl") or "") >= since]
    targets = _areas(paths)
    local = [p for p in read if _areas(p.get("paths")) & targets]
    scoped = len(local) >= MIN_SCOPE_PRS
    pool = local if scoped else read
    counts = Counter()
    for p in pool:
        counts.update({cat for cat, a in asks[p["n"]] if not scoped or a in targets})
    n = len(pool)
    return {"scope": ", ".join(sorted(targets)) if scoped else "whole repo", "reviewed_prs": n,
            "asks": [{"ask": cat, "share": round(c / n, 4), "prs": c} for cat, c in counts.most_common()] if n else []}


TEST_FILE = re.compile(r"(^|/)(tests?|__tests__|spec|testing)(/|$)|(_test|\.test|\.spec|_spec)\.[a-z]+$|(^|/)test_[^/]+$", re.I)
CHANGELOG_FILE = re.compile(r"(^|/)(CHANGELOG|CHANGES|HISTORY|NEWS)(\.[a-z]+)?$|(^|/)(changelog\.d|changes|news|\.changeset|changelog)/", re.I)
DOCS_FILE = re.compile(r"(^|/)docs?/|\.(md|rst|adoc)$", re.I)
HABIT = 0.6


def _kinds(paths: list[str]) -> set[str]:
    out = set()
    for path in paths or []:
        if TEST_FILE.search(path):
            out.add("tests")
        if CHANGELOG_FILE.search(path):
            out.add("changelog")
        elif DOCS_FILE.search(path):
            out.add("docs")
    return out


class Habits:
    """Merged PRs indexed by folder once, so per-PR habits are cheap even with thousands of PRs."""

    def __init__(self, prs: list[dict], now: datetime, months: int = 12):
        since = _iso(now - timedelta(days=30 * months))
        merged = [p for p in prs if p.get("mg") and p["mg"] >= since and p.get("paths") and p.get("at") != "Bot"]
        self.kinds = [_kinds(p["paths"]) for p in merged]
        self.lines = [(p.get("add") or 0) + (p.get("del") or 0) for p in merged]
        self.by_area = defaultdict(list)
        for i, p in enumerate(merged):
            for a in _areas(p["paths"]):
                self.by_area[a].append(i)
        self.cache = {}

    def norms(self, paths: list[str]) -> dict:
        # Only folders with merged history are named (a PR's own folder names are never echoed back).
        targets = frozenset(a for a in _areas(paths) if a in self.by_area)
        if targets not in self.cache:
            local = sorted({i for a in targets for i in self.by_area[a]})
            scoped = len(local) >= MIN_SCOPE_PRS
            pool = local if scoped else range(len(self.lines))
            n = len(pool)
            kinds = Counter(k for i in pool for k in self.kinds[i])
            lines = [self.lines[i] for i in pool]
            self.cache[targets] = {
                "scope": ", ".join(sorted(targets)) if scoped else "whole repo", "merged_prs": n,
                "include": {k: round(kinds[k] / n, 4) if n else 0.0 for k in ("tests", "changelog", "docs")},
                "size": {"median_lines": _pct(lines, 0.5), "p75_lines": _pct(lines, 0.75), "p90_lines": _pct(lines, 0.9)}}
        return self.cache[targets]


def norms(prs: list[dict], paths: list[str], now: datetime, months: int = 12) -> dict:
    """What merged PRs touching these paths usually include (tests, changelog, docs) and how big they are."""
    return Habits(prs, now, months).norms(paths)


MAX_FOLDERS = 30


def folder_habits(prs: list[dict], asks: dict[int, list], now: datetime, index: Habits | None = None, months: int = 12,
                  cap: int = MAX_FOLDERS) -> list[dict]:
    """Per folder with enough merged history (busiest first): the norms and review asks the CLI's preflight gives for it."""
    index = index or Habits(prs, now, months)
    out = []
    for name, idx in sorted(index.by_area.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if len(idx) < MIN_SCOPE_PRS or len(out) >= cap:
            break
        # A file inside the folder: the same lookup as a planned PR touching only that folder.
        probe = "_" if name == "(root)" else f"{name}/_"
        h = index.norms([probe])
        asked = preflight(prs, asks, [probe], now, months)
        scoped = asked["scope"] != "whole repo"
        out.append({"area": name, "merged_prs": h["merged_prs"], "include": h["include"], "size": h["size"],
                    "reviewed_prs": asked["reviewed_prs"] if scoped else 0,
                    "asks": [a for a in asked["asks"] if a["share"] >= 0.05 and a["prs"] >= 3][:3] if scoped else []})
    return out


def gaps(pr: dict, habits: dict) -> list[dict]:
    """Where a PR differs from what merged PRs here usually do: missing tests/changelog/docs, or unusually big."""
    if not habits["merged_prs"]:
        return []
    have, out = _kinds(pr.get("paths")), []
    # Only the first 50 file names are read; a bigger PR may well include what we couldn't see.
    complete = not pr.get("files") or pr["files"] <= len(pr.get("paths") or [])
    labels = {"tests": "test files", "changelog": "a changelog entry", "docs": "docs"}
    for kind in ("tests", "changelog", "docs") if complete else ():
        share = habits["include"][kind]
        if share >= HABIT and kind not in have:
            out.append({"what": kind, "why": f"{share:.0%} of merged PRs in {habits['scope']} include {labels[kind]}"})
    lines = (pr.get("add") or 0) + (pr.get("del") or 0)
    p90 = habits["size"]["p90_lines"]
    if p90 is not None and lines > p90:
        out.append({"what": "size", "why": f"{lines} lines; 90% of merged PRs in {habits['scope']} have at most {p90}"})
    return out


def load_asks(path) -> dict[int, list]:
    out = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        # A line cut short by an interrupted write is skipped, never fatal.
        try:
            rec = json.loads(line) if line.strip() else None
        except ValueError:
            continue
        if isinstance(rec, dict) and "n" in rec:
            out[rec["n"]] = rec.get("a") or []
    return out
