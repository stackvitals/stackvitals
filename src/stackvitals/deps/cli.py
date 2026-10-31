import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from stackvitals.ci.cli import home, token
from stackvitals.deps.dossier import dossier
from stackvitals.deps.evidence import load_evidence
from stackvitals.deps.lockfiles import read_lockfile

MARKS = {"good": "+", "info": ".", "warn": "!", "alarm": "!!"}
ORDER = {"investigate": 0, "monitor": 1, "use": 2, None: 3}
FOOTER = ("Evidence from the crawl's upgrade PRs and maintainer history, deps.dev and OSV. "
          "Verdicts weigh what happened, not what will.")


def find(spec: str, ev: dict, now: datetime, ecosystem: str | None = None) -> list[dict]:
    # "pypi:requests" names its ecosystem; a bare name is looked up in npm and PyPI and shown where it is known.
    if ":" in spec:
        eco, name = spec.split(":", 1)
        return [dossier(eco, name, ev, now)]
    found = [dossier(eco, spec, ev, now) for eco in ([ecosystem] if ecosystem else ["pypi", "npm"])]
    known = [d for d in found if d["lines"] and "not in the evidence set" not in d["lines"][0]["text"]]
    return known or found[:1]


def render(d: dict) -> str:
    head = f"{d['ecosystem']}:{d['package']}: {d['verdict'] or 'not enough evidence yet'}"
    lines = [head] + [f"  {MARKS[x['signal']]} {x['text']}" for x in d["lines"]]
    return "\n".join(lines)


def main(argv: list[str] | None = None, now: datetime | None = None) -> int:
    if argv and argv[0] == "imports":
        from stackvitals.deps.imports import main as imports_main
        return imports_main(argv[1:])
    parser = argparse.ArgumentParser(prog="stackvitals deps", description="Should we add, keep, upgrade or replace a package?")
    sub = parser.add_subparsers(dest="cmd", required=True)
    chk = sub.add_parser("check", help="One package's evidence and verdict: use, monitor or investigate")
    chk.add_argument("packages", nargs="+", help="names like requests, or pypi:requests / npm:lodash")
    chk.add_argument("--ecosystem", choices=["npm", "pypi"])
    chk.add_argument("--json", action="store_true")
    scan = sub.add_parser("scan", help="Every package in a lockfile, the ones that need a look first")
    scan.add_argument("lockfile", type=Path)
    scan.add_argument("--all", action="store_true", help="also list packages with a use verdict or too little evidence")
    scan.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    now = now or datetime.now(timezone.utc)
    ev = load_evidence(token(), home() / "deps")
    if ev is None:
        print("The dependency evidence couldn't be loaded. Set STACKVITALS_DEPS_MAP_URL (and the other "
              "STACKVITALS_DEPS_*_URL files), or a GitHub token that can read them.", file=sys.stderr)
        return 1
    if args.cmd == "check":
        found = [d for spec in args.packages for d in find(spec, ev, now, args.ecosystem)]
        print(json.dumps(found, indent=1) if args.json else "\n\n".join(render(d) for d in found) + f"\n\n{FOOTER}")
        return 0
    try:
        pinned = read_lockfile(args.lockfile)
    except (ValueError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 1
    found = sorted((dossier(eco, name, ev, now) for eco, name in dict.fromkeys((e, n) for e, n, _ in pinned)),
                   key=lambda d: (ORDER[d["verdict"]], d["package"]))
    if args.json:
        print(json.dumps(found, indent=1))
        return 0
    count = {v: sum(1 for d in found if d["verdict"] == v) for v in ORDER}
    print(f"{len(found)} packages: {count['investigate']} investigate, {count['monitor']} monitor, {count['use']} use, "
          f"{count[None]} not enough evidence")
    for d in found:
        if args.all or d["verdict"] in ("investigate", "monitor"):
            reason = d["reasons"][0] if d["reasons"] else ""
            print(f"  {d['verdict'] or 'not enough evidence':<10} {d['ecosystem']}:{d['package']}  {reason}")
    print(f"\n{FOOTER}")
    return 0
