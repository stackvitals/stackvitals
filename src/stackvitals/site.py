"""The project site: a static landing page, the app itself (app.html: Welcome and Setup on first open, ?demo=1 for three
example repos) and, given a repo's docs folder, that repo's real data under demo/, built from the package into one static
folder (`stackvitals site build --out DIR --demo DOCS`)."""
import argparse
import re
import shutil
import sys
from pathlib import Path

from stackvitals.ci.cli import ACTION_REF
from stackvitals.core.webapp import files, site_files, stamped, write_webapp

REAL_DEMO = b"<!--REAL-DEMO-->"
README_SETUP = "https://github.com/stackvitals/stackvitals#quick-start"


def demo_only(pages: dict[str, bytes]) -> dict[str, bytes]:
    """The public demo: the browser may fetch only the site's own files, and setup points at the README."""
    out = dict(pages)
    for name, body in pages.items():
        if not name.endswith(".html"):
            continue
        body = re.sub(rb"connect-src [^;\"]*", b"connect-src 'self'", body)
        body = re.sub(rb"(img-src [^;\"]*?) https://[^;\"]*", rb"\1", body)
        out[name] = body.replace(b'href="app.html#/setup"', f'href="{README_SETUP}"'.encode())
    return out


def build(out: Path, demo: Path | None = None, ref: str = ACTION_REF, public_demo: bool = False) -> list[str]:
    """Write the site into `out`: index.html (landing), app.html and app/ (the app), setup.html and integrations.html
    (forwards from the earlier site's addresses), site/ styles, and demo/ (the app on a copy of `demo`, a docs folder).
    `ref` is kept for the command line; the app's Setup writes the workflow with the release it was built for."""
    out = Path(out)
    app = files()
    pages = {**{name: data for name, data in app.items() if name != "index.html"}, "app.html": app["index.html"], **site_files()}
    link = b'<a class="btn big" href="demo/">A real repo\'s data</a>' if demo else b""
    pages["index.html"] = pages["index.html"].replace(REAL_DEMO, link)
    if public_demo:
        pages = demo_only(pages)
    for name, data in stamped(pages).items():
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    if demo:
        target = out / "demo"
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(demo, target, ignore=shutil.ignore_patterns("app", "index.html"))
        write_webapp(target)
    return sorted(pages)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stackvitals site", description="Build the StackVitals project site.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="landing page, the app and an optional real-data demo into one folder")
    b.add_argument("--out", required=True, help="folder to write")
    b.add_argument("--demo", help="a repo's docs folder (from its stackvitals-data branch) to show as a real-data demo")
    b.add_argument("--ref", default=ACTION_REF, help=argparse.SUPPRESS)  # kept so older build scripts still run
    b.add_argument("--demo-only", action="store_true", help="the public demo: no outside calls, setup links to the README")
    args = parser.parse_args(argv)
    demo = Path(args.demo) if args.demo else None
    if demo and not (demo / "app.json").exists():
        print(f"{demo} has no app.json; give the docs folder of a repo's stackvitals-data branch.", file=sys.stderr)
        return 2
    written = build(Path(args.out), demo, args.ref, public_demo=args.demo_only)
    print(f"Site written to {args.out} ({len(written)} files{', with a real-data demo' if demo else ''}).")
    return 0
