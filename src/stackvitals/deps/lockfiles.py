"""Packages and versions from the lockfiles projects commit: npm's package-lock, and pip, uv, Poetry and Pipenv files."""
import json
import re
import tomllib
from collections import deque
from pathlib import Path
from urllib.parse import urlparse

from mergescout.signals.bumps import _norm

SUPPORTED = "package-lock.json, npm-shrinkwrap.json, requirements*.txt, uv.lock, poetry.lock, Pipfile.lock"
REGISTRY_HOSTS = {"npm": ("registry.npmjs.org", "registry.yarnpkg.com"), "pypi": ("pypi.org", "files.pythonhosted.org")}
REQUIREMENT = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*(?:==\s*([^\s,;]+))?")


def read_lockfile(path: Path) -> list[tuple[str, str, str | None]]:
    """(ecosystem, name, version) for every package the file pins, sorted; a file it can't read is a clear error."""
    path = Path(path)
    return parse_lockfile(path.name, path.read_text(encoding="utf-8"))


def is_lockfile(filename: str) -> bool:
    name = filename.rsplit("/", 1)[-1].lower()
    return name in ("package-lock.json", "npm-shrinkwrap.json", "uv.lock", "poetry.lock", "pipfile.lock") or (
        name.startswith("requirements") and name.endswith(".txt"))


def parse_lockfile(filename: str, text: str) -> list[tuple[str, str, str | None]]:
    name = filename.rsplit("/", 1)[-1].lower()
    if name in ("package-lock.json", "npm-shrinkwrap.json"):
        found = _npm(json.loads(text))
    elif name.endswith(".txt"):
        found = _requirements(text)
    elif name in ("uv.lock", "poetry.lock"):
        found = {("pypi", _norm("pypi", p["name"]), p.get("version")) for p in tomllib.loads(text).get("package") or []
                 if p.get("name") and not _local((p.get("source") or {}))}
    elif name == "pipfile.lock":
        doc = json.loads(text)
        found = {("pypi", _norm("pypi", n), (v.get("version") or "").lstrip("=") or None)
                 for section in ("default", "develop") for n, v in (doc.get(section) or {}).items()}
    else:
        raise ValueError(f"{filename} isn't a lockfile this reads yet; it reads {SUPPORTED}.")
    return sorted(found, key=lambda t: (t[0], t[1], t[2] or ""))


def _local(source: dict) -> bool:
    # uv lists the project itself and path dependencies; they aren't registry packages.
    return any(k in source for k in ("editable", "virtual", "directory", "path"))


def _npm(doc: dict) -> set:
    if isinstance(doc.get("packages"), dict):
        # v2/v3: "node_modules/a/node_modules/b" is package b, nested under a; an alias ("react": "npm:other@1") names the real one.
        return {("npm", _npm_name(key, v), v.get("version")) for key, v in doc["packages"].items()
                if key and "node_modules/" in key and isinstance(v, dict) and not v.get("link")}
    found = set()

    def walk(deps: dict) -> None:
        for n, v in (deps or {}).items():
            found.add(("npm", *_v1_alias(n, (v or {}).get("version"))))
            walk((v or {}).get("dependencies"))
    walk(doc.get("dependencies"))
    return found


def _v1_alias(name: str, version) -> tuple[str, str | None]:
    # v1 writes an alias as "version": "npm:real-name@1.2.3".
    if isinstance(version, str) and version.startswith("npm:") and "@" in version[5:]:
        real, _, ver = version[4:].rpartition("@")
        return real, ver
    return name, version


def _npm_name(key: str, entry: dict) -> str:
    name = entry.get("name")
    return name if isinstance(name, str) and name else key.rsplit("node_modules/", 1)[1]


def _host(url: str) -> str:
    parsed = urlparse(url.removeprefix("git+"))
    return parsed.hostname or (url.split(":", 1)[0] if ":" in url else "a local path")


def foreign_sources(filename: str, text: str) -> dict[tuple[str, str], str]:
    """Packages installed from somewhere other than the public registry (a git repo, a tarball URL, another index), with
    where from: evidence about the registry package of that name doesn't describe them."""
    name, out = filename.rsplit("/", 1)[-1].lower(), {}
    if name in ("package-lock.json", "npm-shrinkwrap.json"):
        doc = json.loads(text)
        if isinstance(doc.get("packages"), dict):
            entries = [(_npm_name(k, v), v) for k, v in doc["packages"].items()
                       if k and "node_modules/" in k and isinstance(v, dict) and not v.get("link")]
        else:
            entries = []

            def walk(deps):
                for n, v in (deps or {}).items():
                    entries.append((_v1_alias(n, (v or {}).get("version"))[0], v or {}))
                    walk((v or {}).get("dependencies"))
            walk(doc.get("dependencies"))
        for pkg, v in entries:
            url = v.get("resolved")
            if isinstance(url, str) and url and _host(url) not in REGISTRY_HOSTS["npm"]:
                out[("npm", pkg)] = _host(url)
    elif name in ("uv.lock", "poetry.lock"):
        for p in tomllib.loads(text).get("package") or []:
            src = p.get("source") or {}
            if not p.get("name") or _local(src):
                continue
            url = src.get("git") or src.get("url") or src.get("registry") or ""
            if isinstance(url, str) and url and (src.get("type") or "git") != "directory" and _host(url) not in REGISTRY_HOSTS["pypi"]:
                out[("pypi", _norm("pypi", p["name"]))] = _host(url)
    elif name == "pipfile.lock":
        doc = json.loads(text)
        for section in ("default", "develop"):
            for n, v in (doc.get(section) or {}).items():
                if isinstance(v, dict) and isinstance(v.get("git") or v.get("file"), str):
                    out[("pypi", _norm("pypi", n))] = _host(v.get("git") or v.get("file"))
    return out


def _requirements(text: str) -> set:
    found = set()
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        # Options (-e, -r, --hash) and URLs aren't registry packages.
        if not line or line.startswith("-") or "://" in line:
            continue
        m = REQUIREMENT.match(line)
        if m:
            found.add(("pypi", _norm("pypi", m.group(1)), m.group(2)))
    return found


def dependency_paths(filename: str, text: str, targets: set[str]) -> dict[str, list[str]]:
    """The shortest chain from a direct dependency to each target package (["express", "qs", "side-channel"]), for
    lockfiles that record the graph and which packages are direct (npm v2/v3, uv); none for the rest (poetry.lock
    doesn't say which are direct, so a guessed chain could name the wrong one) or a file that can't be read."""
    name = filename.rsplit("/", 1)[-1].lower()
    npm = name in ("package-lock.json", "npm-shrinkwrap.json")
    try:
        if npm:
            roots, children = _npm_graph(json.loads(text))
        elif name == "uv.lock":
            roots, children = _uv_graph(tomllib.loads(text))
        else:
            return {}
    except (ValueError, TypeError, AttributeError):
        return {}
    want = set(targets) if npm else {_norm("pypi", t) for t in targets}
    found, queue, seen = {}, deque((r, [label]) for r, label in roots), set()
    while queue and len(found) < len(want):
        node, path = queue.popleft()
        if node in seen:
            continue
        seen.add(node)
        if path[-1] in want and path[-1] not in found:
            found[path[-1]] = path
        queue.extend((child, path + [label]) for child, label in children.get(node, ()))
    return found


def _npm_graph(doc: dict) -> tuple[list, dict]:
    pkgs = doc.get("packages")
    if not isinstance(pkgs, dict):
        return [], {}

    def deps(entry: dict) -> list[str]:
        return [n for key in ("dependencies", "optionalDependencies", "devDependencies", "peerDependencies")
                for n in (entry.get(key) or {})]

    def resolve(parent: str, child: str) -> str | None:
        # Node looks in the parent's own node_modules, then each folder above it, then the top.
        here = parent
        while True:
            key = f"{here}/node_modules/{child}" if here else f"node_modules/{child}"
            if key in pkgs:
                return key
            if not here:
                return None
            here = here.rsplit("/node_modules/", 1)[0] if "/node_modules/" in here else ""
    children = {key: [(k, _npm_name(k, pkgs[k])) for c in deps(v) if (k := resolve(key, c))]
                for key, v in pkgs.items() if isinstance(v, dict)}
    return children.get("", []), children


def _uv_graph(doc: dict) -> tuple[list, dict]:
    packages = [p for p in doc.get("package") or [] if p.get("name")]
    edges = {_norm("pypi", p["name"]): [_norm("pypi", d["name"]) for key in ("dependencies",)
                                         for d in p.get(key) or [] if d.get("name")]
             + [_norm("pypi", d["name"]) for group in ("optional-dependencies", "dev-dependencies")
                for ds in (p.get(group) or {}).values() for d in ds if d.get("name")]
             for p in packages}
    # The project's own entries (a local source) name its direct dependencies.
    local = [_norm("pypi", p["name"]) for p in packages if _local(p.get("source") or {})]
    roots = [d for proj in local for d in edges.get(proj, [])]
    children = {n: [(d, d) for d in ds if d in edges] for n, ds in edges.items()}
    return [(r, r) for r in roots if r in edges], children
