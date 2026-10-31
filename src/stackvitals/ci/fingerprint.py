"""Failure fingerprints in Sentry's order (stack first, message only without one): the root cause's exception type and
its innermost in-app frames, where in-app means not the language, the test framework or installed packages. Works on
the text test reports carry for Java/Kotlin, Python (pytest and plain tracebacks), JavaScript/TypeScript (Jest, Vitest),
Go, Rust and C#."""
import hashlib
import re
from dataclasses import dataclass, field

CAUSE_FRAMES = 2
ANSI = re.compile(r"(?:\x1b|#x1B)\[[0-9;]*[A-Za-z]")
TYPE_LINE = re.compile(r"^(?:E\s+)?([A-Za-z_][\w.$]*(?:Error|Exception|Exit|Interrupt|Warning|Failure|Failed|Fault|"
                       r"Iteration|Timeout))(?:\s*:\s?(.*))?$")
# Java/Kotlin/C# frames: "at pkg.Class.method(...)"; a module prefix ("java.base/", "org.junit...@5.1/") is dropped.
AT_FRAME = re.compile(r"^\s*at ((?:[\w.$-]+(?:@[\w.\-]+)?/)?[\w.$<>`+\[\],-]+?)\((.*)$")
JS_FRAME = re.compile(r"^\s*at (?:(.+?) \()?((?:[A-Za-z]:)?[^\s()]+?):(\d+):(\d+)\)?\s*$")
VITEST_FRAME = re.compile(r"^\s*\u276f (?:\S+ )?(\S+?):(\d+):(\d+)\s*$")
PYTEST_FRAME = re.compile(r"^(\S[^\n]*?\.py):(\d+): ?(?:in (\S+)|\w[\w.]*)?\s*$")
PY_FRAME = re.compile(r'^\s*File "([^"]+)", line \d+, in (\S+)')
GO_TEST = re.compile(r"^\s+([\w.\-]+\.go):\d+: (.*)$")
GO_PATH = re.compile(r"^\t(\S+\.go):\d+")
RUST_PANIC = re.compile(r"^thread '([^']*)' panicked at (?:'(.*)', )?([^\s:]+\.rs):\d+:\d+:?\s*$")
NOT_APP_DOTTED = ("java.", "javax.", "jdk.", "sun.", "com.sun.", "kotlin.", "kotlinx.", "scala.", "org.junit.", "junit.",
                  "org.opentest4j.", "org.testng.", "org.assertj.", "org.hamcrest.", "org.mockito.", "org.apache.maven.",
                  "org.gradle.", "worker.org.gradle.", "System.", "Microsoft.", "Xunit.", "NUnit.", "Moq.")
NOT_APP_PATH = ("site-packages", "dist-packages", "/lib/python", "hostedtoolcache", "_pytest/", "pluggy/", "<frozen",
                "importlib/", "unittest/", "asyncio/", "node_modules", "node:", "internal/", "/src/runtime/",
                "/src/testing/", "/usr/local/go/", "/rustc/", "/.cargo/registry/")


def normalise(text: str | None) -> str:
    """The first line of a message without what changes between runs: escapes, ids, addresses, paths, times, numbers."""
    t = ANSI.sub("", text or "")
    t = next((line for line in t.splitlines() if line.strip()), "")
    t = re.sub(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b", "#", t)
    t = re.sub(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?", "#", t)
    t = re.sub(r"0x[0-9a-fA-F]+", "#", t)
    t = re.sub(r"(?:[A-Za-z]:)?(?:[\\/][\w.\-@+~]+){2,}[\\/]?", "#", t)
    t = re.sub(r"\b[0-9a-f]{12,}\b", "#", t)
    t = re.sub(r"\d+(?:\.\d+)?(?:ms|us|ns|s|m|h)?\b", "#", t)
    return re.sub(r"\s+", " ", t).strip()[:300]


# Where CI systems check code out: GitHub Actions (Linux, Windows), GitLab, Jenkins, CircleCI, Buildkite.
CHECKOUTS = (r"^.*?/work/[^/]+/[^/]+/", r"^[A-Za-z]:/a/[^/]+/[^/]+/", r"^/builds/[^/]+/[^/]+/", r"^.*/workspace/[^/]+/",
             r"^/home/circleci/[^/]+/", r"^.*/buildkite-agent/builds/[^/]+/[^/]+/[^/]+/")


def _rel(path: str) -> str:
    # Runner checkouts (/home/runner/work/repo/repo/, D:\a\repo\repo\) are dropped, so paths match across machines.
    p = path.replace("\\", "/")
    for checkout in CHECKOUTS:
        p, n = re.subn(checkout, "", p, count=1)
        if n:
            break
    return p.lstrip("./") if p.startswith("./") else p


def _app_dotted(name: str) -> bool:
    return not name.startswith(NOT_APP_DOTTED)


def _app_path(path: str) -> bool:
    p = path.replace("\\", "/")
    return not any(x in p for x in NOT_APP_PATH)


def _dotted(name: str) -> str:
    name = name.rsplit("/", 1)[-1] if "/" in name else name
    return re.sub(r"\$\d+", "$#", name)


@dataclass
class Failure:
    type: str
    message: str
    frames: list[str] = field(default_factory=list)  # in-app frames, innermost first

    @property
    def norm(self) -> str:
        return normalise(self.message)

    @property
    def where(self) -> str:
        return self.frames[0] if self.frames else ""

    @property
    def cause(self) -> str:
        """The same failure across tests and runs: type and innermost in-app frames, else type and message."""
        basis = "|".join(self.frames[:CAUSE_FRAMES]) if self.frames else self.norm
        return hashlib.sha1(f"{self.type}|{basis}".encode("utf-8")).hexdigest()[:12]

    def key(self, test_id: str) -> str:
        """The same failure of one test: its id, type, innermost frame and message."""
        return hashlib.sha1(f"{test_id}|{self.type}|{self.where}|{self.norm}".encode("utf-8")).hexdigest()[:12]


def _type_of(line: str) -> tuple[str, str] | None:
    line = next((x for x in (line or "").splitlines() if x.strip()), "").strip()
    m = TYPE_LINE.match(line)
    if m:
        return m[1], (m[2] or "").strip()
    # NUnit and xUnit print "System.Thing : message".
    m = re.match(r"^([\w.$]+)\s+:\s+(.*)$", line)
    if m and "." in m[1]:
        return m[1], m[2]
    return None


def _at_frames(lines: list[str]) -> list[str]:
    out = []
    for line in lines:
        js = JS_FRAME.match(line)
        if js and (" (" in line or re.search(r":\d+:\d+\)?\s*$", line)):
            if _app_path(js[2]):
                out.append(f"{_rel(js[2])}:{js[1]}" if js[1] else _rel(js[2]))
            continue
        m = AT_FRAME.match(line)
        if m:
            name = _dotted(m[1])
            if _app_dotted(name) and _app_path(m[2]):
                out.append(name)
    return out


def _java(text: str) -> Failure | None:
    lines = text.splitlines()
    if not any(AT_FRAME.match(x) or JS_FRAME.match(x) for x in lines):
        return None
    heads = [i for i, x in enumerate(lines) if x.lstrip().startswith("Caused by:")]
    first = _type_of(next((x for x in lines if x.strip()), ""))
    main = _at_frames(lines[1:heads[0]] if heads else lines[1:])
    if heads:
        start = heads[-1]
        root = _type_of(lines[start].split("Caused by:", 1)[1])
        frames = _at_frames(lines[start + 1:]) or main
        if root:
            return Failure(root[0], root[1], frames)
    return Failure(first[0] if first else "", first[1] if first else "", main)


def _python(text: str) -> Failure | None:
    lines = text.splitlines()
    found, last_def = [], None
    for line in lines:
        d = re.match(r"^\s*(?:async )?def (\w+)\(", line)
        if d:
            last_def = d[1]
        m = PY_FRAME.match(line)
        if m:
            found.append((m[1], None, m[2]))
            continue
        m = PYTEST_FRAME.match(line)
        if m:
            # pytest names a frame's function only for outer frames; the innermost one is the source shown above it.
            found.append((m[1], m[2], m[3] or last_def))
            last_def = None
    # The closing "path:line: Error" line repeats the innermost frame when pytest printed it already.
    dedup = []
    for path, line_no, func in found:
        if dedup and line_no and dedup[-1][0] == path and dedup[-1][1] == line_no:
            dedup[-1] = (path, line_no, dedup[-1][2] or func)
            continue
        dedup.append((path, line_no, func))
    frames = [f"{_rel(path)}:{func}" if func else _rel(path) for path, _, func in dedup if _app_path(path)]
    if not frames:
        return None
    found = next((t for x in reversed(lines) if (t := _type_of(x))), None)
    return Failure(found[0] if found else "", found[1] if found else "", list(reversed(frames)))


def _go(text: str) -> Failure | None:
    lines = text.splitlines()
    panic = next((x for x in lines if x.startswith("panic: ")), None)
    if panic:
        frames = []
        for i, line in enumerate(lines[:-1]):
            p = GO_PATH.match(lines[i + 1])
            if p and line and not line.startswith("\t") and "(" in line:
                if _app_path(p[1]):
                    frames.append(line[:line.rindex("(")])
        return Failure("panic", panic[len("panic: "):].replace(" [recovered]", ""), frames)
    hits = [GO_TEST.match(x) for x in lines]
    hits = [h for h in hits if h]
    if hits:
        return Failure("fail", hits[0][2], [hits[0][1]])
    return None


def _rust(text: str) -> Failure | None:
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = RUST_PANIC.match(line.strip())
        if m:
            message = m[2] or next((x for x in lines[i + 1:] if x.strip()), "")
            return Failure("panic", message, [m[3]] if _app_path(m[3]) else [])
    return None


def _vitest(text: str) -> list[str]:
    return [_rel(m[1]) for x in text.splitlines() if (m := VITEST_FRAME.match(x)) and _app_path(m[1])]


def analyse(type_attr: str | None, message: str | None, text: str | None) -> Failure:
    """Type, message and in-app frames of one failure from a report's type attribute, message and body."""
    text = ANSI.sub("", text or "").replace("\r\n", "\n")
    message = ANSI.sub("", message or "")
    declared = (type_attr or "").strip().splitlines()[0].strip() if (type_attr or "").strip() else ""
    found = _rust(text) or _go(text) or _java(text) or _python(text)
    if found is None:
        frames = _vitest(text)
        head = _type_of(message) or next((t for x in text.splitlines()[:5] if (t := _type_of(x))), None)
        found = Failure(head[0] if head else "", head[1] if head else (message or text), frames)
    # The report's own type and message fill what the body did not say.
    if not found.type:
        head = _type_of(message)
        found.type = head[0] if head else declared
    if not found.message:
        head = _type_of(message)
        found.message = head[1] if head else message
    return found
