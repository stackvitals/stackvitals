from collections import defaultdict
from functools import lru_cache
from datetime import datetime, timedelta

from stackvitals import codeowners
from stackvitals.core.actors import People
from stackvitals.flow.analyze import _human_reviews, _iso, _median, _secs, _t, is_bot

HALF_LIFE_DAYS = 180
SINGLE_OWNER = 0.8
LOAD_SCALE = 4
# CODEOWNERS only nudges: on home-assistant a full boost cut hits from 46% to 41%, a quarter cost nothing.
OWNER_BOOST = 0.25
# Who reviewed this author's earlier PRs counts too: with it, a real reviewer was in the top 3 for 79.3% of 555 held-out
# PRs, against 77.5% without and 73.0% for the busiest reviewers (bench/accuracy/team).
PAIR_WEIGHT = 1.0
REVERT_WINDOW = timedelta(days=7)
# Lock files change with every dependency bump; they say nothing about who knows the code.
LOCK_FILES = {"Cargo.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "uv.lock", "go.sum",
              "Gemfile.lock", "composer.lock", "Pipfile.lock", "bun.lockb", "flake.lock", "mix.lock", "pubspec.lock"}


def _areas(paths: list[str] | None) -> set[str]:
    return {area(path) for path in paths or [] if path.rsplit("/", 1)[-1] not in LOCK_FILES}


def area(path: str) -> str:
    """A path's area: its first two folders ("src/db"), its folder, or "(root)"."""
    parts = path.split("/")
    if len(parts) == 1:
        return "(root)"
    return parts[0] if len(parts) == 2 else "/".join(parts[:2])


class Expertise(dict):
    """Area -> {login: weight}, plus how many PRs each person wrote and reviewed there."""

    def __init__(self):
        super().__init__()
        self.authored = defaultdict(lambda: defaultdict(int))
        self.reviewed = defaultdict(lambda: defaultdict(int))
        # People who can review here: seen as owner, member or collaborator.
        self.insiders = set()
        # Author -> {reviewer: merged PRs of theirs that person reviewed}.
        self.pairs = defaultdict(lambda: defaultdict(int))


def _merged_humans(prs: list[dict], now: datetime, days: int = 365, before: str | None = None) -> list[dict]:
    since = _iso(now - timedelta(days=days))
    return [p for p in prs if p.get("mg") and p["mg"] >= since and not is_bot(p) and (before is None or p["mg"] < before)]


def expertise(prs: list[dict], now: datetime, before: str | None = None, people: People | None = None) -> Expertise:
    """Who knows each area: authors and maintainer reviewers of merged PRs, recent work counting more."""
    ex = Expertise()
    if people is None:
        people = People(prs)
    for p in _merged_humans(prs, now, before=before):
        age = (now - _t(p["mg"])).total_seconds() / 86400
        w = 0.5 ** (age / HALF_LIFE_DAYS)
        reviewers = {e[2] for e in _human_reviews(p) if people.is_insider(e[2])}
        ex.insiders |= reviewers | ({p["au"]} if people.is_insider(p.get("au")) else set())
        for r in reviewers:
            ex.pairs[p["au"]][r] += 1
        for a in _areas(p.get("paths")):
            known = ex.setdefault(a, {})
            known[p["au"]] = known.get(p["au"], 0.0) + w
            ex.authored[a][p["au"]] += 1
            for r in reviewers:
                known[r] = known.get(r, 0.0) + 0.5 * w
                ex.reviewed[a][r] += 1
    return ex


@lru_cache(maxsize=16)
def _rules(text: str | None) -> list:
    return codeowners.parse(text)


def codeowners_for(path: str, text: str | None) -> list[str]:
    """Owners of a path from CODEOWNERS text, matched like GitHub (shared matcher), without the "@"."""
    return [w.lstrip("@") for w in codeowners.owners_for(path, _rules(text))]


def suggest_reviewers(pr: dict, ex: Expertise, load: dict[str, int], owners: dict[str, list[str]],
                      speed: dict[str, float] | None = None, k: int = 3) -> list[dict]:
    """Up to k people for a PR: who knows its areas, plus code owners, eased off by how busy they are.
    Answer speed only counts in private views (speed given)."""
    areas = _areas(pr.get("paths"))
    score = defaultdict(float)
    for a in areas:
        for who, w in ex.get(a, {}).items():
            score[who] += w
    top = max(score.values(), default=1.0)
    owned = {o for path in pr.get("paths") or [] for o in owners.get(path, [])}
    for o in owned:
        score[o] += OWNER_BOOST * top
    paired = {r: n for r, n in ex.pairs.get(pr.get("au"), {}).items() if r != pr.get("au")}
    for r, n in paired.items():
        score[r] += PAIR_WEIGHT * top * n / sum(paired.values())
    out = []
    for who, s in score.items():
        if who == pr.get("au") or (who or "").endswith("[bot]") or (who not in ex.insiders and who not in owned):
            continue
        busy = load.get(who, 0)
        s = s / (1 + busy / LOAD_SCALE)
        if speed and who in speed and speed[who] is not None:
            s = s / (1 + speed[who] / (2 * 86400))
        wrote = sum(ex.authored[a].get(who, 0) for a in areas)
        reviewed = sum(ex.reviewed[a].get(who, 0) for a in areas)
        why = []
        if wrote or reviewed:
            why.append(f"wrote {wrote} and reviewed {reviewed} merged PRs in {', '.join(sorted(areas))}")
        if who in owned:
            why.append("code owner")
        if paired.get(who):
            why.append(f"reviewed {paired[who]} of this author's merged PRs")
        if busy:
            why.append(f"{busy} open review requests")
        if speed and speed.get(who) is not None:
            hours = speed[who] / 3600
            why.append(f"usually answers in {hours:.0f}h" if hours >= 1 else "usually answers in under an hour")
        out.append({"login": who, "score": round(s, 3), "why": "; ".join(why)})
    return sorted(out, key=lambda x: -x["score"])[:k]


def knowledge_map(prs: list[dict], now: datetime) -> dict:
    """Per area: its main author and their share, one-person areas, owners gone quiet, and recent hotspots."""
    merged = _merged_humans(prs, now)
    ex = expertise(prs, now)
    last_seen = {}
    for p in merged:
        last_seen[p["au"]] = max(last_seen.get(p["au"], ""), p["mg"])
    recent = _iso(now - timedelta(days=90))
    # Busy = how many merged PRs touched the area lately (line counts per file aren't collected).
    busy, counts = defaultdict(int), defaultdict(int)
    for p in merged:
        for a in _areas(p.get("paths")):
            counts[a] += 1
            if p["mg"] >= recent:
                busy[a] += 1
    areas = []
    for a, people in ex.items():
        authors = {who: w for who, w in people.items() if ex.authored[a].get(who)}
        if not authors:
            continue
        owner = max(authors, key=authors.get)
        share = authors[owner] / sum(authors.values())
        quiet = (now - _t(last_seen[owner])).days if owner in last_seen else None
        areas.append({"area": a, "prs": counts[a], "owner": owner, "share": round(share, 3),
                      "single_owner": share >= SINGLE_OWNER and counts[a] >= 3, "owner_quiet_days": quiet})
    areas.sort(key=lambda x: -x["prs"])
    hotspots = sorted(({"area": a, "prs_90d": c, "prs": counts[a]} for a, c in busy.items()), key=lambda x: -x["prs_90d"])
    return {"areas": areas, "hotspots": hotspots[:10]}


def _is_revert(p: dict) -> bool:
    title, head = (p.get("ti") or "").lower(), (p.get("head") or "").lower()
    return title.startswith('revert "') or head.startswith("revert-") or "hotfix" in title or "hotfix" in head


def delivery(prs: list[dict], releases: list[dict], now: datetime, window_days: int = 90) -> dict:
    """Release frequency, merge-to-release time and a revert/hotfix-based change failure share (a labelled proxy)."""
    since = _iso(now - timedelta(days=window_days))
    rel = sorted((r for r in releases if not r.get("pre") and r.get("at") and r["at"] >= since), key=lambda r: r["at"])
    merged = [p for p in _merged_humans(prs, now, days=window_days)]
    if not rel:
        return {"source": "merges", "releases": 0, "per_week": round(len(merged) / (window_days / 7), 2),
                "lead_time_median_s": None, "change_fail": None, "recovery_median_s": None}
    leads = []
    for p in merged:
        after = [r["at"] for r in rel if r["at"] >= p["mg"]]
        if after:
            leads.append(_secs(p["mg"], after[0]))
    reverts = sorted(p["mg"] for p in merged if _is_revert(p))
    failed, recovery = 0, []
    for i, r in enumerate(rel):
        nxt = rel[i + 1]["at"] if i + 1 < len(rel) else None
        limit = min(filter(None, [nxt, _iso(_t(r["at"]) + REVERT_WINDOW)]))
        if any(r["at"] <= x < limit for x in reverts):
            failed += 1
            if nxt:
                recovery.append(_secs(r["at"], nxt))
    return {"source": "releases", "releases": len(rel), "per_week": round(len(rel) / (window_days / 7), 2),
            "lead_time_median_s": _median([x for x in leads if x is not None]),
            "change_fail": {"failed": failed, "of": len(rel), "rate": round(failed / len(rel), 4), "proxy": True},
            "recovery_median_s": _median([x for x in recovery if x is not None])}


def backtest(prs: list[dict], now: datetime, last: int = 50) -> dict:
    """For recent reviewed PRs, using only what was known before each opened: was a real reviewer in our top 3?"""
    people = People(prs)
    candidates = sorted((p for p in _merged_humans(prs, now)
                         if p.get("paths") and {e[2] for e in _human_reviews(p) if people.is_insider(e[2])}),
                        key=lambda p: p["mg"])[-last:]
    hits = 0
    for p in candidates:
        ex = expertise(prs, now, before=p["cr"], people=people)
        top = {s["login"] for s in suggest_reviewers(p, ex, load={}, owners={})}
        if top & {e[2] for e in _human_reviews(p) if people.is_insider(e[2])}:
            hits += 1
    return {"checked": len(candidates), "hits": hits, "rate": round(hits / len(candidates), 3) if candidates else None}
