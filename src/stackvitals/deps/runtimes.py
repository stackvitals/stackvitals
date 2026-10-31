"""The language runtimes a repo builds and runs on (Node.js, Python, PHP, Ruby, Go), read from its version files,
Dockerfiles and workflow setup steps, checked against endoflife.date: a release line out of support gets no security
fixes, and a pinned patch older than the newest one misses the fixes since. Runtime flaws (PHP's in October 2026) are
not package advisories, so lockfile scans never see them."""
import json
import re

EOL_API = "https://endoflife.date/api"
PRODUCTS = {"node": "nodejs", "python": "python", "php": "php", "ruby": "ruby", "go": "go", "debian": "debian", "ubuntu": "ubuntu",
            "alpine": "alpine-linux"}
FILES = re.compile(r"(^|/)(\.nvmrc|\.node-version|\.python-version|\.php-version|\.ruby-version|\.tool-versions|runtime\.txt"
                   r"|go\.mod|package\.json|composer\.json|Dockerfile[^/]*|\.github/workflows/[^/]+\.ya?ml)$")
SKIP = re.compile(r"(^|/)(node_modules|vendor|third_party|testdata|fixtures?|examples?)/")
MAX_FILES = 40
VERSION = r"v?(\d+(?:\.\d+){0,2})"
SETUP = {"node": re.compile(rf"node-version:\s*['\"]?{VERSION}"), "python": re.compile(rf"python-version:\s*['\"]?{VERSION}"),
         "php": re.compile(rf"php-version:\s*['\"]?{VERSION}"), "ruby": re.compile(rf"ruby-version:\s*['\"]?{VERSION}"),
         "go": re.compile(rf"go-version:\s*['\"]?{VERSION}")}
MATRIX_KEYS = {"php": "php", "php-version": "php", "php-versions": "php", "python": "python", "python-version": "python",
               "python-versions": "python", "node": "node", "node-version": "node", "node-versions": "node", "ruby": "ruby",
               "ruby-version": "ruby", "go": "go", "go-version": "go"}
MATRIX = re.compile(r"(?mi)^\s*(" + "|".join(re.escape(k) for k in MATRIX_KEYS) + r")\s*:\s*(?:\[([^\]\n]*)\]|\n((?:[ \t]*-[ \t]*['\"]?[\d.]+['\"]?[ \t]*\n)+))")
IMAGE = re.compile(rf"(?mi)^\s*FROM\s+(?:[\w./-]+/)?(node|python|php|ruby|golang)[:@]{VERSION}")
# Base operating system images, by version or codename (endoflife.date's debian, ubuntu and alpine).
DEBIAN = {"stretch": "9", "buster": "10", "bullseye": "11", "bookworm": "12", "trixie": "13"}
UBUNTU = {"bionic": "18.04", "focal": "20.04", "jammy": "22.04", "noble": "24.04", "oracular": "24.10", "plucky": "25.04"}
CODENAMES = {**DEBIAN, **UBUNTU}
OS_IMAGE = re.compile(r"(?mi)^\s*FROM\s+(?:--platform=\S+\s+)?(?:[\w./-]+/)?(debian|ubuntu|alpine)[:]([\w.]+)")
SUFFIX = re.compile(r"(?mi)^\s*FROM\s+(?:--platform=\S+\s+)?(?:[\w./-]+/)?(?:node|python|php|ruby|golang)[:][\w.]*?-(?:slim-)?("
                    + "|".join(CODENAMES) + r")\b")


def wanted(path: str) -> bool:
    return bool(FILES.search(path)) and not SKIP.search(path)


def detect(files: dict[str, str]) -> list[dict]:
    """Every runtime version a repo names, with where: [{"runtime", "version", "file"}]; versions that aren't a number
    ("lts/*", ">=18") are left out rather than guessed."""
    found = []

    def add(runtime, version, file, use="runs"):
        # "runs": what the project runs on; "tests": a test matrix, where old lines are often kept on purpose.
        if version and re.fullmatch(r"\d+(\.\d+){0,2}", version):
            found.append({"runtime": runtime, "version": version, "file": file, "use": use})
    for path, text in files.items():
        name = path.rsplit("/", 1)[-1]
        first = text.strip().splitlines()[0].strip() if text.strip() else ""
        if name in (".nvmrc", ".node-version"):
            add("node", first.lstrip("v"), path)
        elif name == ".python-version":
            add("python", first, path)
        elif name == ".php-version":
            add("php", first, path)
        elif name == ".ruby-version":
            add("ruby", first.removeprefix("ruby-"), path)
        elif name == "runtime.txt":
            m = re.match(rf"(python|php|ruby)-{VERSION}", first)
            if m:
                add(m.group(1), m.group(2), path)
        elif name == ".tool-versions":
            for line in text.splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[0] in ("nodejs", "python", "php", "ruby", "golang"):
                    add({"nodejs": "node", "golang": "go"}.get(parts[0], parts[0]), parts[1], path)
        elif name == "go.mod":
            m = re.search(r"(?m)^go\s+(\d+\.\d+(?:\.\d+)?)", text)
            if m:
                add("go", m.group(1), path)
        elif name.startswith("Dockerfile"):
            for runtime, version in IMAGE.findall(text):
                add({"golang": "go"}.get(runtime.lower(), runtime.lower()), version, path)
            # The operating system under the image: debian:bookworm, ubuntu:22.04, alpine:3.18, or a language image's
            # suffix (python:3.11-slim-bookworm). An end-of-life base gets no security fixes for its packages.
            for os_name, tag in OS_IMAGE.findall(text):
                version = CODENAMES.get(tag.split("-")[0].lower(), tag.split("-")[0])
                add(os_name.lower(), version, path)
            for codename in SUFFIX.findall(text):
                add("debian" if codename.lower() in DEBIAN else "ubuntu", CODENAMES[codename.lower()], path)
        elif path.startswith(".github/workflows/"):
            for runtime, pattern in SETUP.items():
                for version in pattern.findall(text):
                    add(runtime, version, path)
            # A matrix names the versions: "php: [8.2, 8.3]" or a "- '3.12'" list under "python:".
            for key, inline, block in MATRIX.findall(text):
                runtime = MATRIX_KEYS[key.lower()]
                for version in re.findall(r"['\"]?(\d+(?:\.\d+){0,2})['\"]?", inline or block):
                    add(runtime, version, path, "tests")
        elif name == "package.json":
            try:
                engine = str(((json.loads(text) or {}).get("engines") or {}).get("node") or "")
            except ValueError:
                engine = ""
            m = re.fullmatch(rf"\s*[\^~]?{VERSION}(\.x)?\s*", engine)
            if m:
                add("node", m.group(1), path)
    seen, out = set(), []
    for f in found:
        k = (f["runtime"], f["version"], f["file"], f["use"])
        if k not in seen:
            seen.add(k)
            out.append(f)
    return out


def _cycle(product: str, version: str, cycles: list[dict]) -> dict | None:
    # The release line a version belongs to: "8.3" for PHP 8.3.4, "20" for Node 20.11, "3.11" for Python 3.11.2.
    parts = version.split(".")
    for n in (2, 1):
        name = ".".join(parts[:n])
        hit = next((c for c in cycles if str(c.get("cycle")) == name), None)
        if hit:
            return hit
    return None


def judge(found: list[dict], cycles: dict[str, list[dict]], today: str) -> list[dict]:
    """For each runtime version found: its release line, whether that line is out of support (and since when), and
    the newest patch when the repo pins an older one."""
    out = []
    for f in found:
        product = PRODUCTS[f["runtime"]]
        c = _cycle(product, f["version"], cycles.get(product) or [])
        if not c:
            out.append({**f, "status": "unknown"})
            continue
        eol = c.get("eol")
        ended = eol is True or (isinstance(eol, str) and eol <= today)
        latest = str(c.get("latest") or "")
        pinned = f["version"].count(".") >= 2  # a full version; "8.3" or "20" installs the newest patch
        behind = pinned and latest and _key(f["version"]) < _key(latest)
        out.append({**f, "cycle": str(c.get("cycle")), "eol": eol if isinstance(eol, str) else None, "latest": latest or None,
                    "latest_date": c.get("latestReleaseDate"),
                    "status": "end of life" if ended else "behind the newest patch" if behind else "supported"})
    return out


def _key(version: str) -> list:
    return [int(p) if p.isdigit() else 0 for p in version.split(".")]


def runtimes(api, ref: str, client) -> list[dict]:
    """Read the files that name runtimes at `ref` (one tree read, at most 40 files) and judge each version."""
    tree = api._get(f"/repos/{api.repo}/git/trees/{ref}", {"recursive": "1"})
    paths = [t["path"] for t in tree.get("tree") or [] if t.get("type") == "blob" and wanted(t["path"])][:MAX_FILES]
    files = {}
    for p in paths:
        try:
            files[p] = api.file(p, ref).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 - one unreadable file is skipped
            continue
    found = detect(files)
    cycles = {}
    for product in sorted({PRODUCTS[f["runtime"]] for f in found}):
        try:
            r = client.get(f"{EOL_API}/{product}.json")
            cycles[product] = r.json() if r.status_code == 200 else []
        except Exception:  # noqa: BLE001
            cycles[product] = []
    from datetime import date
    return judge(found, cycles, date.today().isoformat())
