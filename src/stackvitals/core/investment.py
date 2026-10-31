"""Where the work goes: each merged pull request sorted into feature, fix, maintenance, security or docs work from the
repo's own label rules, its Jira or Linear issue's type, common labels, its changelog fragment, its title (a Conventional
Commit or component prefix, or the leading verb) or the files it touched; the mix per month, with how each was decided.
People's and agents' work only: update bots are counted apart."""
import fnmatch
import re
from collections import Counter
from datetime import datetime

from stackvitals.core.actors import kind_of
from stackvitals.core.config import INVESTMENT as CATEGORIES

OTHER = "other"
# Common label names (the part after "type:", "kind/" and the like), checked in this order: security work wins.
LABELS = (("security", ("security", "vulnerability", "cve")),
          ("fix", ("bug", "fix", "bugfix", "regression", "defect", "hotfix")),
          ("feature", ("feature", "enhancement", "feat", "new feature", "feature request")),
          ("docs", ("documentation", "docs", "doc")),
          ("maintenance", ("chore", "refactor", "refactoring", "dependencies", "deps", "tech debt", "tech-debt", "ci",
                           "build", "maintenance", "performance", "perf", "cleanup", "test", "tests", "infra")))
TITLES = {"feat": "feature", "feature": "feature", "fix": "fix", "bugfix": "fix", "hotfix": "fix", "revert": "fix", "bug": "fix",
          "docs": "docs", "doc": "docs", "documentation": "docs", "security": "security", "sec": "security",
          "chore": "maintenance", "refactor": "maintenance", "ci": "maintenance", "build": "maintenance", "test": "maintenance",
          "tests": "maintenance", "testing": "maintenance", "perf": "maintenance", "style": "maintenance", "deps": "maintenance",
          "mnt": "maintenance", "maint": "maintenance", "bench": "maintenance", "release": "maintenance"}
CONVENTIONAL = re.compile(r"^\s*([A-Za-z]+)(?:\([^)]*\))?!?:")
# Changelog fragments (towncrier and the like) name their kind: news/1234.bugfix.rst, changelog/12.feature.md, CHANGES/9.bugfix.
FRAGMENT = re.compile(r"(?:^|/)(?:news|changes|changelog|changelog\.d|newsfragments)/[^/]+?\.([A-Za-z]+)(?:\.(?:rst|md|txt))?$",
                      re.I)
FRAGMENTS = {"security": "security", "bugfix": "fix", "bugfixes": "fix", "bug": "fix", "fix": "fix", "fixed": "fix",
             "feature": "feature", "features": "feature", "improvement": "feature", "enhancement": "feature", "added": "feature",
             "removal": "maintenance", "deprecation": "maintenance", "breaking": "maintenance", "misc": "maintenance",
             "trivial": "maintenance", "vendor": "maintenance", "process": "maintenance", "packaging": "maintenance",
             "contrib": "maintenance", "internal": "maintenance", "performance": "maintenance", "doc": "docs", "docs": "docs",
             "documentation": "docs"}
# A title's leading verb, once backport tags, a component prefix and a scope are set aside ("[3.14] dialects: (llvm) add").
VERBS = {**dict.fromkeys(("fix", "fixes", "fixed", "fixing", "revert", "resolve", "resolves", "correct", "repair", "prevent",
                          "avoid", "handle", "restore", "preserve", "don't"), "fix"),
         **dict.fromkeys(("add", "adds", "added", "adding", "implement", "implements", "introduce", "support", "allow",
                          "enable", "expose", "new", "create", "provide", "feat", "feature"), "feature"),
         **dict.fromkeys(("refactor", "remove", "removes", "drop", "clean", "cleanup", "bump", "upgrade", "deprecate",
                          "simplify", "move", "rename", "replace", "migrate", "speed", "optimize", "optimise", "vendor", "pin",
                          "unpin", "release", "prepare", "tidy", "reorganize", "restructure", "test", "tests", "skip", "lint",
                          "use", "rework", "extract", "split", "switch"), "maintenance"),
         **dict.fromkeys(("document", "documents", "docs", "doc", "typo", "readme", "clarify"), "docs")}
DOCS = ("docs/*", "doc/*", "*.md", "*.rst", "*.adoc", "mkdocs.yml", "LICENSE*")
TESTS = ("tests/*", "test/*", "testing/*", "__tests__/*", "*_test.*", "test_*", "*.spec.*", "*.test.*", "conftest.py")
UPKEEP = (".github/*", "*.lock", "*lock.json", "*lock.yaml", "go.sum", "requirements*.txt", ".pre-commit-config.yaml",
          "Dockerfile*", ".gitignore", "renovate.json", ".editorconfig")
ORDER = ("security", "fix", "feature", "maintenance", "docs")  # when a PR carries fragments of several kinds
RELEASE = re.compile(r"^\s*(?:(?:prepare\s+)?release\b(?!s)|bump\s+version\b|v?\d+\.\d+(?:\.\d+)?\s*$)", re.I)
TRACKER = {"BUG": "fix", "INCIDENT": "fix", "REQUIREMENT": "feature"}
MONTHS = 6


def _key(label: str) -> str:
    # "type: bug", "kind/bug", "T-bug", "🐛 bug" all read as "bug".
    last = re.split(r"[:/]", label.lower())[-1]
    return re.sub(r"^[^a-z0-9]+", "", last).removeprefix("t-").strip(" -_")


def _all(paths: list[str], patterns: tuple) -> bool:
    return bool(paths) and all(any(fnmatch.fnmatch(p, g) or fnmatch.fnmatch(p.rsplit("/", 1)[-1], g) for g in patterns)
                               for p in paths)


def _verb(title: str) -> str | None:
    t = re.sub(r"^\s*(\[[^\]]*\]\s*)+", "", title)
    t = re.sub(r"^\s*[\w./-]+:\s*", "", t)
    t = re.sub(r"^\(([^)]*)\)\s*", "", t)
    word = re.match(r"[A-Za-z]+(?:'t)?", t)
    return word.group(0).lower() if word else None


def classify(pr: dict, rules: dict | None = None, tracker_type: str | None = None) -> tuple[str, str]:
    """(category, how it was decided) for one pull request."""
    labels = pr.get("lb") or []
    low = {x.lower(): x for x in labels}
    for cat in CATEGORIES:
        for name in (rules or {}).get(cat) or []:
            if name.lower() in low:
                return cat, f"label {low[name.lower()]} (this repo's rule)"
    keys = {_key(x): x for x in labels}
    if any(k in keys for k in LABELS[0][1]):
        return "security", f"label {next(keys[k] for k in LABELS[0][1] if k in keys)}"
    if tracker_type in TRACKER:
        return TRACKER[tracker_type], f"issue type {tracker_type.lower()}"
    for cat, names in LABELS[1:]:
        hit = next((keys[k] for k in names if k in keys), None)
        if hit:
            return cat, f"label {hit}"
    title = pr.get("ti") or ""
    # A release PR gathers every changelog fragment, so its title decides (pip's "Release 26.2").
    if RELEASE.match(title):
        return "maintenance", "title release"
    found = CONVENTIONAL.match(title)
    if found and found.group(1).lower() in TITLES:
        return TITLES[found.group(1).lower()], f"title {found.group(1).lower()}:"
    paths = pr.get("paths") or []
    fragments = [k.lower() for p in paths if (m := FRAGMENT.search(p)) and (k := m.group(1)).lower() in FRAGMENTS]
    kinds = {FRAGMENTS[k] for k in fragments}
    if len(fragments) >= 3 and len(kinds) >= 2:
        return "maintenance", "changelog fragments of several kinds"  # release notes gathered or edited
    if fragments:
        kind = min(fragments, key=lambda k: ORDER.index(FRAGMENTS[k]))
        return FRAGMENTS[kind], f"changelog fragment {kind}"
    if _all(paths, DOCS):
        return "docs", "only docs files"
    if _all(paths, TESTS):
        return "maintenance", "only test files"
    if _all(paths, UPKEEP):
        return "maintenance", "only CI or dependency files"
    if "[NFC]" in title:
        return "maintenance", "title [NFC]"
    verb = _verb(title)
    if verb in VERBS:
        return VERBS[verb], f"title verb {verb}"
    if re.search(r"\b(fix|fixes|fixed|bug|crash|regression)\b", title, re.I):
        return "fix", "title mentions a fix"
    return OTHER, "no label, issue type, changelog fragment, title or file pattern"


def mix(prs: list[dict], now: datetime, rules: dict | None = None, tracker_types: dict | None = None,
        months: int = MONTHS, base: str | None = None) -> dict | None:
    """Merged PRs into the default branch (`base`; backports to release branches would count the work twice) of the
    last `months` calendar months (this one so far) by category and month, how each category was decided, and the update
    bots' PRs counted apart; None without a merged PR."""
    first = (now.year * 12 + now.month - 1) - (months - 1)
    since = f"{first // 12:04d}-{first % 12 + 1:02d}"
    merged = [p for p in prs if p.get("mg") and p["mg"][:7] >= since and (base is None or p.get("base") in (None, base))]
    work = [p for p in merged if kind_of(p.get("au"), p.get("at")) in ("person", "agent")]
    if not work:
        return None
    by_month, total, how, examples = {}, Counter(), Counter(), {}
    for p in sorted(work, key=lambda p: p["mg"]):
        cat, why = classify(p, rules, (tracker_types or {}).get(p["n"]))
        by_month.setdefault(p["mg"][:7], Counter())[cat] += 1
        total[cat] += 1
        how[why.split(" ")[0] if cat != OTHER else OTHER] += 1
        examples.setdefault(cat, []).append(p["n"])
    order = (*CATEGORIES, OTHER)
    return {"since": since, "months": [{"month": m, "n": sum(c.values()), "counts": {k: c.get(k, 0) for k in order}}
                                       for m, c in sorted(by_month.items())],
            "n": len(work), "counts": {k: total.get(k, 0) for k in order},
            "shares": {k: round(total.get(k, 0) / len(work), 4) for k in order},
            "decided_by": dict(how.most_common()), "examples": {k: v[-5:] for k, v in examples.items()},
            "bots": len(merged) - len(work)}


def tracker_types(prs: list[dict], issues: list[dict]) -> dict[int, str]:
    """Each PR's linked Jira or Linear issue type; with several, the most telling (incident, bug, requirement, task)."""
    from stackvitals.connectors.tracker import pr_links
    rank = {"INCIDENT": 0, "BUG": 1, "REQUIREMENT": 2, "TASK": 3}
    types = {i["key"]: i.get("type") or "TASK" for i in issues}
    out = {}
    for n, key in pr_links(prs, issues):
        if n not in out or rank.get(types[key], 3) < rank.get(out[n], 3):
            out[n] = types[key]
    return out


def by_epic(prs: list[dict], issues: list[dict], now: datetime, months: int = MONTHS, base: str | None = None) -> dict | None:
    """Merged people's PRs linked to Jira or Linear issues, by the epic (Jira) or project (Linear) those belong to, and
    the share linked to feature work (requirements), which teams often capitalise; None without a linked PR."""
    from stackvitals.connectors.tracker import pr_links
    first = (now.year * 12 + now.month - 1) - (months - 1)
    since = f"{first // 12:04d}-{first % 12 + 1:02d}"
    # Into the default branch only, as in the monthly mix: a backport would count the same work twice.
    work = [p for p in prs if p.get("mg") and p["mg"][:7] >= since and kind_of(p.get("au"), p.get("at")) in ("person", "agent")
            and (base is None or p.get("base") in (None, base))]
    by_key = {i["key"]: i for i in issues}
    linked = {}
    for n, key in pr_links(work, issues):
        linked.setdefault(n, []).append(by_key[key])
    if not linked:
        return None
    epics, titles, features = Counter(), {}, 0
    for found in linked.values():
        tagged = [i for i in found if i.get("epic")]
        if tagged:
            epics[tagged[0]["epic"]] += 1
            titles.setdefault(tagged[0]["epic"], tagged[0].get("epic_title"))
        features += any(i.get("type") == "REQUIREMENT" for i in found)
    total = len(linked)
    return {"since": since, "linked": total, "no_epic": total - sum(epics.values()),
            "epics": [{"epic": e, "title": titles.get(e), "prs": n, "share": round(n / total, 4)} for e, n in epics.most_common(10)],
            "feature_share": round(features / total, 4)}
