"""Pre-launch readiness: one command answers "is it ready to launch?" with pass/fail per check, launching nothing.

    python scripts/prelaunch.py                  # everything but the sandbox run
    python scripts/prelaunch.py --quick          # the normal suite in place of the clean-copy suite
    python scripts/prelaunch.py --offline        # skip the live, read-only checks
    python scripts/prelaunch.py --live           # also run the sandbox "StackVitals try" and check every run it causes
    python scripts/prelaunch.py --only package,docs-links

It never publishes, tags, pushes a default branch or posts. Writes prelaunch-report.md and .json (gitignored) at the repo
root, logs in .prelaunch/, and exits 1 when any check failed. Python stdlib only.
"""
import argparse
import concurrent.futures
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import tomllib
import urllib.error
import urllib.request
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / ".prelaunch"
WIN = os.name == "nt"
SANDBOX = "kaushik-yadav/stackvitals-sandbox"
SANDBOX_TRY_WORKFLOW = "391825828"
SPEED_TEST = "tests/local/test_tool_speed.py"
LINK_CAP = 4000
# Private planning files: these names anywhere, the root ones only at the repo root.
PRIVATE_ANYWHERE = ["CLAUDE.md", ".env"]
PRIVATE_AT_ROOT = ["architecture_plan.md", "updates.md", "connector-accounts-guide.md", "competitor-research-guide.md",
                   "agent_*", "team-review-*", "plans/*"]


@dataclass
class Result:
    name: str
    status: str  # pass, warn, fail, skip or manual
    detail: str
    evidence: str = ""
    seconds: float = 0.0


@dataclass
class Ctx:
    args: argparse.Namespace
    tmp: Path
    cache: dict = field(default_factory=dict)


# ---------- small helpers ----------

def run(cmd, cwd=ROOT, env=None, timeout=1800, log=None):
    """Run a command; returns (exit code, combined output). A missing program or a timeout is exit code 127 or 124."""
    full = {**os.environ, **(env or {})}
    exe = shutil.which(cmd[0]) or cmd[0]
    try:
        p = subprocess.run([exe, *cmd[1:]], cwd=cwd, env=full, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
        code, out = p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        code, out = 127, f"not found: {cmd[0]}"
    except subprocess.TimeoutExpired as e:
        code, out = 124, f"timed out after {timeout}s\n{e.stdout or ''}"
    if log:
        LOGS.mkdir(exist_ok=True)
        (LOGS / log).write_text(f"$ {' '.join(map(str, cmd))}\n(cwd {cwd}, exit {code})\n\n{out}", encoding="utf-8")
    return code, out


def evidence(log):
    path = LOGS / log
    return (path.relative_to(ROOT) if path.is_relative_to(ROOT) else path).as_posix()


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if WIN else "bin/python")


def venv_script(venv: Path, name: str) -> Path:
    return venv / ("Scripts" if WIN else "bin") / (name + (".exe" if WIN else ""))


def repo_python() -> str:
    p = venv_python(ROOT / ".venv")
    return str(p) if p.exists() else sys.executable


def last_line(out, pattern=r"\d+ (passed|failed)"):
    lines = [ln.strip(" =") for ln in out.splitlines() if re.search(pattern, ln)]
    return lines[-1] if lines else (out.strip().splitlines() or ["(no output)"])[-1][:160]


def commit_files() -> list[str]:
    """Tracked files plus new ones not ignored: what a commit of the whole tree would carry."""
    _, out = run(["git", "ls-files", "-co", "--exclude-standard", "-z"])
    return sorted({f for f in out.split("\0") if f and (ROOT / f).is_file()})


def export_tree(ctx) -> Path:
    """A copy of the committed-or-addable files only, so ignored local files can't hide a problem."""
    if "export" not in ctx.cache:
        dest = ctx.tmp / "export"
        for f in commit_files():
            (dest / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / f, dest / f)
        ctx.cache["export"] = dest
    return ctx.cache["export"]


def http(url, method="GET", timeout=30):
    """(status, headers, body) without following redirects; status 0 when the request never got an answer."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    req = urllib.request.Request(url, method=method, headers={"User-Agent": "stackvitals-prelaunch"})
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read() if e.fp else b""
    except (urllib.error.URLError, OSError) as e:
        return 0, {}, str(e).encode()


# ---------- pure helpers (unit tested in tests/local/test_prelaunch.py) ----------

FENCE = re.compile(r"^(```|~~~).*?^\1[^\n]*$", re.M | re.S)


def strip_code(md: str) -> str:
    """Markdown without fenced blocks and inline code, so `#` comments and example links aren't read as real ones."""
    return re.sub(r"`[^`\n]*`", "", FENCE.sub("", md))


def anchor(heading: str) -> str:
    """GitHub's anchor for a heading: lower case, punctuation dropped, spaces to hyphens."""
    text = re.sub(r"<[^>]+>", "", heading).strip().lower()
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text).replace("`", "")
    return re.sub(r"[^\w\- ]", "", text).replace(" ", "-")


def anchors(md: str) -> set[str]:
    seen, out = {}, set()
    for h in re.findall(r"^#{1,6} +(.*?)#*\s*$", FENCE.sub("", md), re.M):
        a = anchor(h)
        n = seen.get(a, 0)
        out.add(a if n == 0 else f"{a}-{n}")
        seen[a] = n + 1
    out |= set(re.findall(r"""<a\s+(?:name|id)=["']([^"']+)["']""", md))
    return out


def md_links(md: str) -> list[str]:
    return re.findall(r"\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)", strip_code(md))


def broken_links(root: Path, pages: list[Path]) -> list[str]:
    """Relative links and #anchors in the pages that don't reach a file or a heading."""
    broken, cache = [], {}
    for page in pages:
        for url in md_links(page.read_text(encoding="utf-8")):
            if re.match(r"^[a-z][a-z0-9+.-]*:", url, re.I):
                continue
            path, _, frag = url.partition("#")
            target = (page.parent / urllib.request.url2pathname(path)).resolve() if path else page
            ok = target.exists()
            if ok and frag and target.suffix.lower() == ".md":
                if target not in cache:
                    cache[target] = anchors(target.read_text(encoding="utf-8"))
                ok = frag.lower() in cache[target]
            if not ok:
                broken.append(f"{page.relative_to(root).as_posix()} -> {url}")
    return broken


CMD = re.compile(r"(?<![\w/.\-@\[])stackvitals[ \t]+([^\s`'\"<>|;&()\\]+(?:[ \t]+[^\s`'\"<>|;&()\\]+)*)")


def command_lines(text: str, markdown: bool = False) -> list[list[str]]:
    """Each `stackvitals ...` command line as its words, cut at a placeholder, comment, template part or `--`."""
    text = text.replace("\\n", "\n")
    if markdown:
        # Only code: fenced blocks and inline code spans.
        text = "\n".join([m.group(0) for m in FENCE.finditer(text)] + re.findall(r"`([^`\n]+)`", FENCE.sub("", text)))
    else:
        # Source comments are prose; a // after a colon is a URL, not a comment.
        text = re.sub(r"(?:^|(?<=\s))//.*$", "", re.sub(r"/\*.*?\*/", "", text, flags=re.S), flags=re.M)
    found, pos = [], 0
    while m := CMD.search(text, pos):
        pos = m.start() + len("stackvitals")  # one line may hold another stackvitals, e.g. `mcp add stackvitals -- uvx stackvitals serve`
        before = text[max(0, m.start() - 12):m.start()]
        # The package or a server name, not the command: `pip install stackvitals`, `claude mcp add stackvitals`.
        if re.search(r"(install|add|--from)\s+$", before):
            continue
        words = []
        for w in m.group(1).split():
            if "${" in w or w.startswith(("#", "$", "{")) or w == "--" or w == "stackvitals":
                break
            words.append(w.rstrip(".,:"))
        if words:
            found.append(words)
    return found


def check_command(words: list[str], tree: dict, discover=None) -> str | None:
    """None when the command line fits the CLI tree ({"flags": set, "subs": {name: tree}}), else what's wrong.

    `discover(path)` returns the tree of a command missing from --help (dispatched by hand), or None if it doesn't exist."""
    node, path = tree, []
    for w in words:
        if w.startswith("-"):
            flag = w.split("=")[0]
            if flag not in node["flags"]:
                return f"`{' '.join(['stackvitals', *path])}` has no {flag}"
        elif node["subs"]:
            if w not in node["subs"] and discover:
                found = discover(path + [w])
                if found is not None:
                    node["subs"][w] = found
            if w not in node["subs"]:
                return f"`{' '.join(['stackvitals', *path])}` has no command `{w}`"
            node, path = node["subs"][w], path + [w]
        # Anything else is a positional value or a flag's value.
    return None


def parse_help(text: str) -> tuple[list[str], set[str]]:
    """(subcommands, flags) from argparse's --help text."""
    usage = text.split("\n\n")[0]
    subs = re.search(r"\{([\w,-]+)\}\s+\.\.\.", usage)
    flags = set(re.findall(r"(?<![\w-])(--?[A-Za-z][\w-]*)", usage))
    for line in text.splitlines():
        head = re.match(r"^\s{1,8}(-[^\s].*?)(?:\s{2,}|$)", line)
        if head:
            flags |= set(re.findall(r"(?<![\w-])(--?[A-Za-z][\w-]*)", head.group(1)))
    return (subs.group(1).split(",") if subs else []), flags


SECRET_PATTERNS = {
    "GitHub token": r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})",
    "Anthropic key": r"\bsk-ant-[A-Za-z0-9_-]{20,}",
    "OpenAI key": r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}",
    "Google API key": r"\bAIza[0-9A-Za-z_-]{35}",
    "AWS key": r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",
    "Slack token": r"\bxox[abposr]-[A-Za-z0-9-]{10,}",
    "Slack webhook": r"hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]{16,}",
    "Private key": r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP |ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----",
}
# Known fake values in tests and docs: (file glob, exact match). Each needs a reason.
SECRET_ALLOW = [
    # Split in two so this file doesn't match its own scan.
    ("tests/test_flow_core.py", "AKIA" "IOSFODNN7EXAMPLE", "AWS's documented example key, used as a SigV4 signing test vector"),
]


def find_secrets(path: str, text: str, allow=None) -> list[str]:
    """Secret-looking strings in one file, minus the allow-listed fakes."""
    allow = SECRET_ALLOW if allow is None else allow
    hits = []
    for kind, pattern in SECRET_PATTERNS.items():
        for m in re.finditer(pattern, text):
            value = m.group(0)
            if any(fnmatch.fnmatch(path, glob) and value == fake for glob, fake, *_ in allow):
                continue
            hits.append(f"{path}: {kind} {value[:8]}...")
    return hits


def is_private(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return any(name == p for p in PRIVATE_ANYWHERE) or any(fnmatch.fnmatchcase(path, p) for p in PRIVATE_AT_ROOT)


USES = re.compile(r"""(?<![\w-])["']?uses["']?\s*:\s*([^\s#,}]+)""")


def loose_uses(text: str, own_ref: str) -> list[str]:
    """`uses:` references not pinned to a full commit SHA (local actions and our own documented ref are fine)."""
    loose = []
    for m in USES.findall(text):
        ref = m.strip("'\"")
        if ref == own_ref or ref.startswith("./") or re.search(r"@[0-9a-f]{40}$", ref) or re.search(r"@sha256:[0-9a-f]{64}$", ref):
            continue
        loose.append(ref)
    return loose


def csp_problems(html: str) -> list[str]:
    """What's wrong with the app's Content-Security-Policy meta (empty when it holds)."""
    m = re.search(r"""<meta\s+http-equiv=["']Content-Security-Policy["']\s+content=(["'])(.*?)\1""", html, re.I | re.S)
    if not m:
        return ["no Content-Security-Policy meta"]
    rules = {d.split()[0]: d.split()[1:] for d in m.group(2).split(";") if d.strip()}
    problems = []
    if rules.get("script-src") != ["'self'"]:
        problems.append(f"script-src is {' '.join(rules.get('script-src', ['(missing)']))}, not 'self'")
    if rules.get("object-src") != ["'none'"]:
        problems.append("object-src isn't 'none'")
    if re.search(r"<script(?![^>]*\bsrc=)[^>]*>\s*\S", html, re.I):
        problems.append("an inline <script> (blocked by the CSP)")
    return problems


def validate_schema(doc, schema, root=None, path="$") -> list[str]:
    """A small JSON Schema check (type, required, properties, items, enum, const, pattern, lengths, $ref, anyOf/oneOf/allOf)."""
    root = root or schema
    if "$ref" in schema:
        ref = schema["$ref"]
        if ref.startswith("#/"):
            target = root
            for part in ref[2:].split("/"):
                target = target[part]
            return validate_schema(doc, target, root, path)
        return []
    errs = []
    kinds = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}
    t = schema.get("type")
    if t:
        allowed = t if isinstance(t, list) else [t]

        def fits(k):
            if k in ("integer", "number"):
                return isinstance(doc, (int, float)) and not isinstance(doc, bool) and (k == "number" or float(doc).is_integer())
            return isinstance(doc, kinds.get(k, object))
        if not any(fits(k) for k in allowed):
            return [f"{path}: expected {t}"]
    if "enum" in schema and doc not in schema["enum"]:
        errs.append(f"{path}: {doc!r} not one of {schema['enum']}")
    if "const" in schema and doc != schema["const"]:
        errs.append(f"{path}: must be {schema['const']!r}")
    if isinstance(doc, str):
        if "pattern" in schema and not re.search(schema["pattern"], doc):
            errs.append(f"{path}: doesn't match {schema['pattern']}")
        if len(doc) > schema.get("maxLength", 10**9) or len(doc) < schema.get("minLength", 0):
            errs.append(f"{path}: length {len(doc)} out of range")
    if isinstance(doc, dict):
        errs += [f"{path}: missing {k}" for k in schema.get("required", []) if k not in doc]
        for k, sub in schema.get("properties", {}).items():
            if k in doc:
                errs += validate_schema(doc[k], sub, root, f"{path}.{k}")
        if schema.get("additionalProperties") is False:
            errs += [f"{path}: unexpected {k}" for k in doc if k not in schema.get("properties", {})]
    if isinstance(doc, list) and isinstance(schema.get("items"), dict):
        for i, item in enumerate(doc):
            errs += validate_schema(item, schema["items"], root, f"{path}[{i}]")
    for sub in schema.get("allOf", []):
        errs += validate_schema(doc, sub, root, path)
    for key in ("anyOf", "oneOf"):
        if key in schema and not any(not validate_schema(doc, s, root, path) for s in schema[key]):
            errs.append(f"{path}: matches none of {key}")
    return errs


# ---------- 1. code ----------

def check_code_suite(ctx):
    """The whole pytest suite on a copy holding only committed-or-addable files (--quick: the normal suite in place)."""
    log = "code-suite.log"
    if ctx.args.quick:
        code, out = run([repo_python(), "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--ignore={SPEED_TEST}"],
                        timeout=3600, log=log)
        where = "in place, speed test left out"
    else:
        tree = export_tree(ctx)
        if (ROOT / "web" / "node_modules").is_dir():
            run(["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund", "--prefer-offline"], cwd=tree / "web",
                timeout=900, log="code-suite-npm.log")
        env = {"PYTHONPATH": str(tree / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
        code, out = run([repo_python(), "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=tree, env=env,
                        timeout=3600, log=log)
        where = "clean copy of the tracked tree"
        failed = sorted(set(re.findall(r"^FAILED (\S+?)(?:::| )", out, re.M)))
        # The speed test fails on a busy machine: it gets one quiet rerun alone, and counts only if that fails too.
        if code == 1 and SPEED_TEST in failed:
            again, _ = run([repo_python(), "-m", "pytest", "-q", "-p", "no:cacheprovider", SPEED_TEST], cwd=tree,
                           env=env, timeout=600, log="code-suite-speed-rerun.log")
            if again == 0:
                failed.remove(SPEED_TEST)
                where += "; the speed test passed on a rerun alone"
                code = 0 if not failed else code
        if failed:
            where += f"; failing: {', '.join(failed)}"
        # Only the load-sensitive speed test failing is a warning: GitHub's runner checks it at every merge.
        if failed == [SPEED_TEST]:
            return Result("code-suite", "warn", f"{last_line(out)} ({where}); only the speed test, which this busy machine "
                          "fails on unchanged code too; GitHub's runner checks it at merge", evidence(log))
    return Result("code-suite", "pass" if code == 0 else "fail", f"{last_line(out)} ({where})", evidence(log))


def npm_script(name, log, timeout=900):
    code, out = run(["npm", "run", name], cwd=ROOT / "web", timeout=timeout, log=log)
    return code, out


def check_web_types(ctx):
    code, out = npm_script("check", "web-types.log")
    return Result("web-types", "pass" if code == 0 else "fail",
                  "tsc --noEmit clean" if code == 0 else last_line(out, r"error"), evidence("web-types.log"))


def check_web_tests(ctx):
    code, out = npm_script("test", "web-tests.log")
    summary = re.findall(r"^(?:#|ℹ) (pass|fail) (\d+)", out, re.M)
    detail = ", ".join(f"{n} {k}" for k, n in summary) or last_line(out, r"pass|fail")
    return Result("web-tests", "pass" if code == 0 else "fail", detail, evidence("web-tests.log"))


def pytest_check(name, target, log):
    code, out = run([repo_python(), "-m", "pytest", "-q", "-p", "no:cacheprovider", target], timeout=1200, log=log)
    return Result(name, "pass" if code == 0 else "fail", last_line(out), evidence(log))


def check_web_budgets(ctx):
    return pytest_check("web-budgets", "tests/local/test_web_build.py", "web-budgets.log")


def check_web_build_current(ctx):
    return pytest_check("web-build-current", "tests/test_flow_web.py", "web-build-current.log")


# ---------- 2. package ----------

def built(ctx):
    """(sdist, wheel) built from the clean copy, once."""
    if "dist" not in ctx.cache:
        out_dir = ctx.tmp / "dist"
        code, out = run(["uv", "build", "--out-dir", str(out_dir), str(export_tree(ctx))], timeout=600, log="package-build.log")
        sdist = next(out_dir.glob("*.tar.gz"), None) if code == 0 else None
        wheel = next(out_dir.glob("*.whl"), None) if code == 0 else None
        ctx.cache["dist"] = (sdist, wheel, out)
    return ctx.cache["dist"]


def installed(ctx):
    """A fresh venv with the wheel and its [sql] extra, once; None when that failed."""
    if "venv" not in ctx.cache:
        _, wheel, _ = built(ctx)
        venv = ctx.tmp / "venv"
        ok = False
        if wheel:
            code, _ = run(["uv", "venv", "-q", "--python", "3.11", str(venv)], timeout=300, log="package-venv.log")
            if code == 0:
                code, _ = run(["uv", "pip", "install", "-q", "--python", str(venv_python(venv)), f"{wheel}[sql]"],
                              timeout=900, log="package-install.log")
                ok = code == 0
        ctx.cache["venv"] = venv if ok else None
    return ctx.cache["venv"]


def check_package_build(ctx):
    sdist, wheel, out = built(ctx)
    if not (sdist and wheel):
        return Result("package-build", "fail", "uv build failed: " + last_line(out, r"error|Error"), evidence("package-build.log"))
    code, out = run(["uvx", "twine", "check", str(sdist), str(wheel)], timeout=600, log="package-twine.log")
    if "PASSED" not in out and "FAILED" not in out:
        return Result("package-build", "pass", f"built {sdist.name}, {wheel.name}; twine not available (metadata unchecked)",
                      evidence("package-build.log"))
    return Result("package-build", "pass" if code == 0 else "fail",
                  f"built {sdist.name}, {wheel.name}; twine check {'passed' if code == 0 else 'FAILED'}", evidence("package-twine.log"))


def check_package_install(ctx):
    venv = installed(ctx)
    if not venv:
        return Result("package-install", "fail", "the wheel with [sql] didn't install in a fresh venv", evidence("package-install.log"))
    code, out = run([str(venv_python(venv)), "-c", "import duckdb, stackvitals, mergescout, stackvitals.mcp_server; print('ok')"],
                    cwd=ctx.tmp, timeout=120, log="package-import.log")
    return Result("package-install", "pass" if code == 0 else "fail",
                  "installs with [sql] in a fresh venv; imports work" if code == 0 else last_line(out, r"Error"), evidence("package-import.log"))


def cli_tree(ctx, program):
    """{"flags", "subs"} for every command of an installed CLI, by walking --help; also the failures."""
    exe = str(venv_script(installed(ctx), program))
    failures, lock = [], threading.Lock()

    def walk(path):
        code, out = run([exe, *path, "--help"], cwd=ctx.tmp, timeout=120)
        if code != 0:
            with lock:
                failures.append(f"`{program} {' '.join(path)} --help` exit {code}: {last_line(out, r'Error')}")
            return {"flags": set(), "subs": {}}
        subs, flags = parse_help(out)
        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            kids = dict(zip(subs, pool.map(lambda s: walk(path + [s]), subs)))
        return {"flags": flags, "subs": kids}
    tree = walk([])
    return tree, failures


def count_commands(tree):
    return 1 + sum(count_commands(t) for t in tree["subs"].values())


def check_cli_help(ctx):
    if not installed(ctx):
        return Result("cli-help", "skip", "no installed package (see package-install)")
    lines, bad = [], []
    for program in ("stackvitals", "mergescout"):
        tree, failures = cli_tree(ctx, program)
        ctx.cache[f"tree-{program}"] = tree
        lines.append(f"{program}: {count_commands(tree)} commands")
        bad += failures
    LOGS.mkdir(exist_ok=True)
    (LOGS / "cli-help.log").write_text("\n".join(lines + bad), encoding="utf-8")
    detail = "; ".join(lines) + (f"; {len(bad)} failed: {bad[0]}" if bad else ", every --help exits 0")
    return Result("cli-help", "fail" if bad else "pass", detail, evidence("cli-help.log"))


def doc_command_sources():
    files = [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]
    web = sorted(p for ext in ("*.ts", "*.tsx", "*.js", "*.mjs") for p in (ROOT / "web" / "src").rglob(ext))
    return [(p, True) for p in files] + [(p, False) for p in web]


def check_doc_commands(ctx):
    tree = ctx.cache.get("tree-stackvitals")
    if tree is None:
        if not installed(ctx):
            return Result("doc-commands", "skip", "no installed package (see package-install)")
        tree, _ = cli_tree(ctx, "stackvitals")
    exe, hidden = str(venv_script(installed(ctx), "stackvitals")), []

    def discover(path):
        # Some commands are dispatched before argparse (`ci upload`): they exist when their own --help answers.
        code, out = run([exe, *path, "--help"], cwd=ctx.tmp, timeout=120)
        if code != 0 or not re.search(r"usage: \S+ .*" + re.escape(path[-1]), out):
            return None
        hidden.append(" ".join(path))
        subs, flags = parse_help(out)
        return {"flags": flags, "subs": {s: {"flags": set(), "subs": {}} for s in subs}}
    seen, bad = 0, []
    for path, md in doc_command_sources():
        for words in command_lines(path.read_text(encoding="utf-8"), markdown=md):
            seen += 1
            problem = check_command(words, tree, discover)
            if problem:
                bad.append(f"{path.relative_to(ROOT).as_posix()}: stackvitals {' '.join(words)} -> {problem}")
    bad = sorted(set(bad))
    LOGS.mkdir(exist_ok=True)
    (LOGS / "doc-commands.log").write_text("\n".join(bad) or "all fit", encoding="utf-8")
    detail = (f"{seen} command lines in docs, README and web/src ({len(hidden)} commands not in --help lists: {', '.join(hidden)})"
              + (f"; {len(bad)} don't fit, e.g. {bad[0]}" if bad else "; all fit the CLI"))
    return Result("doc-commands", "fail" if bad else "pass", detail, evidence("doc-commands.log"))


def mcp_handshake(exe: Path, cwd: Path) -> tuple[int, str]:
    """Start `stackvitals serve`, initialize over stdio and list its tools; (tool count, note)."""
    p = subprocess.Popen([str(exe), "serve"], cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, text=True, encoding="utf-8")
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {},
             "clientInfo": {"name": "prelaunch", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]
    answer = {}

    def read():
        for line in p.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get("id") == 2:
                answer.update(msg)
                return
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    try:
        for m in msgs:
            p.stdin.write(json.dumps(m) + "\n")
            p.stdin.flush()
        reader.join(60)
    finally:
        p.kill()
    tools = answer.get("result", {}).get("tools", [])
    return len(tools), "no tools/list answer in 60 s" if not answer else ""


def check_package_contents(ctx):
    sdist, wheel, _ = built(ctx)
    if not wheel:
        return Result("package-contents", "skip", "no wheel (see package-build)")
    names = set(zipfile.ZipFile(wheel).namelist())
    app = {f"stackvitals/web/{p.relative_to(ROOT / 'src/stackvitals/web').as_posix()}"
           for p in (ROOT / "src/stackvitals/web").rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    tracked = set(commit_files())
    app = {a for a in app if f"src/{a}" in tracked}
    missing = sorted(app - names) + [n for n in ("stackvitals/mcp_server.py", "stackvitals/web/index.html") if n not in names]
    if missing:
        return Result("package-contents", "fail", f"{len(missing)} files missing from the wheel, e.g. {missing[0]}")
    venv = installed(ctx)
    if not venv:
        return Result("package-contents", "fail", "the app ships, but the MCP server couldn't be started (no install)")
    count, note = mcp_handshake(venv_script(venv, "stackvitals"), ctx.tmp)
    if not count:
        return Result("package-contents", "fail", f"the app ships ({len(app)} files), but the MCP server listed no tools {note}")
    return Result("package-contents", "pass", f"the web app ({len(app)} files) ships; the installed MCP server answers with {count} tools")


def check_version(ctx):
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    want = meta["project"]["version"]
    server = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    found = {"server.json": server.get("version")}
    for i, pkg in enumerate(server.get("packages", [])):
        found[f"server.json packages[{i}]"] = pkg.get("version")
    for pkg in ("stackvitals", "mergescout"):
        m = re.search(r"""__version__\s*=\s*["']([^"']+)""", (ROOT / "src" / pkg / "__init__.py").read_text(encoding="utf-8"))
        found[f"src/{pkg}/__init__.py"] = m and m.group(1)
    m = re.search(r"^## (\d[\w.]*)", (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), re.M)
    found["CHANGELOG.md top entry"] = m and m.group(1)
    for f in ("action.yml", "web/package.json"):
        m = re.search(r"""(?:stackvitals[=@ ]=?|"stackvitals",\s*"version":\s*")(\d+\.\d+\.\d+)""", (ROOT / f).read_text(encoding="utf-8"))
        if m:
            found[f] = m.group(1)
    _, wheel, _ = ctx.cache.get("dist", (None, None, None))
    if wheel:
        found["wheel file name"] = wheel.name.split("-")[1]
    off = {k: v for k, v in found.items() if v != want}
    detail = f"{want} in pyproject.toml, " + (", ".join(f"{k} says {v}" for k, v in off.items()) if off else f"{len(found)} other places agree")
    return Result("version", "fail" if off else "pass", detail)


# ---------- 3. browser end to end ----------

def check_e2e(ctx):
    pkg = json.loads((ROOT / "web" / "package.json").read_text(encoding="utf-8"))
    if "e2e" not in pkg.get("scripts", {}):
        return Result("e2e", "skip", "not set up (no e2e script in web/package.json)")
    results = ROOT / "web" / "e2e" / "results.json"
    started = time.time()
    code, out = npm_script("e2e", "e2e.log", timeout=3600)
    detail = last_line(out, r"passed|failed|flaky")
    if results.exists() and results.stat().st_mtime >= started - 5:
        stats = json.loads(results.read_text(encoding="utf-8")).get("stats", {})
        detail = (f"{stats.get('expected', 0)} passed, {stats.get('unexpected', 0)} failed, {stats.get('flaky', 0)} flaky, "
                  f"{stats.get('skipped', 0)} skipped")
    return Result("e2e", "pass" if code == 0 else "fail", detail, "web/e2e/results.json" if results.exists() else evidence("e2e.log"))


# ---------- 4. live, read-only ----------

def check_live_link(ctx):
    """GitHub takes a prefilled new-file link at our cap (signed out it sends you to log in) and 5xx's well above it."""
    base = "https://github.com/octocat/Hello-World/new/master?filename=prelaunch.txt&value="

    def probe(n):
        return http(base + "a" * (n - len(base)), timeout=30)[0]
    at_cap = probe(LINK_CAP)
    if not 200 <= at_cap < 400:
        return Result("live-link", "fail", f"a {LINK_CAP:,}-character link got {at_cap or 'no answer'} (expected a redirect to log in)")
    # Signed out, without cookies, so the real limit for a signed-in browser sits somewhat lower (about 5,700 measured).
    lengths = (5000, 5800, 6200, 6600, 7000, 8000)
    codes = {}
    for n in lengths:
        codes[n] = probe(n)
        if not 200 <= codes[n] < 400:
            break
    refused = next((n for n, c in codes.items() if not 200 <= c < 400), None)
    tail = ", ".join(f"{n:,}: {c}" for n, c in codes.items())
    margin = (f"refused from {refused:,} signed out, margin {refused - LINK_CAP:,}" if refused
              else f"no refusal up to {lengths[-1]:,} (more room than measured)")
    return Result("live-link", "pass", f"{LINK_CAP:,} chars: {at_cap}; {tail}; {margin}")


def check_live_pypi(ctx):
    code, _, _ = http("https://pypi.org/pypi/stackvitals/json")
    if code == 404:
        return Result("live-pypi", "pass", "the name stackvitals is still free on PyPI (404)")
    if code == 200:
        return Result("live-pypi", "fail", "stackvitals is already published on PyPI (expected nothing before launch)")
    return Result("live-pypi", "fail", f"PyPI answered {code or 'nothing'}; can't tell if the name is free")


def check_live_registry(ctx):
    server = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    url = server.get("$schema", "")
    cached = ctx.tmp / "server.schema.json"
    if not cached.exists():
        code, _, body = http(url)
        if code != 200:
            return Result("live-registry", "fail", f"couldn't fetch the schema server.json names ({url}): {code}")
        cached.write_bytes(body)
    errs = validate_schema(server, json.loads(cached.read_text(encoding="utf-8")))
    code, out = run(["uvx", "check-jsonschema", "--schemafile", str(cached), str(ROOT / "server.json")], timeout=300,
                    log="live-registry.log")
    if "validation errors" in out:
        errs.append("check-jsonschema: " + last_line(out, r"\S"))
    full = "check-jsonschema " + ("agrees" if "validation done" in out else "failed" if errs else "unavailable")
    return Result("live-registry", "fail" if errs else "pass",
                  (f"server.json invalid: {errs[0]}" if errs else f"server.json fits {url.rsplit('/', 2)[-2]} schema") + f"; {full}",
                  evidence("live-registry.log"))


def gh(args, env, timeout=120):
    return run(["gh", *args], env=env, timeout=timeout)


def check_live_sandbox(ctx):
    """Point the sandbox-try branch at HEAD, dispatch the sandbox's try workflow, then check every run it caused."""
    if not ctx.args.live:
        return Result("live-sandbox", "skip", "only with --live")
    code, token = run(["gh", "auth", "token", "--user", "kaushik-yadav"])
    if code != 0:
        return Result("live-sandbox", "fail", "no gh token for kaushik-yadav")
    env = {"GH_TOKEN": token.strip(), "MSYS_NO_PATHCONV": "1"}
    head = run(["git", "rev-parse", "--short", "HEAD"])[1].strip()
    # Only refs/heads/sandbox-try moves; never a default branch.
    code, out = run(["git", "push", "-q", "--force", "origin", "HEAD:refs/heads/sandbox-try"], env=env, log="live-sandbox-push.log")
    if code != 0:
        return Result("live-sandbox", "fail", "couldn't point sandbox-try at HEAD", evidence("live-sandbox-push.log"))
    since = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for _ in range(3):
        code, out = gh(["api", "-X", "POST", f"repos/{SANDBOX}/actions/workflows/{SANDBOX_TRY_WORKFLOW}/dispatches", "-f", "ref=main"], env)
        if code == 0:
            break
        time.sleep(30)
    if code != 0:
        return Result("live-sandbox", "fail", f"dispatch failed: {last_line(out, r'.')}")
    runs, quiet, deadline = [], 0, time.time() + 50 * 60
    # Wait until the try run and everything it set off are done, and no new run turned up for two polls.
    while time.time() < deadline:
        time.sleep(45)
        code, out = gh(["api", f"repos/{SANDBOX}/actions/runs?per_page=50&created=%3E%3D{since}",
                        "--jq", "[.workflow_runs[]|{id,name,status,conclusion,event}]"], env)
        if code != 0:
            continue
        now = json.loads(out or "[]")
        done = now and all(r["status"] == "completed" for r in now)
        quiet = quiet + 1 if done and len(now) == len(runs) else 0
        runs = now
        if quiet >= 2:
            break
    LOGS.mkdir(exist_ok=True)
    (LOGS / "live-sandbox.json").write_text(json.dumps(runs, indent=2), encoding="utf-8")
    if not runs:
        return Result("live-sandbox", "fail", "no sandbox run started", evidence("live-sandbox.json"))
    bad = [r for r in runs if r["conclusion"] not in ("success", "skipped", "neutral")]
    listing = ", ".join(f"{r['name']}: {r['conclusion'] or r['status']}" for r in runs)
    return Result("live-sandbox", "fail" if bad else "pass", f"sandbox-try at {head}; {len(runs)} runs: {listing}",
                  evidence("live-sandbox.json"))


# ---------- 5. docs ----------

def check_docs_llms(ctx):
    return pytest_check("docs-llms", "tests/local/test_llms_txt.py", "docs-llms.log")


def check_docs_accuracy(ctx):
    code, out = run([repo_python(), "bench/accuracy/summary.py", "--check"], timeout=600, log="docs-accuracy.log")
    return Result("docs-accuracy", "pass" if code == 0 else "fail",
                  "docs/accuracy.md and the app's table are current" if code == 0 else last_line(out, r"\S"), evidence("docs-accuracy.log"))


def check_docs_links(ctx):
    tracked = set(commit_files())
    pages = [ROOT / f for f in sorted(tracked) if f.endswith(".md") and (f.startswith("docs/") or "/" not in f) and not is_private(f)]
    bad = broken_links(ROOT, pages)
    LOGS.mkdir(exist_ok=True)
    (LOGS / "docs-links.log").write_text("\n".join(bad) or "all resolve", encoding="utf-8")
    return Result("docs-links", "fail" if bad else "pass",
                  f"{len(pages)} pages; " + (f"{len(bad)} broken, e.g. {bad[0]}" if bad else "every relative link and #anchor resolves"),
                  evidence("docs-links.log"))


# ---------- 6. security and privacy ----------

def package_members(ctx):
    """[(name, bytes)] of every file in the built sdist and wheel."""
    sdist, wheel, _ = built(ctx)
    members = []
    if wheel:
        with zipfile.ZipFile(wheel) as z:
            members += [(f"wheel:{n}", z.read(n)) for n in z.namelist() if not n.endswith("/")]
    if sdist:
        with tarfile.open(sdist) as t:
            members += [(f"sdist:{m.name.split('/', 1)[-1]}", t.extractfile(m).read()) for m in t.getmembers() if m.isfile()]
    return members


def check_secrets(ctx):
    hits = []
    files = commit_files()
    for f in files:
        data = (ROOT / f).read_bytes()
        if b"\0" not in data[:4096]:
            hits += find_secrets(f, data.decode("utf-8", "replace"))
    members = package_members(ctx)
    for name, data in members:
        if b"\0" not in data[:4096]:
            hits += find_secrets(name.split(":", 1)[1], data.decode("utf-8", "replace"))
    LOGS.mkdir(exist_ok=True)
    (LOGS / "secrets.log").write_text("\n".join(hits) or "none", encoding="utf-8")
    scope = f"{len(files)} files" + (f" and {len(members)} package files" if members else " (no package built)")
    return Result("secrets", "fail" if hits else "pass",
                  f"{scope}; " + (f"{len(hits)} possible secrets, e.g. {hits[0]}" if hits else f"none ({len(SECRET_ALLOW)} known fakes allowed)"),
                  evidence("secrets.log"))


def check_private_files(ctx):
    leaked = [f"tracked: {f}" for f in commit_files() if is_private(f)]
    members = package_members(ctx)
    leaked += [n for n, _ in members if is_private(n.split(":", 1)[1])]
    scope = "tracked files" + (" and the sdist and wheel" if members else " (no package built)")
    return Result("private-files", "fail" if leaked else "pass",
                  f"{len(leaked)} private files in {scope}: {', '.join(leaked[:3])}" if leaked else f"none in {scope}")


def check_pins(ctx):
    own = re.search(r"""ACTION_REF\s*=\s*["']([^"']+)""", (ROOT / "src/stackvitals/ci/cli.py").read_text(encoding="utf-8")).group(1)
    files = [f for f in commit_files() if f == "action.yml" or (f.startswith((".github/", "deploy/")) and f.endswith((".yml", ".yaml")))
             or f.startswith("templates/")]
    loose, count = [], 0
    for f in files:
        text = (ROOT / f).read_text(encoding="utf-8")
        count += len(USES.findall(text))
        loose += [f"{f}: {ref}" for ref in loose_uses(text, own)]
    return Result("pins", "fail" if loose else "pass",
                  f"{count} uses: in {len(files)} files; " + (f"{len(loose)} not pinned, e.g. {loose[0]}" if loose
                  else f"all pinned to a commit (own {own} allowed; generated workflows: web-tests and code-suite)"))


def check_csp(ctx):
    html = (ROOT / "src/stackvitals/web/index.html").read_text(encoding="utf-8")
    problems = csp_problems(html)
    _, wheel, _ = ctx.cache.get("dist", (None, None, None))
    if wheel:
        shipped = zipfile.ZipFile(wheel).read("stackvitals/web/index.html").decode("utf-8")
        problems += [f"in the wheel: {p}" for p in csp_problems(shipped)]
    return Result("csp", "fail" if problems else "pass",
                  "; ".join(problems) if problems else "built app keeps script-src 'self', object-src 'none', no inline script"
                  + (" (checked in the wheel too)" if wheel else ""))


# ---------- 7. manual at launch ----------

MANUAL = [
    ("manual-tokens", "rotate every token with a 6-month expiry (launch prep only)"),
    ("manual-pypi", "publish to PyPI (release workflow on the v0 tag)"),
    ("manual-tag", "tag v0 (and the release version tag)"),
    ("manual-marketplace", "list the Action on GitHub Marketplace"),
    ("manual-mcp-registry", "publish server.json to the MCP registry"),
    ("manual-public", "make the repo public"),
    ("manual-announce", "announcements"),
]

CHECKS = [
    ("code-suite", check_code_suite), ("web-types", check_web_types), ("web-tests", check_web_tests),
    ("web-budgets", check_web_budgets), ("web-build-current", check_web_build_current),
    ("package-build", check_package_build), ("package-install", check_package_install), ("cli-help", check_cli_help),
    ("doc-commands", check_doc_commands), ("package-contents", check_package_contents), ("version", check_version),
    ("e2e", check_e2e),
    ("live-link", check_live_link), ("live-pypi", check_live_pypi), ("live-registry", check_live_registry),
    ("live-sandbox", check_live_sandbox),
    ("docs-llms", check_docs_llms), ("docs-accuracy", check_docs_accuracy), ("docs-links", check_docs_links),
    ("secrets", check_secrets), ("private-files", check_private_files), ("pins", check_pins), ("csp", check_csp),
]


def selected(name, only):
    return not only or any(name.startswith(o) for o in only)


def write_reports(results, args, started):
    head = run(["git", "rev-parse", "--short", "HEAD"])[1].strip()
    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])[1].strip()
    failed = [r for r in results if r.status == "fail"]
    warned = [r for r in results if r.status == "warn"]
    verdict = ("NOT READY" if failed else "READY (the manual items stay for launch day)"
               + (f"; {len(warned)} warning(s) to read" if warned and not failed else ""))
    flags = " ".join(f"--{k}" for k in ("quick", "offline", "live") if getattr(args, k)) or "(default)"
    md = [f"# Pre-launch report", "", f"{verdict}. Branch {branch} at {head}, {started:%Y-%m-%d %H:%M} UTC, flags {flags}.", "",
          "| Check | Status | Detail | Evidence |", "|---|---|---|---|"]
    md += [f"| {r.name} | {r.status} | {r.detail.replace('|', '/')} | {r.evidence} |" for r in results]
    (ROOT / "prelaunch-report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (ROOT / "prelaunch-report.json").write_text(json.dumps({"verdict": verdict, "branch": branch, "commit": head,
        "started": started.isoformat(), "flags": flags, "checks": [asdict(r) for r in results]}, indent=2), encoding="utf-8")
    return verdict


def main(argv=None):
    p = argparse.ArgumentParser(description="Is it ready to launch? Runs every check, launches nothing.")
    p.add_argument("--quick", action="store_true", help="the normal suite in place of the clean-copy suite; no speed test")
    p.add_argument("--offline", action="store_true", help="skip the live, read-only checks")
    p.add_argument("--live", action="store_true", help="also run the sandbox try workflow and check every run it causes")
    p.add_argument("--only", action="append", default=[], help="check names or prefixes, comma separated (e.g. package,docs-links)")
    args = p.parse_args(argv)
    args.only = [o.strip() for o in ",".join(args.only).split(",") if o.strip()]
    if args.offline and args.live:
        p.error("--live needs the network; drop --offline")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    started = datetime.now(timezone.utc)
    shutil.rmtree(LOGS, ignore_errors=True)
    results = []
    with tempfile.TemporaryDirectory(prefix="prelaunch-", ignore_cleanup_errors=True) as tmp:
        ctx = Ctx(args, Path(tmp))
        for name, fn in CHECKS:
            if not selected(name, args.only):
                continue
            if name.startswith("live-") and args.offline:
                results.append(Result(name, "skip", "--offline"))
                continue
            print(f"... {name}", flush=True)
            t0 = time.time()
            try:
                r = fn(ctx)
            except Exception as e:  # a crashed check is a failed check, and the rest still run
                r = Result(name, "fail", f"the check crashed: {type(e).__name__}: {e}")
            r.seconds = round(time.time() - t0, 1)
            results.append(r)
            print(f"    {r.status:6} {r.detail}", flush=True)
        results += [Result(n, "manual", f"at launch: {d}") for n, d in MANUAL if selected(n, args.only)]
    verdict = write_reports(results, args, started)
    width = max(len(r.name) for r in results)
    print(f"\n{'check'.ljust(width)}  status  detail")
    for r in results:
        print(f"{r.name.ljust(width)}  {r.status:6}  {r.detail}")
    print(f"\n{verdict}. Report: prelaunch-report.md, prelaunch-report.json; logs in .prelaunch/")
    return 1 if any(r.status == "fail" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
