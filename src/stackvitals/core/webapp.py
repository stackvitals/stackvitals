"""The StackVitals app, one static page over every module, copied beside the pages at the end of every job: index.html is
the app (built from web/ into the package's web/index.html and web/app/; the CI page is ci.html), each file is written
only when it changed, so a quiet run commits nothing, and app files the package no longer carries are removed."""
import hashlib
import re
from importlib import resources
from pathlib import Path

APP_DIR = "app"
TEXT = (".js", ".mjs", ".css", ".html", ".md", ".json", ".txt", ".svg")
# Relative module imports in the app's scripts (static, side-effect and dynamic), and the page's links to its scripts and styles.
IMPORTS = re.compile(rb"""(\bfrom\s*["']|\bimport\s*\(?\s*["'])(\.{1,2}/[^"'?]+\.m?js)(?=["'])""")
LINKS = re.compile(rb"""((?:href|src)=")((?:app|site)/[^"?]+\.(?:m?js|css))(?=")""")
WEB = resources.files("stackvitals") / "web"
# The project site (landing page and forwards to the app) lives beside the app in the package but never goes to a repo's Pages.
SITE_SOURCE = Path(str(WEB / "site"))


def _walk(node, prefix: str, out: dict, skip=()) -> dict:
    for child in node.iterdir():
        if child.name.startswith((".", "__")) or child.name in skip:
            continue
        if child.is_dir():
            _walk(child, f"{prefix}{child.name}/", out)
        else:
            out[prefix + child.name] = child.read_bytes()
    return out


def files() -> dict[str, bytes]:
    """The app's files from the package, by their path under docs/."""
    return _walk(WEB, "", {}, skip=("site",))


def site_files() -> dict[str, bytes]:
    """The project site's own files: its pages at the root, its styles under site/."""
    return {(name if name.endswith(".html") else f"site/{name}"): data for name, data in _walk(WEB / "site", "", {}).items()}


def stamped(app: dict[str, bytes]) -> dict[str, bytes]:
    """Every app URL gets `?v=` + a hash of all the files, so a browser never mixes a cached release with a new one."""
    # Text files lose a Windows checkout's CRLF; fonts and other binaries are kept byte for byte.
    norm = {k: v.replace(b"\r\n", b"\n") if k.endswith(TEXT) else v for k, v in app.items()}
    digest = hashlib.sha256(b"".join(k.encode() + b"\0" + norm[k] + b"\0" for k in sorted(norm))).hexdigest()[:10]
    tag = rb"\1\2?v=" + digest.encode()
    out = {}
    for name, data in norm.items():
        if name.endswith((".js", ".mjs")):
            data = IMPORTS.sub(tag, data)
        elif name.endswith(".html"):
            data = LINKS.sub(tag, data)
        out[name] = data
    return out


def write_webapp(docs: Path) -> list[str]:
    """Copy the app into docs/ and return the paths that changed."""
    docs = Path(docs)
    wanted = stamped(files())
    changed = []
    same = lambda a, b: a.replace(b"\r\n", b"\n") == b.replace(b"\r\n", b"\n")  # a Windows checkout turns LF into CRLF
    for rel, data in sorted(wanted.items()):
        target = docs / rel
        if target.is_file() and same(target.read_bytes(), data):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        changed.append(rel)
    app = docs / APP_DIR
    if app.is_dir():
        # The earlier app's files (views/, vendor/, old fonts) go too, so an upgraded site carries only this release.
        for path in sorted(app.rglob("*"), reverse=True):
            rel = path.relative_to(docs).as_posix()
            if path.is_file() and rel not in wanted:
                path.unlink()
                changed.append(rel)
            elif path.is_dir() and not any(path.iterdir()):
                path.rmdir()
    return changed
