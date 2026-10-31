"""The reviewer suggestions' prospective test: freeze today's top 3 suggestions (and the 3 busiest reviewers) for every
recent open pull request nobody in the project had reviewed yet, then, from 2027-01-15, score whether the maintainer
who first reviewed it was among them. The suggestions use only each repo's stored history; nobody has seen the outcomes.

    python bench/accuracy/team/prospective.py freeze --flow <folder of flow stores, one per repo>
    GH_TOKEN=... python bench/accuracy/team/prospective.py score     # 2027-01-15 or later
"""
import argparse
import gzip
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[2] / "src"))
from fair import by_repo, mcnemar  # noqa: E402

from stackvitals.core.actors import kind_of  # noqa: E402
from stackvitals.core.stats import wilson  # noqa: E402
from stackvitals.flow.knowledge import People, _human_reviews, _merged_humans, expertise, suggest_reviewers  # noqa: E402
from stackvitals.flow.store import FlowStore  # noqa: E402

FROZEN, MANIFEST = HERE / "prospective-frozen.json.gz", HERE / "prospective-manifest.json"
NOT_BEFORE = date(2027, 1, 15)
RECENT_DAYS = 30  # only pull requests opened in the 30 days before the read; older ones are backlog
INSIDERS = {"OWNER", "MEMBER", "COLLABORATOR"}


def _who(login: str) -> str:
    # Logins are kept hashed, so the frozen file names nobody; scoring hashes the real reviewer the same way.
    return hashlib.sha256(login.lower().encode()).hexdigest()[:16]


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def freeze(flow: Path) -> int:
    items = []
    for folder in sorted(p for p in flow.iterdir() if p.is_dir()):
        data = FlowStore(folder).load()
        prs = (data.get("closed") or []) + (data.get("open") or [])
        if not prs:
            continue
        repo = folder.name.replace("__", "/", 1)
        read_at = max(_t(p.get("up") or p["cr"]) for p in prs)
        people = People(prs)
        merged = _merged_humans(prs, read_at)
        counts = Counter(e[2] for q in merged for e in _human_reviews(q) if people.is_insider(e[2]) and e[2] != q.get("au"))
        ex = expertise(prs, read_at, people=people)
        for p in data.get("open") or []:
            if (not p.get("paths") or p.get("draft") or kind_of(p.get("au"), p.get("at")) != "person"
                    or _t(p["cr"]) < read_at - timedelta(days=RECENT_DAYS)
                    or any(people.is_insider(e[2]) for e in _human_reviews(p))):
                continue
            ours = [s["login"] for s in suggest_reviewers(p, ex, load={}, owners={}) if s["login"] != p.get("au")]
            busiest = [r for r, _n in counts.most_common(4) if r != p.get("au")][:3]
            if ours:
                items.append({"repo": repo, "pr": p["n"], "opened": p["cr"], "read_at": read_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                              "author": _who(p.get("au") or ""),
                              "suggested": [_who(x) for x in ours[:3]], "busiest": [_who(x) for x in busiest]})
    data = gzip.compress(json.dumps(items, separators=(",", ":")).encode(), mtime=0)
    FROZEN.write_bytes(data)
    manifest = {"frozen_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "items": len(items),
                "repos": len({i["repo"] for i in items}), "not_before": NOT_BEFORE.isoformat(),
                "sha256": hashlib.sha256(data).hexdigest(),
                "rule": "hit when the first review by an owner, member or collaborator (not the author) after frozen_at "
                        "came from one of the 3 names; pull requests closed or still unreviewed by a maintainer on the "
                        "scoring day are counted apart, never as misses. Reviews between read_at and frozen_at existed "
                        "before the freeze, so they are scored apart as a second, weaker read",
                "test": "primary: the suggestions' hit share with its Wilson 95% range; against the 3 busiest reviewers, "
                        "McNemar's test on the pull requests where exactly one of the two lists held the reviewer",
                "bar": "met when the suggestions' lower bound is at least 65% and McNemar doesn't show the busiest "
                       "reviewers doing better (p < 0.05); repo ranges (bootstrap, each repo once) reported beside it"}
    MANIFEST.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=1))
    return 0


def score() -> int:
    if date.today() < NOT_BEFORE:
        print(f"The prospective read opens on {NOT_BEFORE}; the frozen suggestions stay unscored until then.")
        return 1
    import httpx
    items = json.loads(gzip.decompress(FROZEN.read_bytes()))
    client = httpx.Client(timeout=60, headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}",
                                               "Accept": "application/vnd.github+json"})
    frozen_at = json.loads(MANIFEST.read_text(encoding="utf-8"))["frozen_at"]
    reviews_of = {}
    for it in items:
        got, page = [], 1
        while True:
            resp = client.get(f"https://api.github.com/repos/{it['repo']}/pulls/{it['pr']}/reviews",
                              params={"per_page": 100, "page": page})
            batch = resp.json() if resp.status_code == 200 else []
            got += batch
            if len(batch) < 100:
                break
            page += 1
        reviews_of[(it["repo"], it["pr"])] = sorted(got, key=lambda r: r.get("submitted_at") or "")

    def read(after) -> dict:
        rows, unreviewed = [], 0
        for it in items:
            first = next((_who(r["user"]["login"]) for r in reviews_of[(it["repo"], it["pr"])]
                          if r.get("user") and r.get("author_association") in INSIDERS and (r.get("submitted_at") or "") > after(it)
                          and _who(r["user"]["login"]) != it.get("author")), None)
            if first is None:
                unreviewed += 1
                continue
            rows.append((it["repo"], first in it["suggested"], first in it["busiest"]))
        n = len(rows)
        res = {"reviewed": n, "not_reviewed_by_a_maintainer": unreviewed}
        for i, name in ((1, "suggested"), (2, "busiest_reviewers")):
            k = sum(r[i] for r in rows)
            lo, hi = wilson(k, n)
            res[name] = {"hits": k, "share": round(k / n, 4) if n else None, "low": round(lo, 4), "high": round(hi, 4),
                         "by_repo": by_repo([(r[0], r[i]) for r in rows])}
        res["suggested_vs_busiest"] = mcnemar(sum(o and not b for _r, o, b in rows), sum(b and not o for _r, o, b in rows))
        return res
    out = {"prs": len(items), "after_freeze": read(lambda it: frozen_at), "after_read_weaker": read(lambda it: it["read_at"])}
    (HERE / "prospective-results.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=("freeze", "score"))
    ap.add_argument("--flow", type=Path)
    args = ap.parse_args(argv)
    return freeze(args.flow) if args.cmd == "freeze" else score()


if __name__ == "__main__":
    raise SystemExit(main())
