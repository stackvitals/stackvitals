"""Dependency-update PRs (Dependabot, Renovate) read from their titles and branch names: which package, which versions,
how big a step. The upgrade ledger counts how these PRs ended across the crawl."""
import re

from mergescout.crawl.queries import is_dep_bot

# Dependabot's branch says the package manager: dependabot/<manager>/<path>/<package>-<version>.
MANAGERS = {"npm_and_yarn": "npm", "npm": "npm", "bun": "npm", "pip": "pypi", "pipenv": "pypi", "poetry": "pypi",
            "uv": "pypi", "pip_compile": "pypi", "github_actions": "actions", "cargo": "cargo", "go_modules": "go",
            "maven": "maven", "gradle": "maven", "bundler": "rubygems", "composer": "packagist", "nuget": "nuget",
            "docker": "docker"}
# Renovate names the kind of dependency in its title ("update rust crate serde", "update actions/checkout action").
RENOVATE_KINDS = {"rust crate": "cargo", "module": "go", "action": "actions", "docker tag": "docker", "docker digest": "docker",
                  "digest": None, "container image": "docker", "image": "docker", "helm release": "helm", "chart": "helm",
                  "gem": "rubygems", "plugin": None, "pre-commit hook": None, "package": None, "dependency": None}
KINDS = "rust crate|module|docker tag|docker digest|container image|image|helm release|chart|gem|plugin|pre-commit hook|package|dependency"
WHATS = "action|monorepo|packages|docker tag|docker digest|digest"

# Leading noise: emoji and a "chore(ci)(deps):"-style prefix of any language; "[Security]" tags are removed first.
PREFIX = re.compile(r"^\W*(?:[^:]{1,40}?:\s+)?")
SECURITY = re.compile(r"\s*\[security\]\s*", re.I)
AUTOCLOSED = re.compile(r"\s+-\s+autoclosed$", re.I)
BASE_BRANCH = re.compile(r"\s+\((?!major\))[^()]*\)$", re.I)
NOT_UPDATE = re.compile(r"^(?:configure renovate|migrate renovate config|pin\b)", re.I)

DEPENDABOT = re.compile(r"^bump (?P<pkg>\S+) from (?P<old>\S+) to (?P<new>\S+)(?: in .*)?$", re.I)
DEPENDABOT_RANGE = re.compile(r"^update (?P<pkg>\S+) requirement from (?P<old>.+?) to (?P<new>.+?)(?: in .*)?$", re.I)
DEPENDABOT_GROUP = re.compile(r"^bump the \S+ group|^bump \S+(?:,| and )|^bump \S+ packages from", re.I)
ARROW = re.compile(rf"^update (?:(?P<kind>{KINDS}) )?(?P<pkg>\S+) \(\s*(?P<old>\S+)\s*(?:→|➔|->)\s*(?P<new>\S+)\s*\)", re.I)
RENOVATE = re.compile(rf"^update (?:(?P<kind>{KINDS}) )?(?P<pkg>\S+)(?: (?P<what>{WHATS}))?(?: from (?P<old>\S+))? to (?P<new>\S+)",
                      re.I)
RENOVATE_GROUP = re.compile(r"^update all |^lock file maintenance|monorepo", re.I)
VERSION = re.compile(r"^[\^~=<>]*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?")


def _norm(eco: str | None, name: str) -> str:
    # PyPI names compare case- and separator-insensitively (PEP 503); others are kept as written.
    return re.sub(r"[-_.]+", "-", name.lower()) if eco == "pypi" else name


def _version(text: str) -> str:
    # "v14.0.3" -> "14.0.3"; ranges ("^0.57.0") stay as written.
    return text[1:] if re.match(r"^v\d", text) else text


def bump_size(old: str | None, new: str | None) -> str | None:
    """major / minor / patch from two versions; 0.x minor steps count as major, since semver lets them break."""
    a, b = VERSION.match(old or ""), VERSION.match(new or "")
    if not a or not b:
        return None
    x = [int(v or 0) for v in a.groups()]
    y = [int(v or 0) for v in b.groups()]
    if x[0] != y[0] or (x[0] == 0 and x[1] != y[1]):
        return "major"
    return "minor" if x[1] != y[1] else "patch"


def parse_bump(title: str | None, head: str | None, login: str | None) -> dict | None:
    """One dependency-update PR as {bot, ecosystem, package, from_version, to_version, bump, grouped, security,
    closed_by_bot}, or None when it isn't an update (another author, Renovate's setup or pin PRs)."""
    if not is_dep_bot(login, head) or not title:
        return None
    bot = "dependabot" if (head or "").lower().startswith("dependabot") or (login or "").lower().startswith("dependabot") \
        else "renovate"
    text = SECURITY.sub(" ", title).strip()
    closed_by_bot = AUTOCLOSED.search(text) is not None
    text = PREFIX.sub("", AUTOCLOSED.sub("", text)).strip()
    if NOT_UPDATE.match(text):
        return None
    out = {"bot": bot, "ecosystem": None, "package": None, "from_version": None, "to_version": None, "bump": None,
           "grouped": False, "security": SECURITY.search(title) is not None, "closed_by_bot": closed_by_bot}
    if bot == "dependabot":
        parts = (head or "").split("/")
        eco = out["ecosystem"] = MANAGERS.get(parts[1]) if len(parts) > 1 else None
        # One package in several folders comes on a "multi-" branch without versions in the title.
        if DEPENDABOT_GROUP.match(text) or "/multi-" in (head or ""):
            return {**out, "grouped": True}
        if m := DEPENDABOT.match(text):
            return {**out, "package": _norm(eco, m["pkg"]), "from_version": m["old"], "to_version": m["new"],
                    "bump": bump_size(m["old"], m["new"])}
        if m := DEPENDABOT_RANGE.match(text):
            return {**out, "package": _norm(eco, m["pkg"]), "from_version": m["old"], "to_version": m["new"], "bump": "range"}
        return out
    if m := ARROW.match(text):
        eco = RENOVATE_KINDS.get((m["kind"] or "image").lower())
        return {**out, "ecosystem": eco, "package": _norm(eco, m["pkg"]), "from_version": _version(m["old"]),
                "to_version": _version(m["new"]), "bump": bump_size(m["old"], m["new"])}
    text = BASE_BRANCH.sub("", text)
    grouped = RENOVATE_GROUP.search(text) is not None
    m = RENOVATE.match(text)
    if not m:
        # A Renovate update without "to <version>" is a named group ("update frontend dependencies").
        return {**out, "grouped": True}
    kind = (m["what"] or m["kind"] or "dependency").lower()
    eco, new = RENOVATE_KINDS.get(kind), _version(m["new"])
    if "digest" in kind:
        bump = "digest"
    elif m["old"]:
        bump = bump_size(m["old"], new)
    else:
        # Renovate writes only the new major for major updates ("to v19"), the full version otherwise.
        bump = "major" if "(major)" in text.lower() or re.fullmatch(r"v?\d+", m["new"]) else "nonmajor"
    return {**out, "ecosystem": eco, "package": None if grouped else _norm(eco, m["pkg"]), "grouped": grouped,
            "from_version": _version(m["old"]) if m["old"] else None, "to_version": new, "bump": bump}
