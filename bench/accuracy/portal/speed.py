"""How light the Portal's core is: a full catalog run on public orgs, cold (nothing kept) and then warm (the next day's
run), counting REST requests, GraphQL points, seconds and repos that failed. Run before and after a change with the same
orgs; results go to speed-<label>.json beside this script.

    GH_TOKEN=... python bench/accuracy/portal/speed.py --label before pallets astral-sh
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "src"))
from mergescout.github.graphql import GitHubGraphQL  # noqa: E402
from stackvitals.ci.api import ActionsAPI  # noqa: E402
from stackvitals.portal.catalog import build_catalog  # noqa: E402


class CountingGql(GitHubGraphQL):
    points = 0

    def query(self, q, v):
        r = super().query(q, v)
        CountingGql.points += r.cost
        return r


def run(org: str, token: str, now: datetime, previous: dict | None, etags: dict) -> tuple[dict, dict]:
    CountingGql.points = 0
    api = ActionsAPI(token, f"{org}/portal", max_requests=2000)
    try:
        from stackvitals.portal.catalog import cacheable
        api.etags, api.cacheable = etags, cacheable  # kept between the cold and warm runs, as the data branch keeps them
    except ImportError:
        pass
    t = time.monotonic()
    catalog = build_catalog(api, org, "public", now, previous=previous, scorecard_client=None, gql=CountingGql(token))
    seconds = time.monotonic() - t
    checked = [r for r in catalog["repos"] if r.get("checked") and not r.get("archived") and not r.get("fork")]
    return catalog, {"repos": len(catalog["repos"]), "checked": len(checked), "complete": catalog["complete"],
                     "rest": api.requests, "unchanged": getattr(api, "unchanged", 0),
                     "counted": api.requests - getattr(api, "unchanged", 0),
                     "graphql_points": CountingGql.points, "seconds": round(seconds, 1),
                     "rest_per_repo": round(api.requests / max(len(checked), 1), 2),
                     "errors": sum(1 for r in catalog["repos"] if r.get("error"))}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("orgs", nargs="+")
    ap.add_argument("--label", required=True)
    ap.add_argument("--keep", type=Path, help="a work folder to keep each org's catalogs in, to compare runs")
    args = ap.parse_args(argv)
    token, now = os.environ["GH_TOKEN"], datetime.now(timezone.utc)
    out = {"label": args.label, "read": now.strftime("%Y-%m-%d"), "orgs": {}}
    for org in args.orgs:
        etags = {}
        catalog, cold = run(org, token, now, None, etags)
        later, warm = run(org, token, now + timedelta(days=1), catalog, etags)
        if args.keep:
            args.keep.mkdir(parents=True, exist_ok=True)
            (args.keep / f"{org}-{args.label}.json").write_text(json.dumps({"cold": catalog, "warm": later}), encoding="utf-8")
        out["orgs"][org] = {"cold": cold, "warm": warm}
        print(org, "cold", cold, "warm", warm, flush=True)
    (HERE / f"speed-{args.label}.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
