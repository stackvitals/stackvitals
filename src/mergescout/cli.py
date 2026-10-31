import argparse
import json
import logging
import sys

import httpx

from mergescout.github.releases import ReleaseError
from mergescout.mcp_server import App, NoSnapshot, build_server, live_status, plain
from mergescout.tool.live import LiveError
from mergescout.tool.action_pack import build_action_pack
from mergescout.tool.refs import parse_ref


def _print(data) -> None:
    print(json.dumps(data, indent=1, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv) or ["serve"]
    parser = argparse.ArgumentParser(prog="mergescout", description="Find open-source issues you can get merged.",
                                     epilog="Also: `stackvitals contribute brief owner/repo`, how changes get merged in a repo.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve", help="Run the MCP server on stdio (what Claude Code and Cursor start)")
    u = sub.add_parser("update", help="Download the newest snapshot")
    u.add_argument("--force", action="store_true")
    f = sub.add_parser("find", help="Best free issues")
    f.add_argument("--lang")
    f.add_argument("--topic")
    f.add_argument("--beginner", action="store_true")
    f.add_argument("--no-walls", action="store_true")
    f.add_argument("--limit", type=int, default=10)
    f.add_argument("--json", action="store_true")
    for name in ("check", "explain", "pack", "health", "track", "untrack"):
        sub.add_parser(name).add_argument("ref")
    o = sub.add_parser("outcome")
    o.add_argument("ref")
    o.add_argument("outcome")
    o.add_argument("--note", default="")
    sub.add_parser("tracked")
    sub.add_parser("stats")
    args = parser.parse_args(argv)
    if args.cmd == "serve":
        # Request lines from the HTTP library would only clutter the AI client's log.
        logging.getLogger("httpx").setLevel(logging.WARNING)
        build_server(App()).run("stdio")
        return 0
    app = App(log=lambda msg: print(msg, file=sys.stderr))
    try:
        if args.cmd == "update":
            print(app.store.update(force=args.force))
        elif args.cmd == "find":
            out = app.snapshot().find_issues(args.lang, args.topic, args.beginner, 0.0, not args.no_walls, args.limit)
            if args.json:
                _print(out)
            else:
                print(f"snapshot {out['snapshot']}  ({out['note']})")
                for r in out["results"]:
                    print(f"{r['score']:.2f}  {r['issue']}  {r['title']}\n      {r['outsider_merge']}; {r['review']}"
                          + (f"; walls: {', '.join(r['walls'])}" if r["walls"] else ""))
        elif args.cmd == "check":
            _print(live_status(app, parse_ref(args.ref)))
        elif args.cmd == "explain":
            ref = parse_ref(args.ref)
            _print(app.snapshot().explain(ref.repo, ref.number))
        elif args.cmd == "pack":
            _print(build_action_pack(app.snapshot(), parse_ref(args.ref)))
        elif args.cmd == "health":
            _print(app.snapshot().repo_health(parse_ref(args.ref).repo, detail=True))
        elif args.cmd == "track":
            ref = parse_ref(args.ref)
            _print(app.tracker.track(ref.key, app.live.issue_status(ref.owner, ref.name, ref.number)))
        elif args.cmd == "untrack":
            app.tracker.untrack(parse_ref(args.ref).key)
            _print({"tracked": sorted(app.tracker.tracked())})
        elif args.cmd == "tracked":
            _print({"tracked": app.tracker.tracked(), "changes": app.tracker.updates(app.live)})
        elif args.cmd == "outcome":
            _print(app.tracker.report_outcome(parse_ref(args.ref).key, args.outcome, args.note))
        elif args.cmd == "stats":
            _print(app.snapshot().stats())
    except (NoSnapshot, ValueError, LiveError, httpx.HTTPError, ReleaseError) as exc:
        print(plain(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
