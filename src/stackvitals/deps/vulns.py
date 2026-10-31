"""Known vulnerabilities in every package of every lockfile, in every ecosystem OSV covers (npm, PyPI, Go, Rust, Maven,
RubyGems, NuGet, Composer and more), from Google's OSV-Scanner run on the repo's lockfiles. The binary is pinned and
checked against its published SHA-256; the lockfiles are read through the API, so the repo's code is never checked out.
With outside lookups off, the scanner uses OSV's downloaded databases, so no package name leaves the runner."""
import hashlib
import json
import os
import platform
import re
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from stackvitals.core.time import iso

SCANNER = "2.7.0"
RELEASES = f"https://github.com/google/osv-scanner/releases/download/v{SCANNER}"
SHA256 = {
    "osv-scanner_linux_amd64": "160c6253e2922e9e0a6a9771c5c4c40a4b3c6090b34a3cdd5e80c96cc2e4218b",
    "osv-scanner_linux_arm64": "4061ef4c021ed3c47f203b818f337e351336cc5cd67c0274fc36bd1dfc728dd7",
    "osv-scanner_darwin_amd64": "e82c5df7ab0a42dff29a1cd0660711447b56b4c0483ff66ad8634df10fd81a45",
    "osv-scanner_darwin_arm64": "d4926ef8da134332543be276dff157e4c170f99ad91fc48e89448a8816bdf70b",
    "osv-scanner_windows_amd64.exe": "9964ed64ec9a387391eb4cc006ad5c531154821aef29b793e02c448de4686438",
    "osv-scanner_windows_arm64.exe": "3e630381c1f1fd3c9c4d447e6ff2ef6c737083371722773db8337eead0f97962",
}
# Every lockfile and manifest the scanner reads (osv-scalibr's extractors), by file name.
LOCKFILES = re.compile(
    r"(^|/)(package-lock\.json|npm-shrinkwrap\.json|yarn\.lock|pnpm-lock\.yaml|bun\.lock|deno\.lock"
    r"|requirements[^/]*\.txt|poetry\.lock|uv\.lock|Pipfile\.lock|pdm\.lock|pylock(\.[^/]+)?\.toml"
    r"|go\.mod|Cargo\.lock|Gemfile\.lock|gems\.locked|composer\.lock|packages\.lock\.json|paket\.lock"
    r"|(buildscript-)?gradle\.lockfile|verification-metadata\.xml|pom\.xml|mix\.lock|pubspec\.lock"
    r"|Package\.resolved|renv\.lock|conan\.lock|cabal\.project\.freeze|stack\.yaml\.lock"
    # .NET project files (a side-by-side found a remote-code-execution advisory we missed for want of these), and SBOMs.
    r"|[^/]+\.(csproj|fsproj|vbproj)|packages\.config|Directory\.Packages\.props"
    r"|[^/]+\.spdx(\.json)?|[^/]+\.cdx\.(json|xml)|bom\.(json|xml))$")
# Lockfiles in these folders belong to vendored code, tests or fixtures, not to what the project ships.
SKIP = re.compile(r"(^|/)(node_modules|vendor|third_party|testdata|test-data|fixtures?|__fixtures__|\.git)/")
MAX_FILES, MAX_BYTES = 200, 5_000_000
RESCAN = timedelta(hours=6)  # new advisories for unchanged lockfiles
LEVELS = ((9.0, "critical"), (7.0, "high"), (4.0, "moderate"), (0.1, "low"))


class ScannerError(RuntimeError):
    pass


def asset() -> str | None:
    system = {"linux": "linux", "darwin": "darwin", "win32": "windows"}.get(sys.platform)
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "amd64" if machine in ("x86_64", "amd64") else None
    if not system or not arch:
        return None
    return f"osv-scanner_{system}_{arch}" + (".exe" if system == "windows" else "")


def ensure_scanner(cache_dir: Path, client=None) -> Path:
    """The pinned scanner, downloaded once and kept; refused unless it matches the published SHA-256."""
    name = asset()
    if not name:
        raise ScannerError(f"no OSV-Scanner build for {sys.platform} {platform.machine()}")
    path = Path(cache_dir) / f"osv-scanner-{SCANNER}" / name
    if path.exists() and _sha256(path.read_bytes()) == SHA256[name]:
        return path
    own = client is None
    if own:
        import httpx
        client = httpx.Client(timeout=120, follow_redirects=True, headers={"User-Agent": "stackvitals"})
    try:
        body = client.get(f"{RELEASES}/{name}").raise_for_status().content
    except Exception as exc:  # noqa: BLE001 - any download trouble is said, never fatal
        raise ScannerError(f"OSV-Scanner download failed ({type(exc).__name__})") from exc
    finally:
        if own:
            client.close()
    if _sha256(body) != SHA256[name]:
        raise ScannerError("OSV-Scanner download didn't match its published SHA-256; not run")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def tool_dir(env: dict) -> Path:
    # The runner's tool cache, which the Action keeps between runs; a temp folder elsewhere.
    return Path(env.get("RUNNER_TOOL_CACHE") or tempfile.gettempdir()) / "stackvitals"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def scannable(path: str) -> bool:
    return bool(LOCKFILES.search(path)) and not SKIP.search(path)


def lockfile_blobs(api, ref: str) -> list[dict]:
    """The repo's lockfiles at a commit, from one tree read: path, blob sha and size."""
    tree = api._get(f"/repos/{api.repo}/git/trees/{ref}", {"recursive": "1"})
    return [{"path": t["path"], "sha": t["sha"], "size": t.get("size") or 0} for t in tree.get("tree") or []
            if t.get("type") == "blob" and scannable(t["path"])][:MAX_FILES]


DOT = "_dot"


def _plain(path: str) -> str:
    # The scanner skips folders named with a leading dot (.devcontainer), so they get a plain name while scanning.
    return "/".join(DOT + s if s.startswith(".") else s for s in path.split("/"))


def _real(path: str) -> str:
    return "/".join(s[len(DOT):] if s.startswith(DOT + ".") else s for s in path.split("/"))


def fetch(api, blobs: list[dict], ref: str, dest: Path) -> list[str]:
    """Write each lockfile under `dest` at its own path; very large ones are skipped and named."""
    skipped = []
    for b in blobs:
        if b["size"] > MAX_BYTES:
            skipped.append(b["path"])
            continue
        target = dest / _plain(b["path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(api.file(b["path"], ref))
    return skipped


def run_scanner(binary: Path, folder: Path, offline: bool, timeout: int = 600, all_packages: bool = False) -> dict:
    """The scanner's JSON report. Exit 1 means it found vulnerabilities; anything else non-zero is trouble."""
    # No call analysis: it needs the source, which isn't fetched, and with Go installed (as on GitHub's runners) its
    # failure on a lone go.mod failed the whole scan. Reachability comes from govulncheck run in the repo's own workflow.
    args = [str(binary), "scan", "source", "-r", "--format", "json", "--no-call-analysis=go",
            *(["--all-packages"] if all_packages else [])]
    if offline:
        # OSV's own databases, downloaded whole: the package names never leave the runner; no resolving either.
        args += ["--offline-vulnerabilities", "--download-offline-databases", "--no-resolve"]
    # Downloaded databases are kept beside the scanner, so a cached tool folder reuses them.
    run = subprocess.run([*args, str(folder)], capture_output=True, timeout=timeout,
                         env={**os.environ, "NO_COLOR": "1", "OSV_SCANNER_LOCAL_DB_CACHE_DIRECTORY": str(Path(binary).parent / "db")})
    if run.returncode not in (0, 1) or not run.stdout.strip():
        tail = run.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or ["no output"]
        raise ScannerError(f"OSV-Scanner exit {run.returncode}: {tail[0][:200]}")
    return json.loads(run.stdout.decode("utf-8"))


def _key(version: str) -> list:
    return [(0, int(p)) if p.isdigit() else (1, p) for p in re.split(r"[.\-+_]", str(version)) if p]


def _fixed(vulns: list[dict], ids: set[str], ecosystem: str, name: str, version: str) -> str | None:
    # The lowest version that fixes every advisory of the group and is newer than the one installed.
    best = None
    for v in vulns:
        if v.get("id") not in ids:
            continue
        for a in v.get("affected") or []:
            pkg = a.get("package") or {}
            if pkg.get("name") != name or pkg.get("ecosystem") != ecosystem:
                continue
            for r in a.get("ranges") or []:
                for e in r.get("events") or []:
                    f = e.get("fixed")
                    if f and _key(f) > _key(version) and (best is None or _key(f) < _key(best)):
                        best = f
    return best


def _level(group: dict, vulns: list[dict], ids: set[str]) -> str:
    try:
        score = float(group.get("max_severity") or 0)
    except ValueError:
        score = 0
    for floor, name in LEVELS:
        if score >= floor:
            return name
    labels = [str((v.get("database_specific") or {}).get("severity") or "").lower() for v in vulns if v.get("id") in ids]
    for name in ("critical", "high", "moderate", "medium", "low"):
        if name in labels:
            return "moderate" if name == "medium" else name
    return "unrated"


def findings(doc: dict, root: Path) -> list[dict]:
    """One row per advisory group per package per lockfile, with the version that fixes it."""
    out, base = [], str(Path(root).resolve()).replace("\\", "/").rstrip("/") + "/"
    for result in doc.get("results") or []:
        source = str((result.get("source") or {}).get("path") or "").replace("\\", "/")
        file = source[len(base):] if source.startswith(base) else source.rsplit("/", 1)[-1]
        for p in result.get("packages") or []:
            pkg, vulns = p.get("package") or {}, p.get("vulnerabilities") or []
            for g in p.get("groups") or []:
                ids = set(g.get("ids") or [])
                main = sorted(ids, key=lambda i: (not i.startswith("MAL-"), not i.startswith("GHSA-"), i))[0] if ids else "?"
                out.append({"id": main, "aliases": sorted(set(g.get("aliases") or []) - {main}), "file": file,
                            "ecosystem": pkg.get("ecosystem"), "package": pkg.get("name"), "version": pkg.get("version"),
                            "severity": _level(g, vulns, ids), "malware": any(i.startswith("MAL-") for i in ids),
                            "fixed": _fixed(vulns, ids, pkg.get("ecosystem"), pkg.get("name"), pkg.get("version") or ""),
                            "summary": next((v.get("summary") for v in vulns if v.get("id") in ids and v.get("summary")), "")})
    return out


def dev_only(root: Path) -> set[tuple[str, str]]:
    """(lockfile, package) pairs a lockfile marks as development-only: npm's "dev": true, pnpm's dev: true, and
    Pipfile.lock's develop section (when not also in default). Other formats don't say, so nothing is guessed."""
    out = set()
    for path in Path(root).rglob("*"):
        rel = path.relative_to(root).as_posix()
        try:
            if path.name in ("package-lock.json", "npm-shrinkwrap.json"):
                doc = json.loads(path.read_text(encoding="utf-8"))
                for key, meta in (doc.get("packages") or {}).items():
                    if key and isinstance(meta, dict) and meta.get("dev"):
                        out.add((rel, key.rsplit("node_modules/", 1)[-1].lower()))
            elif path.name == "Pipfile.lock":
                doc = json.loads(path.read_text(encoding="utf-8"))
                runtime = {k.lower() for k in doc.get("default") or {}}
                out |= {(rel, k.lower()) for k in doc.get("develop") or {} if k.lower() not in runtime}
            elif path.name == "pnpm-lock.yaml":
                import yaml
                doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                for key, meta in (doc.get("packages") or {}).items():
                    if isinstance(meta, dict) and meta.get("dev") is True:
                        name = str(key).lstrip("/")
                        out.add((rel, name.rsplit("@", 1)[0].lower() if not name.startswith("@") or name.count("@") > 1 else name.lower()))
        except (OSError, ValueError, AttributeError):
            continue
    return out


def scan(api, ref: str, binary: Path, offline: bool, blobs: list[dict] | None = None) -> dict:
    """Fetch the lockfiles at `ref` into a scratch folder, scan them, and return what was found."""
    blobs = lockfile_blobs(api, ref) if blobs is None else blobs
    if not blobs:
        return {"files": [], "skipped": [], "findings": [], "packages": []}
    with tempfile.TemporaryDirectory(prefix="stackvitals-osv-") as tmp:
        skipped = fetch(api, blobs, ref, Path(tmp))
        doc = run_scanner(binary, Path(tmp), offline, all_packages=True)
        dev = dev_only(Path(tmp))
        # A package only development uses (test tools, linters) is marked, so it can wait behind what ships.
        rows = [{**f, "file": _real(f["file"]), **({"dev": True} if (f["file"], str(f.get("package") or "").lower()) in dev else {})}
                for f in findings(doc, Path(tmp))]
        return {"files": [b["path"] for b in blobs if b["path"] not in skipped], "skipped": skipped,
                "findings": rows, "packages": [[_real(p[0]), *p[1:]] for p in packages_of(doc, Path(tmp))]}


def pr_diff(api, paths: list[tuple[str, str | None]], base: str, head: str, binary: Path, offline: bool,
            timeout: int = 600) -> dict:
    """Known vulnerabilities a pull request adds or removes in the lockfiles it changes: each lockfile is scanned at
    the base and head commits (a renamed one at its old path) and the advisories compared per package."""
    def found(ref: str, wanted: list[tuple[str, str]]) -> set:
        # wanted: (path at this commit, path at head), so a renamed file's rows line up.
        with tempfile.TemporaryDirectory(prefix="stackvitals-osv-") as tmp:
            names = {}
            for i, (at, as_head) in enumerate(wanted):
                try:
                    body = api.file(at, ref)
                except Exception as exc:  # noqa: BLE001 - a lockfile the PR adds has no base version
                    if "404" in str(exc):
                        continue
                    raise
                # One folder per file keeps two lockfiles of the same name apart.
                target = Path(tmp) / str(i) / Path(at).name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(body)
                names[f"{i}/{Path(at).name}"] = as_head
            if not names:
                return set(), set()
            doc = run_scanner(binary, Path(tmp), offline, timeout=timeout, all_packages=True)
            rows = findings(doc, Path(tmp))
            pkgs = {(eco, name, version) for _f, eco, name, version in packages_of(doc, Path(tmp))}
            return {(names.get(r["file"], r["file"]), r["ecosystem"], r["package"], r["id"], r["version"], r["severity"],
                     r["fixed"] or "", r["malware"]) for r in rows}, pkgs
    after, pkgs_after = found(head, [(p, p) for p, _old in paths])
    before, pkgs_before = found(base, [(old, p) for p, old in paths if old])
    key = lambda r: r[:4]  # noqa: E731 - the same advisory on the same package counts as already there
    had, has = {key(r) for r in before}, {key(r) for r in after}
    row = lambda r: {"file": r[0], "ecosystem": r[1], "package": r[2], "id": r[3], "version": r[4], "severity": r[5],  # noqa: E731
                     "fixed": r[6] or None, "malware": r[7]}
    order = lambda f: (not f["malware"], ["critical", "high", "moderate", "low", "unrated"].index(f["severity"]), f["package"])  # noqa: E731
    return {"added": sorted((row(r) for r in after if key(r) not in had), key=order),
            "removed": sorted((row(r) for r in before if key(r) not in has), key=order), "files": len(paths),
            # Package versions the PR brings in, for its licence check.
            "new_packages": sorted(pkgs_after - pkgs_before)[:200]}


# GitHub's ecosystem names, as OSV and the scanner write them.
GHSA_ECOSYSTEMS = {"npm": "npm", "pip": "PyPI", "rubygems": "RubyGems", "nuget": "NuGet", "maven": "Maven",
                   "composer": "Packagist", "go": "Go", "rust": "crates.io", "pub": "Pub", "swift": "SwiftURL",
                   "erlang": "Hex"}
MALWARE_PAGES = 5
CONDITION = re.compile(r"^\s*(>=|<=|>|<|=)\s*(\S+)\s*$")


def in_range(version: str, spec: str) -> bool:
    """GitHub's vulnerable_version_range: conditions joined by commas, all of which must hold (">= 0", "= 1.2.3")."""
    for part in str(spec or "").split(","):
        m = CONDITION.match(part)
        if not m:
            return False
        op, bound = m.groups()
        a, b = _key(version), _key(bound)
        if not {"=": a == b, ">=": a >= b, "<=": a <= b, ">": a > b, "<": a < b}[op]:
            return False
    return True


def malware_feed(api, since: str) -> list[dict]:
    """GitHub's malware advisories published since `since`, newest first: usually hours before OSV lists them."""
    params = {"type": "malware", "per_page": 100, "sort": "published", "direction": "desc", "published": f">={since[:10]}"}
    client = getattr(api, "client", None)
    if client is None:
        return [a for a in api._get("/advisories", params) if (a.get("published_at") or "") >= since]
    from stackvitals.ci.api import API, APIError
    # This endpoint pages by cursor (the Link header's next), not by page number; a worm can publish hundreds a day.
    out, url = [], f"{API}/advisories"
    for _ in range(MALWARE_PAGES):
        api.requests += 1
        resp = client.get(url, headers=api.headers, params=params)
        if resp.status_code >= 400:
            raise APIError(f"GET /advisories: HTTP {resp.status_code}")
        batch = resp.json()
        out += [a for a in batch if (a.get("published_at") or "") >= since]
        url = (resp.links.get("next") or {}).get("url")
        if not url or len(batch) < 100 or (batch[-1].get("published_at") or "") < since:
            break
        params = None  # the next link carries them
    return out


def malware_matches(advisories: list[dict], packages: list[list[str]], now: datetime) -> list[dict]:
    """Rows for every package of the repo that a GitHub malware advisory names, in the scanner's shape."""
    by_name = {}
    for file, eco, name, version in packages:
        by_name.setdefault((eco, name.lower()), []).append((file, name, version))
    rows = []
    for a in advisories:
        for v in a.get("vulnerabilities") or []:
            pkg = v.get("package") or {}
            eco = GHSA_ECOSYSTEMS.get(str(pkg.get("ecosystem") or "").lower())
            for file, name, version in by_name.get((eco, str(pkg.get("name") or "").lower()), []):
                if in_range(version, v.get("vulnerable_version_range")):
                    rows.append({"id": a["ghsa_id"], "aliases": [], "file": file, "ecosystem": eco, "package": name,
                                 "version": version, "severity": "critical", "malware": True, "fixed": None,
                                 "summary": (a.get("summary") or "Malicious package")[:200],
                                 "source": f"GitHub malware advisory, published {str(a.get('published_at'))[:16]}Z"})
    return rows


def packages_of(doc: dict, root: Path) -> list[list[str]]:
    # Every package the scanner read (with --all-packages), as [file, ecosystem, name, version].
    base = str(Path(root).resolve()).replace("\\", "/").rstrip("/") + "/"
    out = set()
    for result in doc.get("results") or []:
        source = str((result.get("source") or {}).get("path") or "").replace("\\", "/")
        file = source[len(base):] if source.startswith(base) else source.rsplit("/", 1)[-1]
        for p in result.get("packages") or []:
            pkg = p.get("package") or {}
            if pkg.get("name") and pkg.get("version"):
                out.add((file, pkg.get("ecosystem") or "", pkg["name"], pkg["version"]))
    return [list(x) for x in sorted(out)]


def ident(f: dict) -> str:
    return f"{f['file']}|{f['ecosystem']}|{f['package']}|{f['version']}|{f['id']}"


def merge(previous: list[dict], found: list[dict], now: datetime) -> tuple[list[dict], list[dict], list[dict]]:
    """Today's open findings with the day each was first seen, the new ones, and those gone since the last scan."""
    seen = {ident(f): f.get("first_seen") for f in previous}
    today = iso(now)[:10]
    current = [{**f, "first_seen": seen.get(ident(f)) or today} for f in found]
    new = [f for f in current if ident(f) not in seen]
    gone_ids = {ident(f) for f in current}
    gone = [{**f, "closed": today} for f in previous if ident(f) not in gone_ids]
    return current, new, gone


def digest(blobs: list[dict]) -> str:
    return hashlib.sha256("\n".join(f"{b['path']} {b['sha']}" for b in blobs).encode()).hexdigest()[:16]


def _same_package(rows: list[dict], previous: list[dict]) -> list[dict]:
    # GitHub's malware advisory and OSV's MAL- record name one bad version twice: keep one row, from its first sighting.
    first = {}
    for f in previous:
        if f.get("malware"):
            k = (f["file"], f["ecosystem"], f["package"].lower(), f["version"])
            first[k] = min(first.get(k, f["first_seen"]), f["first_seen"])
    out, seen = [], set()
    for f in sorted(rows, key=lambda f: not f.get("source")):
        k = (f["file"], f["ecosystem"], f["package"].lower(), f["version"])
        if f.get("malware") and k in seen:
            continue
        seen.add(k)
        out.append({**f, **({"first_seen": first[k]} if f.get("malware") and k in first else {})})
    return out


def ignores(toml_text: str | None, now: datetime) -> dict[str, dict]:
    """The advisories a repo's osv-scanner.toml ignores ([[IgnoredVulns]] id, ignoreUntil, reason), still in force today;
    the same file OSV-Scanner itself reads, so a team that uses it already gets the same answers here."""
    import tomllib
    try:
        doc = tomllib.loads(toml_text or "")
    except tomllib.TOMLDecodeError:
        return {}
    out = {}
    for item in doc.get("IgnoredVulns") or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        until = item.get("ignoreUntil")
        until = until.date().isoformat() if hasattr(until, "date") else str(until)[:10] if until else None
        if until and until < now.date().isoformat():
            continue
        out[str(item["id"])] = {"until": until, "reason": str(item.get("reason") or "")[:300]}
    return out


SARIF_LEVEL = {"critical": "error", "high": "error", "moderate": "warning", "low": "note", "unrated": "note"}
SARIF_SCORE = {"critical": "9.5", "high": "7.5", "moderate": "5.0", "low": "2.0", "unrated": "0.0"}


def sarif(findings: list[dict]) -> dict:
    """Open findings (ignored ones left out) as SARIF 2.1.0 for GitHub's Security tab: one rule per advisory, located in
    the lockfile, with the fixing version as the help."""
    live = [f for f in findings if not f.get("ignored")]
    rules = {f["id"]: {"id": f["id"], "shortDescription": {"text": f"{f.get('package')} {f.get('version')}: {f['id']}"},
                       "helpUri": f"https://osv.dev/vulnerability/{f['id']}",
                       "help": {"text": f"Upgrade {f.get('package')} to {f['fixed']}." if f.get("fixed") else "No fixed version yet."},
                       "properties": {"security-severity": "10.0" if f.get("malware") else SARIF_SCORE.get(f.get("severity") or "unrated", "0.0")}}
             for f in live}
    results = [{"ruleId": f["id"], "level": "error" if f.get("malware") else SARIF_LEVEL.get(f.get("severity") or "unrated", "note"),
                "message": {"text": f"{'Malware' if f.get('malware') else 'Known vulnerability'} in {f.get('package')} {f.get('version')} ({f.get('ecosystem')})"},
                "locations": [{"physicalLocation": {"artifactLocation": {"uri": f.get("file") or "."}}}]} for f in live]
    return {"version": "2.1.0", "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
            "runs": [{"tool": {"driver": {"name": "StackVitals (OSV-Scanner)", "rules": list(rules.values())}}, "results": results}]}


def apply_reach(findings: list[dict], reach: dict | None) -> None:
    """Puts govulncheck's verdict on each Go finding it covers (by the advisory's id or an alias): "called" with the
    call path, "imported" or only "required"; so the advisories your code really calls come first."""
    by_id = {}
    for r in (reach or {}).get("findings") or []:
        for i in [r["id"], *(r.get("aliases") or [])]:
            by_id[i] = r
    for f in findings:
        hit = next((by_id[i] for i in [f.get("id"), *(f.get("aliases") or [])] if i in by_id), None)
        if hit and f.get("ecosystem") == "Go":
            f["reach"] = {"level": hit["reach"], "path": hit.get("path") or []}


def apply_ignores(findings: list[dict], ignored: dict[str, dict]) -> None:
    """Marks findings the repo chose to ignore (by the advisory's id or any alias); they stay listed, with the reason."""
    for f in findings:
        hit = next((ignored[i] for i in [f.get("id"), *(f.get("aliases") or [])] if i in ignored), None)
        if hit:
            f["ignored"] = hit
        else:
            f.pop("ignored", None)


def _action_findings(api, ref: str, offline: bool, notes: list) -> list[dict]:
    """Known vulnerabilities in the GitHub Actions the workflows use by tag; nothing when outside lookups are off."""
    if offline:
        return []
    import httpx

    from stackvitals.deps import actions_vulns
    try:
        listing = api._get(f"/repos/{api.repo}/contents/.github/workflows", {"ref": ref}) or []
        files = {i["path"]: api.file(i["path"], ref).decode("utf-8", "replace") for i in listing
                 if isinstance(i, dict) and str(i.get("name", "")).endswith((".yml", ".yaml"))}
        with httpx.Client(timeout=30) as c:
            found, _pinned = actions_vulns.findings(actions_vulns.uses_in(files), lambda u, b: c.post(u, json=b).json(),
                                                    lambda u: c.get(u).json())
        return found
    except Exception as exc:  # noqa: BLE001 - the lockfile findings still count
        notes.append(f"Vulnerabilities: the workflows' actions weren't checked ({type(exc).__name__}).")
        return []


def vulns_step(ws, env: dict, now: datetime, make_api=None, scanner=None) -> dict | None:
    """Scan the default branch's lockfiles when they change, and every 6 hours for new advisories; on every run, check
    GitHub's newest malware advisories against every package the last scan read. Keep each finding's first-seen day,
    publish docs/vulns.json and name new ones in the job summary. Trouble is said, never fatal."""
    from stackvitals.core.config import parse
    from stackvitals.core.store import published, write_if_changed
    cfg = ws.cache.get("settings") or parse("")[0]
    path = ws.path / "deps" / "vulns.json"
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    if make_api is None:
        from stackvitals.ci.api import ActionsAPI as make_api
    api = make_api(env.get("STACKVITALS_TOKEN") or env.get("GITHUB_TOKEN"), ws.repo, max_requests=MAX_FILES + 20)
    offline = not cfg["deps"].get("outside_lookups", True)
    try:
        ref = api._get(f"/repos/{ws.repo}").get("default_branch") or "main"
        blobs = lockfile_blobs(api, ref)
        mark = digest(blobs)
        fresh = state.get("last") and state["last"] > iso(now - RESCAN)
        full = mark != state.get("digest") or not fresh or env.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
        result = scan(api, ref, scanner or ensure_scanner(tool_dir(env)), offline, blobs) if full else None
    except ScannerError as exc:
        ws.notes.append(f"Vulnerabilities: {exc}.")
        return {"error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - GitHub trouble mid-scan keeps the last result
        ws.notes.append(f"Vulnerabilities: not scanned this run ({type(exc).__name__}: {str(exc)[:120]}).")
        return {"error": str(exc)}
    packages = result["packages"] if result else state.get("packages") or []
    # The fast lane: malware GitHub published since the last full scan (an hour of overlap), matched by name and version.
    malware = []
    if packages:
        try:
            since = min(state.get("last") or iso(now - timedelta(days=3)), iso(now - timedelta(hours=1)))
            since = iso(datetime.fromisoformat(since.replace("Z", "+00:00")) - timedelta(hours=1))
            malware = malware_matches(malware_feed(api, since), packages, now)
        except Exception as exc:  # noqa: BLE001 - the scan's own results still count
            ws.notes.append(f"Vulnerabilities: GitHub's malware advisories weren't read ({type(exc).__name__}).")
    previous = state.get("open") or []
    if result is None:
        known = {ident(f) for f in previous}
        if not [m for m in malware if ident(m) not in known]:
            return None
        base = [{k: v for k, v in f.items() if k != "first_seen"} for f in previous]
    else:
        # A malware match from GitHub's feed stays open while the package is still in a lockfile, even after the
        # feed's window has moved past it and before OSV lists it.
        present = {(eco, name.lower(), version) for _file, eco, name, version in packages}
        held = [{k: v for k, v in f.items() if k != "first_seen"} for f in previous
                if f.get("malware") and str(f.get("source") or "").startswith("GitHub malware")
                and (f.get("ecosystem"), str(f.get("package") or "").lower(), f.get("version")) in present]
        base = result["findings"] + held + _action_findings(api, ref, offline, ws.notes)
    rows = _same_package(base + malware, previous)
    current, new, gone = merge(previous, rows, now)
    current = _same_package(current, previous)
    closed = (gone + (state.get("closed") or []))[:200]
    # Advisories the repo ignores in osv-scanner.toml stay listed, marked with their reason, until their date.
    try:
        toml_text = api.file("osv-scanner.toml", ref).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001 - no file (or no access) means nothing is ignored
        toml_text = None
    apply_ignores(current, ignores(toml_text, now))
    from stackvitals.deps.fixplan import plan
    for f in current:
        # The smallest upgrade that fixes it, how big a jump that is, and the command.
        if (fix := plan(f)):
            f["fix_plan"] = fix
    if env.get("STACKVITALS_GOVULNCHECK"):
        from stackvitals.deps.supply import _reachability
        # Go advisories say whether the code calls the vulnerable function (govulncheck run in the workflow).
        apply_reach(current, _reachability(env["STACKVITALS_GOVULNCHECK"]))
    new = [f for f in new if not f.get("ignored")]
    files = result["files"] if result else state.get("files") or []
    skipped = result["skipped"] if result else state.get("skipped") or []
    # Whether the repo's own code imports each npm, PyPI or crates.io package (the imports-json input, `stackvitals deps imports`).
    imports_doc = None
    if env.get("STACKVITALS_IMPORTS"):
        try:
            imports_doc = json.loads(Path(env["STACKVITALS_IMPORTS"]).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            ws.notes.append(f"Vulnerabilities: {env['STACKVITALS_IMPORTS']} couldn't be read; run `stackvitals deps imports --out` before StackVitals.")
    if isinstance(imports_doc, dict):
        from stackvitals.deps.imports import imported
        for f in current:
            f["imported"] = imported(imports_doc, f.get("ecosystem"), f.get("package") or "")
    out = {"generated": iso(now), "ref": ref, "scanner": f"OSV-Scanner {SCANNER}", "offline": offline,
           "files": files, "skipped": skipped, "open": current, "closed": closed}
    path.parent.mkdir(parents=True, exist_ok=True)
    keep = {"last": iso(now), "digest": mark} if result else {"last": state.get("last"), "digest": state.get("digest")}
    path.write_text(json.dumps({**out, **keep, "packages": packages}, indent=1, sort_keys=True) + "\n",
                    encoding="utf-8", newline="\n")
    docs = ws.path / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    write_if_changed(docs / "vulns.json", published(out))
    # The same findings for GitHub's Security tab (github/codeql-action/upload-sarif reads it from the data branch).
    write_if_changed(docs / "vulns.sarif", sarif(current))
    if new:
        worst = sorted(new, key=lambda f: (not f["malware"], ["critical", "high", "moderate", "low", "unrated"].index(f["severity"])))
        ws.notes.append(f"Vulnerabilities: {len(new)} new since the last scan, worst {worst[0]['package']} "
                        f"{worst[0]['version']} ({worst[0]['id']}, {'malware' if worst[0]['malware'] else worst[0]['severity']}"
                        f"{', fixed in ' + worst[0]['fixed'] if worst[0]['fixed'] else ''}).")
    return {"files": len(files), "open": len(current), "new": len(new), "closed": len(gone),
            "malware": sum(f["malware"] for f in current), "scanned": result is not None}
