"""First responses to outside contributors' issues under three published rules, on the same items across the crawl.

- issue-metrics (GitHub OSPO): the first comment by anyone but the author and bots; unanswered issues are dropped.
- OpenDigger: the first comment by anyone but the author (bots included) or a close; unanswered issues count as 15 days.
- StackVitals: the first comment by a maintainer (owner, member or collaborator, or anyone who merged a PR there, as
  the app's insiders; never a bot) or a regular responder (commented on 10+ other people's issues or first-reviewed 2+
  other people's PRs in the 360 days before the read), or a close; unanswered issues stay in as "still waiting"
  (Kaplan-Meier). The crawl doesn't record who closed an issue, so any close counts here. The roles-only rule is kept
  beside it for comparison.

Issues: opened by people who are not owners, members or collaborators, 1 to 180 days before the repo was read, in repos
with at least 10 of them. Reported: each rule's median per repo and how they compare, how often the answered-only median
looks settled while most issues still wait, and what the other rules counted as a first response. Also writes a
labelling sample: issues whose first non-author comment came from someone who isn't a maintainer (labeller's view in
responses-sample.jsonl; whether the commenter is a regular responder in responses-key.jsonl, kept from the labeller).
--exclude skips repos an earlier sample used; --stratify draws half the sample from regular responders' comments.

    python bench/accuracy/community/responses.py <crawl folder with issues/ and comments/> --home <work folder>
        [--exclude <earlier work folder>] [--stratify]
"""
import argparse
import json
import random
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb

from stackvitals.core.stats import km_median

MAINTAINERS = {"OWNER", "MEMBER", "COLLABORATOR"}
MIN_ISSUES = 10
IMPUTE_H = 15 * 24
SAMPLE_PER_REPO, SAMPLE = 5, 400
REGULAR_ISSUES, REGULAR_REVIEWS, REGULAR_DAYS = 10, 2, 360


def _hours(a, b) -> float:
    return (b - a).total_seconds() / 3600


def _bot(c: dict) -> bool:
    return c["type"] == "Bot" or (c["login"] or "").lower().endswith("[bot]")


def _maintainer(c: dict, mergers: set) -> bool:
    return not _bot(c) and (c["assoc"] in MAINTAINERS or (c["login"] or "") in mergers)


def _regulars(issues: list, comments: dict, reviews: list, mergers: dict) -> dict:
    """Per repo, people who answer others: comments on 10+ other people's issues or first reviews on 2+ other people's
    PRs in the 360 days before the read; maintainers and bots are left out."""
    read = {}
    for repo, _n, _a, _as, _c, _cl, fetched, _t in issues:
        if fetched:
            read[repo] = max(read.get(repo, fetched), fetched)
    on_issues, reviewed = defaultdict(set), Counter()
    for repo, number, author, _as, _c, _cl, _f, _t in issues:
        since = read[repo] - timedelta(days=REGULAR_DAYS) if repo in read else None
        for c in comments[(repo, number)]:
            if since and c["at"] and c["at"] >= since and c["login"] and c["login"] != author and not _bot(c):
                on_issues[(repo, c["login"])].add(number)
    for repo, author, created, who in reviews:
        if repo in read and created and created >= read[repo] - timedelta(days=REGULAR_DAYS) and who != author \
                and not who.endswith("[bot]"):
            reviewed[(repo, who)] += 1
    out = defaultdict(set)
    for (repo, login), numbers in on_issues.items():
        if len(numbers) >= REGULAR_ISSUES:
            out[repo].add(login)
    for (repo, login), n in reviewed.items():
        if n >= REGULAR_REVIEWS:
            out[repo].add(login)
    return {repo: logins - mergers[repo] for repo, logins in out.items()}


def load(folder: Path) -> tuple[list, dict, dict, dict]:
    """The crawl's issues, comments by issue, PR mergers by repo and regular responders by repo."""
    con = duckdb.connect()
    issues = con.execute(f"""
        SELECT repo_id, number, lower(author_login), author_association, created_at, closed_at, fetched_at, title
        FROM read_parquet('{(folder / 'issues' / '*.parquet').as_posix()}', union_by_name = true)
        QUALIFY row_number() OVER (PARTITION BY repo_id, number ORDER BY fetched_at DESC) = 1""").fetchall()
    # GitHub shows private org members as outsiders; whoever merged a PR in the repo is a maintainer whatever it says.
    mergers = defaultdict(set)
    for repo, login in con.execute(f"""
            SELECT DISTINCT repo_id, lower(merged_by) FROM read_parquet('{(folder / 'prs' / '*.parquet').as_posix()}', union_by_name = true)
            WHERE merged_by IS NOT NULL""").fetchall():
        mergers[repo].add(login)
    comments = defaultdict(list)
    for repo, number, created, login, assoc, kind, body in con.execute(f"""
            SELECT repo_id, number, created_at, lower(author_login), author_association, author_type, body_excerpt
            FROM read_parquet('{(folder / 'comments' / '*.parquet').as_posix()}', union_by_name = true)""").fetchall():
        comments[(repo, number)].append({"at": created, "login": login, "assoc": assoc, "type": kind, "body": body or ""})
    reviews = [(repo, author, created, who) for repo, author, created, first, human in con.execute(f"""
            SELECT repo_id, lower(author_login), created_at, lower(first_review_by), lower(first_human_review_by)
            FROM read_parquet('{(folder / 'prs' / '*.parquet').as_posix()}', union_by_name = true)
            QUALIFY row_number() OVER (PARTITION BY repo_id, number ORDER BY fetched_at DESC) = 1""").fetchall()
               for who in {first, human} - {None}]
    return issues, comments, mergers, _regulars(issues, comments, reviews, mergers)


def run(folder: Path, seed: int, exclude: set | None = None, stratify: bool = False) -> tuple[dict, list[dict], list[dict]]:
    issues, comments, mergers, regulars = load(folder)
    by_repo = defaultdict(list)
    for repo, number, author, assoc, created, closed, fetched, title in issues:
        if assoc in MAINTAINERS or author in mergers[repo] or not created or not fetched:
            continue
        age = (fetched - created).days
        if 1 <= age <= 180:
            by_repo[repo].append({"repo": repo, "number": number, "author": author, "created": created, "closed": closed,
                                  "fetched": fetched, "title": title,
                                  "comments": sorted((c for c in comments[(repo, number)] if c["at"] and c["at"] >= created),
                                                     key=lambda c: c["at"])})
    stats = {"repos": 0, "issues": 0, "most_waiting_but_answered_median_shown": 0, "understated_2x": 0, "both_defined": 0,
             "ratio_medians": [], "im_first_from_non_maintainer": 0, "im_answered": 0, "od_first_bot": 0, "od_first_close": 0,
             "im_first_from_regular": 0, "repos_with_regulars": 0, "roles_only_median_defined": 0,
             "with_regulars_median_defined": 0, "ratio_roles_to_regulars": []}
    sample_pool = []
    for repo, items in by_repo.items():
        if len(items) < MIN_ISSUES:
            continue
        stats["repos"] += 1
        stats["issues"] += len(items)
        regular = regulars.get(repo, set())
        stats["repos_with_regulars"] += bool(regular)
        im, od, sv_t, sv_done, rg_t, rg_done = [], [], [], [], [], []
        for it in items:
            others = [c for c in it["comments"] if c["login"] != it["author"]]
            human = next((c for c in others if not _bot(c)), None)
            if human:
                im.append(_hours(it["created"], human["at"]))
                stats["im_answered"] += 1
                if not _maintainer(human, mergers[repo]):
                    stats["im_first_from_non_maintainer"] += 1
                    stats["im_first_from_regular"] += human["login"] in regular
                    sample_pool.append({**it, "picked": human, "regular": human["login"] in regular})
            anyone = others[0] if others else None
            od_at = min([x for x in (anyone["at"] if anyone else None, it["closed"]) if x], default=None)
            od.append(_hours(it["created"], od_at) if od_at else IMPUTE_H)
            if od_at and anyone and od_at == anyone["at"] and _bot(anyone):
                stats["od_first_bot"] += 1
            if od_at and od_at == it["closed"] and not (anyone and anyone["at"] <= it["closed"]):
                stats["od_first_close"] += 1
            maint = next((c for c in others if _maintainer(c, mergers[repo])), None)
            sv_at = min([x for x in (maint["at"] if maint else None, it["closed"]) if x], default=None)
            sv_t.append(_hours(it["created"], sv_at or it["fetched"]))
            sv_done.append(sv_at is not None)
            reg = next((c for c in others if _maintainer(c, mergers[repo]) or (c["login"] in regular and not _bot(c))), None)
            rg_at = min([x for x in (reg["at"] if reg else None, it["closed"]) if x], default=None)
            rg_t.append(_hours(it["created"], rg_at or it["fetched"]))
            rg_done.append(rg_at is not None)
        km = km_median(sv_t, sv_done)
        km_reg = km_median(rg_t, rg_done)
        stats["roles_only_median_defined"] += km["median"] is not None
        stats["with_regulars_median_defined"] += km_reg["median"] is not None
        if km["median"] is not None and km_reg["median"]:
            stats["ratio_roles_to_regulars"].append(km["median"] / max(km_reg["median"], 1 / 60))
        im_median = statistics.median(im) if im else None
        if km["median"] is None and im_median is not None:
            stats["most_waiting_but_answered_median_shown"] += 1
        if km["median"] is not None and im_median:
            stats["both_defined"] += 1
            stats["ratio_medians"].append(km["median"] / max(im_median, 1 / 60))
            stats["understated_2x"] += km["median"] >= 2 * im_median
    ratios = sorted(stats.pop("ratio_medians"))
    shifts = sorted(stats.pop("ratio_roles_to_regulars"))
    rng = random.Random(seed)
    # DuckDB returns rows in no fixed order: sort first so the seed alone fixes the sample.
    sample_pool = sorted((x for x in sample_pool if x["repo"] not in (exclude or set())), key=lambda x: (x["repo"], x["number"]))
    rng.shuffle(sample_pool)
    # Stratified: half from regular responders' comments (rare, so the rule's mistakes get enough items), half the rest.
    pools = [[x for x in sample_pool if x["regular"]], [x for x in sample_pool if not x["regular"]]] if stratify else [sample_pool]
    sample = []
    for pool in pools:
        per_repo = defaultdict(list)
        for x in pool:
            if len(per_repo[x["repo"]]) < SAMPLE_PER_REPO:
                per_repo[x["repo"]].append(x)
        sample += [x for xs in per_repo.values() for x in xs][: SAMPLE // len(pools)]
    if stratify:
        rng.shuffle(sample)
    out = {**stats, "median_ratio_km_to_answered_only": round(ratios[len(ratios) // 2], 2) if ratios else None,
           "median_ratio_roles_only_to_with_regulars": round(shifts[len(shifts) // 2], 2) if shifts else None,
           "im_first_from_non_maintainer_share": round(stats["im_first_from_non_maintainer"] / stats["im_answered"], 4)
           if stats["im_answered"] else None,
           "regular_rule": {"issues_commented": REGULAR_ISSUES, "prs_first_reviewed": REGULAR_REVIEWS, "days": REGULAR_DAYS},
           "pool": {"regular": sum(x["regular"] for x in sample_pool), "other": sum(not x["regular"] for x in sample_pool)},
           "seed": seed}
    rows = [{"id": n + 1, "repo": x["repo"], "issue": x["number"], "title": (x["title"] or "")[:200],
             "picked_login_role": x["picked"]["assoc"], "picked_hours": round(_hours(x["created"], x["picked"]["at"]), 2),
             "picked_text": x["picked"]["body"][:500],
             "later_maintainer_reply": any(_maintainer(c, mergers[x["repo"]]) for c in x["comments"] if c["at"] > x["picked"]["at"])}
            for n, x in enumerate(sample)]
    key = [{"id": n + 1, "regular": x["regular"]} for n, x in enumerate(sample)]
    return out, rows, key


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("folder", type=Path)
    ap.add_argument("--home", type=Path, required=True, help="local work folder for the labelling sample (never published)")
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--out", type=Path, default=Path(__file__).with_name("responses-results.json"))
    ap.add_argument("--exclude", type=Path, default=None, help="an earlier work folder whose sampled repos are skipped")
    ap.add_argument("--stratify", action="store_true", help="draw half the sample from regular responders' comments")
    args = ap.parse_args(argv)
    exclude = {json.loads(x)["repo"] for x in (args.exclude / "responses-sample.jsonl").read_text(encoding="utf-8").splitlines()
               if x.strip()} if args.exclude else None
    out, rows, key = run(args.folder, args.seed, exclude, args.stratify)
    out["generated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    args.out.write_text(json.dumps(out, indent=1, sort_keys=True), encoding="utf-8")
    args.home.mkdir(parents=True, exist_ok=True)
    with (args.home / "responses-sample.jsonl").open("w", encoding="utf-8") as f:
        f.writelines(json.dumps(r) + "\n" for r in rows)
    with (args.home / "responses-key.jsonl").open("w", encoding="utf-8") as f:
        f.writelines(json.dumps(r) + "\n" for r in key)
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
