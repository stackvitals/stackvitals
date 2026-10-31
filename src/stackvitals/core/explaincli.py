"""`stackvitals explain owner/repo lead-time`: a headline number, what it means, and the pull requests, deployments or
pushes it was counted from, each with its GitHub link. Reads the repo's published files (a local copy of its
stackvitals-data branch, as `stackvitals ui` keeps, or a docs folder with --docs)."""
import argparse
import json
import sys
from pathlib import Path

PHASES = ("coding", "pickup", "review", "approve", "merge", "deploy", "cycle", "cycle-to-merge")
NUMBERS = ("deployments", "lead-time", "change-failure", "recovery", "first-try", *PHASES)


def _hours(minutes) -> str:
    return "?" if minutes is None else f"{minutes / 60:.1f} h"


def _pct(x) -> str:
    return "?" if x is None else f"{round(x * 100)}%"


def explain(repo: str, what: str, delivery: dict | None, data: dict | None) -> dict | None:
    """{"headline", "meaning", "items": [{..., "url"}], "total"} for one number, or None when it isn't published."""
    gh = f"https://github.com/{repo}"
    dora = (delivery or {}).get("dora") or {}
    ev = dora.get("evidence") or {}
    if what == "deployments":
        rows = ev.get("deployments") or []
        return {"headline": f"Deployments: {dora.get('deployments', len(rows))} in {(delivery or {}).get('window_days', '?')} days",
                "meaning": "Every deployment counted, oldest first; deployment frequency counts the days they landed on.",
                "items": [{"commit": c, "finished": t, "url": f"{gh}/commit/{c}"} for c, t in rows], "total": len(rows)}
    if what == "lead-time":
        rows = ev.get("lead_time") or []
        return {"headline": f"Change lead time: {dora.get('lead_time_hours', '?')} h (median of {dora.get('lead_time_n', len(rows))} deployed pull requests)",
                "meaning": "Each deployed pull request with its time from first commit to deployment, longest first.",
                "items": [{"pr": n, "deployment": c, "time": _hours(m), "url": f"{gh}/pull/{n}"} for n, c, m in rows],
                "total": ev.get("lead_time_total", len(rows))}
    if what in ("change-failure", "recovery"):
        key = "failed" if what == "change-failure" else "recovery"
        rows = ev.get(key) or []
        head = (f"Change fail rate: {_pct(dora.get('change_failure_rate'))} ({dora.get('failed_deployments', len(rows))} of {dora.get('deployments', '?')} deployments)"
                if key == "failed" else f"Failed deployment recovery: {dora.get('recovery_hours', '?')} h (median of {dora.get('recovery_n', len(rows))})")
        kind = lambda s: "issues" if s == "issue" else "pull"  # noqa: E731
        items = [{"deployment": r[0], "incident": f"{r[1]} #{r[2]}", **({"time": _hours(r[3])} if key == "recovery" else {}),
                  "url": f"{gh}/{kind(r[1])}/{r[2]}" if r[2] and r[1] in ("issue", "revert", "hotfix") else f"{gh}/commit/{r[0]}"} for r in rows]
        return {"headline": head, "meaning": "Each deployment tied to an incident after it (a revert, a hotfix or an incident issue)"
                + ("." if key == "failed" else ", with the time until it was resolved."), "items": items, "total": len(rows)}
    if what == "first-try":
        p = (data or {}).get("pushes") or {}
        rows = p.get("not_first_try") or []
        return {"headline": f"Green on the first try: {_pct(p.get('first_try_share'))} of {p.get('pushes', '?')} pushes",
                "meaning": "The pushes whose checks failed or needed a re-run, newest first, with those runs.",
                "items": [{"commit": c, "branch": b, "runs": ids, "url": f"{gh}/actions/runs/{ids[0]}" if ids else f"{gh}/commit/{c}"}
                          for c, b, ids in rows], "total": p.get("not_first_try_total", len(rows))}
    if what in PHASES:
        ph = ((delivery or {}).get("phases") or {}).get(what.replace("-", "_")) or {}
        rows = ph.get("evidence") or []
        p75 = f"P75 {ph['p75_h']} h" if ph.get("p75_h") is not None else "too few to read a P75"
        return {"headline": f"{what.replace('-', ' ').capitalize()}: {p75} over {ph.get('n', len(rows))} merged pull requests",
                "meaning": "Each merged pull request's hours in this phase, longest first.",
                "items": [{"pr": n, "time": f"{h:.1f} h", "url": f"{gh}/pull/{n}"} for n, h in rows], "total": ph.get("n", len(rows))}
    return None


def _read(docs: Path, name: str) -> dict | None:
    try:
        return json.loads((docs / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="stackvitals explain", description=__doc__.split("\n\n")[0])
    ap.add_argument("repo", help="owner/name")
    ap.add_argument("number", help=", ".join(NUMBERS))
    ap.add_argument("--docs", help="a docs folder to read instead of the repo's data branch")
    ap.add_argument("--limit", type=int, default=20, help="items to print (default 20)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.number not in NUMBERS:
        print(f"Can't explain {args.number!r}. Pick one of: {', '.join(NUMBERS)}.", file=sys.stderr)
        return 2
    if args.docs:
        docs = Path(args.docs)
    else:
        from stackvitals.ci import cli as ci_cli
        from stackvitals.core.uicli import fetch
        folder = Path(ci_cli.home()) / "ui" / args.repo.replace("/", "__")
        try:
            docs = fetch(args.repo, ci_cli.token(), folder) / "docs"
        except RuntimeError as exc:
            print(f"Could not read {args.repo}: {exc}", file=sys.stderr)
            return 1
    out = explain(args.repo, args.number, _read(docs, "delivery.json"), _read(docs, "data.json"))
    if not out or not out["items"]:
        print(f"{args.repo} hasn't published what's behind {args.number} yet (the next scheduled run writes it).", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(out, indent=1))
        return 0
    shown = out["items"][:args.limit]
    print(out["headline"])
    print(out["meaning"])
    for it in shown:
        print("  " + "  ".join(f"#{v}" if k == "pr" else str(v) for k, v in it.items() if k != "url") + f"  {it['url']}")
    if out["total"] > len(shown):
        print(f"({len(shown)} of {out['total']} shown; --limit for more, --json for all published)")
    return 0
