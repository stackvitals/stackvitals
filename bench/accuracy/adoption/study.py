"""The pre-registered adoption study (preregistration.md): does installing StackVitals change a repo's red-CI hours,
review wait and newcomers' return more than in matched repos that didn't install it?

    python bench/accuracy/adoption/study.py freeze                    # once, before launch
    GH_TOKEN=... python bench/accuracy/adoption/study.py find         # writes adopters.json (code search)
    GH_TOKEN=... python bench/accuracy/adoption/study.py score --crawl <crawl folder: prs/, repo_meta/>   # 2027-07-01 on

Both refuse once a read included 20+ adopters or after 2028-07-01: the last read stands.
"""
import argparse
import hashlib
import json
import os
import random
import statistics
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "src"))
from mergescout.bench.ci import tier  # noqa: E402

MANIFEST, ADOPTERS, RESULTS = HERE / "manifest.json", HERE / "adopters.json", HERE / "results.json"
NOT_BEFORE, LAST_READ = date(2027, 7, 1), date(2028, 7, 1)
USES = "stackvitals/stackvitals@"
INSIDERS = {"OWNER", "MEMBER", "COLLABORATOR"}
BEFORE, SETUP, AFTER, RETURN = 90, 30, 120, 60  # days: pre-period, setup skipped, end of post-period, return window
LOOKBACK, PAGES = 7, 30  # days of runs read before a period (its starting state); pages per runs query
MIN_ADOPTERS, MIN_PRS, SEED, DRAWS = 20, 10, 23, 2000
OUTCOMES = (("red_ci_hours", True), ("review_wait_hours", True), ("newcomer_return", False))  # (name, lower is better)


def _hashes() -> dict:
    # Line endings are normalised, so a Windows checkout hashes the same as Linux.
    sha = lambda p: hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()  # noqa: E731
    return {"preregistration_sha256": sha(HERE / "preregistration.md"), "study_sha256": sha(Path(__file__))}


def freeze() -> int:
    manifest = {"frozen_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **_hashes()}
    MANIFEST.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=1))
    return 0


def red_hours(runs: list[dict], start: datetime, end: datetime) -> float | None:
    """Hours per 30 days in which some workflow's latest completed push run on the default branch had failed.
    Runs before start set the starting state; a period with no completed run in it has no data (None)."""
    done = ("success", "failure", "timed_out")
    if not any(r["c"] in done and start <= r["at"] <= end for r in runs):
        return None
    latest, red, since = {}, 0.0, None
    for r in sorted(runs, key=lambda r: r["at"]):
        if r["c"] not in done or r["at"] > end:
            continue
        latest[r["wf"]] = r["c"] != "success"
        now_red, at = any(latest.values()), max(r["at"], start)
        if since is not None and not now_red:
            red += (at - since).total_seconds()
            since = None
        elif since is None and now_red:
            since = at
    if since is not None:
        red += (end - since).total_seconds()
    days = (end - start).total_seconds() / 86400
    return red / 3600 * 30 / days if days else 0.0


def _people(prs: list[dict]) -> list[dict]:
    return [p for p in prs if not p["bot"]]


def review_wait(prs: list[dict], start: datetime, end: datetime) -> dict:
    mine = [p for p in _people(prs) if start <= p["created"] < end]
    waits = [(p["review_at"] - p["created"]).total_seconds() / 3600 for p in mine
             if p["review_at"] and p["review_by"] != p["author"] and p["review_assoc"] in INSIDERS]
    return {"hours": statistics.median(waits) if waits else None, "reviewed": len(waits), "people_prs": len(mine)}


def newcomer_return(prs: list[dict], start: datetime, end: datetime) -> dict:
    by = {}
    for p in sorted(_people(prs), key=lambda p: p["created"]):
        if p["assoc"] not in INSIDERS:
            by.setdefault(p["author"], []).append(p["created"])
    new = [t for t in by.values() if start <= t[0] < end]
    back = sum(len(t) > 1 and t[1] - t[0] <= timedelta(days=RETURN) for t in new)
    return {"share": back / len(new) if new else None, "newcomers": len(new)}


def match(adopter: dict, pool: list[dict], k: int = 3, seed: int = SEED) -> list[dict]:
    """Up to k comparison repos: same language and star tier, half to double the pull requests, closest review wait."""
    rng = random.Random(f"{seed}:{adopter['repo']}")
    # Sorted by name first, so the seeded tie-break doesn't depend on the crawl's file order.
    ok = sorted((c for c in pool if c["repo"] != adopter["repo"] and c["language"] == adopter["language"]
                 and c["tier"] == adopter["tier"] and adopter["prs"] / 2 <= c["prs"] <= adopter["prs"] * 2
                 and c.get("wait") is not None), key=lambda c: c["repo"])
    keyed = sorted(ok, key=lambda c: (abs(c["wait"] - adopter["wait"]), rng.random()))
    return keyed[:k]


def bootstrap(diffs: list[float], seed: int = SEED, draws: int = DRAWS) -> tuple[float, float, float]:
    """The 95% range of the mean over adopters and a two-sided p-value: twice the smaller share of draws on either
    side of zero, at least 1/draws."""
    rng = random.Random(seed)
    means = sorted(statistics.mean(rng.choice(diffs) for _ in diffs) for _ in range(draws))
    lo, hi = means[int(0.025 * draws)], means[int(0.975 * draws) - 1]
    below, above = sum(m <= 0 for m in means) / draws, sum(m >= 0 for m in means) / draws
    return lo, hi, min(1.0, max(2 * min(below, above), 1 / draws))


def holm(ps: dict) -> dict:
    """Holm-adjusted p-values; an outcome without a p-value counts as p = 1, so the family size stays fixed."""
    order = sorted(ps, key=lambda k: 1.0 if ps[k] is None else ps[k])
    adj, run = {}, 0.0
    for i, k in enumerate(order):
        run = max(run, min(1.0, (len(order) - i) * (1.0 if ps[k] is None else ps[k])))
        adj[k] = run
    return adj


def did(pairs: dict, included: int, seed: int = SEED, draws: int = DRAWS, alpha: float = 0.05) -> dict:
    """pairs: per outcome, each adopter's change and its comparison repos' changes. Per outcome, the mean difference
    in differences with a bootstrap 95% range and p-value, Holm-adjusted across the outcomes, and the reading."""
    out, ps = {}, {}
    for name, _ in OUTCOMES:
        diffs = [p["adopter"] - statistics.mean(p["controls"]) for p in pairs.get(name, []) if p["controls"]]
        out[name] = {"adopters": len(diffs), "mean": statistics.mean(diffs) if diffs else None, "range": None,
                     "p": None, "p_holm": None}
        if included >= MIN_ADOPTERS and diffs:
            lo, hi, ps[name] = bootstrap(diffs, seed, draws)
            out[name].update(range=[lo, hi], p=ps[name])
    if included < MIN_ADOPTERS:
        return {name: {**o, "read": "too few adopters to tell"} for name, o in out.items()}
    adj = holm({name: ps.get(name) for name, _ in OUTCOMES})
    for name, lower_is_better in OUTCOMES:
        o = out[name]
        if o["mean"] is None:
            o["read"] = "no data"
            continue
        o["p_holm"] = adj[name]
        better = -o["mean"] if lower_is_better else o["mean"]
        o["read"] = ("no measurable difference" if adj[name] >= alpha or better == 0
                     else "helped" if better > 0 else "hurt")
    return out


def _gh(path: str, params: dict | None = None):
    import httpx
    resp = httpx.get(f"https://api.github.com{path}", params=params, timeout=60,
                     headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}", "Accept": "application/vnd.github+json"})
    resp.raise_for_status()
    return resp.json()


def _finished(today: date) -> str | None:
    """Why no further read may run: a read already included 20+ adopters, or the last read day has passed."""
    if today > LAST_READ:
        return f"The last pre-registered read day ({LAST_READ}) has passed; the last read stands."
    done = json.loads(RESULTS.read_text(encoding="utf-8")).get("included", 0) if RESULTS.exists() else 0
    if done >= MIN_ADOPTERS:
        return f"A read already included {done} adopters (20+ needed); it stands and is not scored again."
    return None


def _oldest_commit(repo: str, path: str) -> str | None:
    """The oldest commit date of a file, paging through its whole history (newest first)."""
    oldest, page = None, 1
    while True:
        commits = _gh(f"/repos/{repo}/commits", {"path": path, "per_page": 100, "page": page})
        dates = [c["commit"]["committer"]["date"] for c in commits]
        oldest = min(dates + ([oldest] if oldest else [])) if dates else oldest
        if len(commits) < 100:
            return oldest
        page += 1


def find(today: date | None = None) -> int:
    """Public repos whose workflows use the Action, with the oldest commit of the workflow file that uses it."""
    why = _finished(today or date.today())
    if why:
        print(why, file=sys.stderr)
        return 4
    found = {}
    for page in range(1, 11):
        items = _gh("/search/code", {"q": f'"{USES}" path:.github/workflows', "per_page": 100, "page": page})["items"]
        for it in items:
            repo = it["repository"]
            if repo.get("fork") or repo["full_name"].lower().startswith(("kaushik-yadav/", "stackvitals/")):
                continue
            first = _oldest_commit(repo["full_name"], it["path"])
            if first and (repo["full_name"] not in found or first < found[repo["full_name"]]):
                found[repo["full_name"]] = first
        if len(items) < 100:
            break
    ADOPTERS.write_text(json.dumps([{"repo": r, "installed": d} for r, d in sorted(found.items())], indent=1) + "\n",
                        encoding="utf-8")
    print(f"{len(found)} adopters: {ADOPTERS}")
    return 0


def _runs(repo: str, branch: str, start: datetime, end: datetime) -> list[dict]:
    """Push runs on the branch from 7 days before start (so the state at start is known) to end."""
    found = {r["id"]: r for r in _runs_span(repo, branch, start - timedelta(days=LOOKBACK), end)}
    return list(found.values())


def _runs_span(repo: str, branch: str, start: datetime, end: datetime) -> list[dict]:
    span = f"{start:%Y-%m-%dT%H:%M:%SZ}..{end:%Y-%m-%dT%H:%M:%SZ}"
    out = []
    for page in range(1, PAGES + 1):
        got = _gh(f"/repos/{repo}/actions/runs", {"branch": branch, "event": "push", "created": span, "per_page": 100,
                                                  "page": page})["workflow_runs"]
        out += [{"id": r["id"], "wf": r["workflow_id"], "c": r.get("conclusion"),
                 "at": datetime.fromisoformat(r["updated_at"].replace("Z", "+00:00"))} for r in got]
        if len(got) < 100:
            break
    # The API returns at most 1,000 runs per filtered query, so a full answer is read again in two halves.
    if len(out) >= 1000 and end - start > timedelta(hours=1):
        mid = start + (end - start) / 2
        return _runs_span(repo, branch, start, mid) + _runs_span(repo, branch, mid, end)
    return out


def _crawl(crawl: Path) -> tuple[dict, dict]:
    import duckdb
    con = duckdb.connect()
    meta = {n: {"language": lang, "tier": tier(s), "branch": b} for n, lang, s, b in con.execute(f"""
        SELECT name, language, stars, default_branch FROM read_parquet('{(crawl / 'repo_meta').as_posix()}/*.parquet',
            union_by_name = true) WHERE NOT coalesce(archived, false)
        QUALIFY row_number() OVER (PARTITION BY repo_id ORDER BY fetched_at DESC) = 1""").fetchall()}
    prs = {}
    for n, c, a, s, typ, ra, rb, rs in con.execute(f"""
        SELECT m.name, p.created_at, lower(p.author_login), p.author_association, p.author_type,
               p.first_human_review_at, lower(p.first_human_review_by), p.first_human_review_association
        FROM read_parquet('{(crawl / 'prs').as_posix()}/*.parquet', union_by_name = true) p
        JOIN (SELECT DISTINCT repo_id, name FROM read_parquet('{(crawl / 'repo_meta').as_posix()}/*.parquet',
                                                               union_by_name = true)) m USING (repo_id)
        QUALIFY row_number() OVER (PARTITION BY p.repo_id, p.number ORDER BY p.fetched_at DESC) = 1""").fetchall():
        utc = lambda t: t.astimezone(timezone.utc) if t else None  # noqa: E731
        prs.setdefault(n, []).append({"created": utc(c), "author": a, "assoc": s, "bot": typ == "Bot" or (a or "").endswith("[bot]"),
                                      "review_at": utc(ra), "review_by": rb, "review_assoc": rs})
    return meta, prs


def _periods(installed: datetime) -> tuple:
    return (installed - timedelta(days=BEFORE), installed), (installed + timedelta(days=SETUP), installed + timedelta(days=AFTER))


def _measures(repo: str, branch: str, prs: list[dict], period: tuple) -> dict:
    return {"red_ci_hours": red_hours(_runs(repo, branch, *period), *period),
            "review_wait_hours": review_wait(prs, *period)["hours"], "newcomer_return": newcomer_return(prs, *period)["share"]}


def score(crawl: Path | None, adopters_file: Path | None, today: date | None = None) -> int:
    today = today or date.today()
    if today < NOT_BEFORE:
        print(f"Too early: the pre-registered read is on or after {NOT_BEFORE}.", file=sys.stderr)
        return 2
    why = _finished(today)
    if why:
        print(why, file=sys.stderr)
        return 4
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if any(manifest.get(k) != v for k, v in _hashes().items()):
        print("The protocol or this scorer changed since it was frozen; refusing to score.", file=sys.stderr)
        return 3
    meta, prs = _crawl(crawl)
    adopters = json.loads((adopters_file or ADOPTERS).read_text(encoding="utf-8"))
    names = {a["repo"] for a in adopters}
    left_out, pairs, included = {}, {name: [] for name, _ in OUTCOMES}, 0
    for a in adopters:
        installed = datetime.fromisoformat(a["installed"].replace("Z", "+00:00"))
        why = ("not in the crawl" if a["repo"] not in meta else
               "installed under 180 days ago" if installed.date() > today - timedelta(days=AFTER + RETURN) else None)
        before, after = _periods(installed)
        mine = prs.get(a["repo"], [])
        if not why and review_wait(mine, *before)["people_prs"] < MIN_PRS:
            why = "under 10 pull requests by people before installing"
        if why:
            left_out[why] = left_out.get(why, 0) + 1
            continue
        stats = lambda n: {"repo": n, **meta[n], "prs": review_wait(prs.get(n, []), *before)["people_prs"],  # noqa: E731
                           "wait": review_wait(prs.get(n, []), *before)["hours"]}
        mine_stats = stats(a["repo"])
        if mine_stats["wait"] is None:
            left_out["no review wait before installing"] = left_out.get("no review wait before installing", 0) + 1
            continue
        pool = [stats(n) for n in meta if n not in names and n in prs]
        controls = match(mine_stats, pool)
        if not controls:
            left_out["no comparison repo"] = left_out.get("no comparison repo", 0) + 1
            continue
        included += 1
        change = lambda n: {k: (y - x) if x is not None and y is not None else None for (k, x), y in zip(  # noqa: E731
            _measures(n, meta[n]["branch"], prs.get(n, []), before).items(),
            _measures(n, meta[n]["branch"], prs.get(n, []), after).values())}
        mine_change, theirs = change(a["repo"]), [change(c["repo"]) for c in controls]
        for name, _ in OUTCOMES:
            ctl = [t[name] for t in theirs if t[name] is not None]
            if mine_change[name] is not None and ctl:
                pairs[name].append({"adopter": mine_change[name], "controls": ctl})
    out = {**_hashes(), "read_on": today.isoformat(), "adopters_found": len(adopters), "included": included,
           "left_out": left_out, "outcomes": did(pairs, included)}
    RESULTS.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=("freeze", "find", "score"))
    ap.add_argument("--crawl", type=Path)
    ap.add_argument("--adopters", type=Path)
    args = ap.parse_args(argv)
    return freeze() if args.cmd == "freeze" else find() if args.cmd == "find" else score(args.crawl, args.adopters)


if __name__ == "__main__":
    sys.exit(main())
