"""Which packages a repo's own code imports, for Python, JavaScript/TypeScript and Rust, read in the team's checkout:

    stackvitals deps imports [path] --out imports.json      # in a workflow step before StackVitals (imports-json input)

It answers "does our code import the package an advisory names?", not "does our code call the vulnerable function":
an import is a cheap, honest signal for which advisories to look at first, and a package that isn't imported directly
may still run through another package. Tests, vendored code and build output are left out.
"""
import json
import os
import re
from pathlib import Path

SKIP = re.compile(r"(^|/)(node_modules|vendor|third_party|dist|build|target|\.git|\.venv|venv|site-packages|__pycache__|"
                  r"tests?|__tests__|fixtures?)(/|$)")
# `from x import y`, or everything after `import` on the line (`import a as b, c`).
PY = re.compile(r"^\s*(?:from\s+([A-Za-z_][\w.]*)\s+import|import\s+([^\n#;]+))", re.M)
# Rust: `use x::`, `use x;`, `extern crate x` and paths like `tokio::spawn` (2018 edition needs no `use`).
RS = re.compile(r"(?:\bextern\s+crate\s+([a-z_][a-z0-9_]*)|\buse\s+([a-z_][a-z0-9_]*)\s*(?:;|\bas\b)"
                r"|(?<![\w:])([a-z_][a-z0-9_]*)::)")
RS_OWN = {"std", "core", "alloc", "crate", "self", "super", "proc_macro"}
JS = re.compile(r"""(?:\bfrom\s*|\brequire\s*\(\s*|\bimport\s*\(\s*|^\s*import\s+)['"]([^'"]+)['"]""", re.M)
JS_FILES = (".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".mts", ".cts", ".vue", ".svelte", ".astro")
# Distributions whose import name differs from the package name (the common ones). A dotted name must match itself or
# what's under it; a package with a hyphen and no entry here can't be told apart, so it reads "can't tell".
PY_ALIASES = {"pyyaml": ("yaml",), "beautifulsoup4": ("bs4",), "pillow": ("PIL",), "scikit-learn": ("sklearn",),
              "scikit-image": ("skimage",), "python-dateutil": ("dateutil",), "opencv-python": ("cv2",),
              "opencv-python-headless": ("cv2",), "protobuf": ("google.protobuf",), "pyjwt": ("jwt",),
              "python-jose": ("jose",), "msgpack-python": ("msgpack",), "attrs": ("attr", "attrs"),
              "python-multipart": ("multipart",), "pycryptodome": ("Crypto",), "pycryptodomex": ("Cryptodome",),
              "google-cloud-storage": ("google.cloud.storage",), "typing-extensions": ("typing_extensions",),
              "psycopg2-binary": ("psycopg2",), "grpcio": ("grpc",), "grpcio-tools": ("grpc_tools",),
              "pyopenssl": ("OpenSSL",), "gitpython": ("git",), "mysqlclient": ("MySQLdb",), "pyserial": ("serial",),
              "pyzmq": ("zmq",), "python-magic": ("magic",), "websocket-client": ("websocket",),
              "python-slugify": ("slugify",), "pygithub": ("github",), "ruamel-yaml": ("ruamel.yaml",),
              "python-dotenv": ("dotenv",), "pymupdf": ("fitz",), "faiss-cpu": ("faiss",)}
MAX_FILES = 20000


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def scan(root: Path) -> dict:
    """{"pypi": [modules], "npm": [package names], "crates.io": [crate names]} imported by the repo's own source files."""
    py, js, rs, seen = set(), set(), set(), 0
    for dirpath, dirs, files in os.walk(root):
        rel = Path(dirpath).relative_to(root).as_posix()
        if rel != "." and SKIP.search(rel):
            dirs[:] = []
            continue
        for f in files:
            if seen >= MAX_FILES:
                break
            path = Path(dirpath) / f
            if f.endswith(".py"):
                seen += 1
                for a, b in PY.findall(path.read_text(encoding="utf-8", errors="replace")):
                    for part in ([a] if a else b.split(",")):
                        mod = (part.split() or [""])[0].strip("()")
                        if re.fullmatch(r"[A-Za-z_][\w.]*", mod):
                            py.add(mod)
            elif f.endswith(".rs"):
                seen += 1
                for found in RS.findall(path.read_text(encoding="utf-8", errors="replace")):
                    rs.add(next(x for x in found if x))
            elif f.endswith(JS_FILES) and not f.endswith(".d.ts"):
                seen += 1
                for spec in JS.findall(path.read_text(encoding="utf-8", errors="replace")):
                    if spec.startswith((".", "/")) or spec.startswith("node:"):
                        continue
                    parts = spec.split("/")
                    js.add("/".join(parts[:2]) if spec.startswith("@") else parts[0])
    return {"pypi": sorted(py), "npm": sorted(js), "crates.io": sorted(rs - RS_OWN), "files": seen}


def imported(doc: dict | None, ecosystem: str | None, package: str) -> bool | None:
    """True when the code imports the package, False when it doesn't, None when there's nothing to tell (no file read,
    an ecosystem this doesn't cover, or a Python package whose import name isn't known)."""
    if not isinstance(doc, dict):
        return None
    eco = (ecosystem or "").lower()
    if eco == "npm":
        return package in set(doc.get("npm") or [])
    if eco == "crates.io":
        return package.replace("-", "_") in set(doc.get("crates.io") or [])
    if eco == "pypi":
        mods = set(doc.get("pypi") or [])
        names = PY_ALIASES.get(_norm(package))
        if names:
            return any(n in mods or any(m.startswith(n + ".") for m in mods) for n in names)
        tops = {_norm(m.split(".")[0]) for m in mods}
        if _norm(package) in tops:
            return True
        # Only a plain name is safe to call not imported; "foo-bar" may be imported under any name.
        return False if re.fullmatch(r"[A-Za-z0-9_]+", package) else None
    return None


def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="stackvitals deps imports", description=__doc__.split("\n\n")[0])
    ap.add_argument("path", nargs="?", default=".")
    ap.add_argument("--out", help="write the JSON here (default: print it)")
    args = ap.parse_args(argv)
    doc = scan(Path(args.path))
    text = json.dumps(doc, indent=1)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"{len(doc['pypi'])} Python modules, {len(doc['npm'])} npm packages and {len(doc['crates.io'])} crates imported, from {doc['files']} files: {args.out}")
    else:
        print(text)
    return 0
