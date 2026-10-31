"""Where contributors come from and drop out: first answers, the newcomer funnel, newcomers still waiting, star growth and
traffic, with the same definitions as the crawl benchmarks so the peer comparison is fair."""
from collections import Counter
from datetime import datetime, timedelta

from mergescout.bench.ci import tier
from mergescout.bench.stars import star_stats
from stackvitals.ci.bench import RANKS, _about, _label, _rank
from stackvitals.core import changes, stats
from stackvitals.core.actors import INSIDER_ASSOC, People, kind_of
from stackvitals.core.time import iso as _iso
from stackvitals.core.time import parse as _dt

INSIDERS = INSIDER_ASSOC
DAY = timedelta(days=1)
HISTORY_DAYS = 60  # a repo's first 60 days of history can't tell a newcomer from someone who came before
RETURN_DAYS = 90
MIN_PRS = 10
MIN_NEWCOMERS = 10
BURST = 20
DEPENDENCY_DAYS, MIN_MERGED, MIN_TENURE = 180, 20, 10  # who carries the work; tenure groups need 10
# Regular responders, checked against labelled crawl comments (bench/accuracy/community).
RESPONDER_ISSUES, RESPONDER_REVIEWS, RESPONDER_DAYS = 10, 2, 360
# Only these associations can be a first contribution; CONTRIBUTOR means earlier commits, even before our history.
FIRST_TIMERS = {"NONE", "FIRST_TIMER", "FIRST_TIME_CONTRIBUTOR", None}
# The facts behind the score: lower is better for waits, higher for the shares.
SCORE_FACTS = [("first_answer_hours", "First answer to outside PRs", "hours", -1),
               ("newcomer_answered_share", "Newcomers answered within 2 weeks", "share", 1),
               ("newcomer_return_rate", "Newcomers who come back within 90 days", "share", 1)]


def _hours(a: str, b: str) -> float:
    # Signed: callers compare orderings themselves.
    return (_dt(b) - _dt(a)).total_seconds() / 3600


def _median(values: list[float]) -> float | None:
    m = stats.median(values)
    return None if m is None else round(m, 2)


def _human(login: str | None, typ: str | None) -> bool:
    return kind_of(login, typ) == "person"


def insiders(prs: list[dict], issues: list[dict]) -> set[str]:
    """Maintainers by the shared rule: a listed role anywhere, or anyone who merged a PR (private org members show as
    CONTRIBUTOR; pipx's main merger did); bots and agents never."""
    return People(prs, issues).insiders()


def regular_responders(prs: list[dict], issues: list[dict], ins: set | frozenset, now: datetime) -> set[str]:
    """People without a listed role who answer others: comments on 10+ other people's issues, or the first review on 2+
    other people's PRs, in the last 360 days (triagers and private org members show as CONTRIBUTOR)."""
    since = _iso(now - timedelta(days=RESPONDER_DAYS))
    on, first = Counter(), Counter()
    for r in issues:
        on.update({c[1] for c in r.get("cm") or [] if len(c) > 3 and c[0] and c[0] >= since and c[1] != r.get("au")
                   and _human(c[1], c[3])})
    for r in prs:
        got = min(((e[1], e[2]) for e in r.get("ev") or [] if e[0] == "review" and len(e) > 5 and e[1] and e[2]
                   and e[2] != r.get("au") and e[3] != "PENDING" and _human(e[2], e[5])), default=None)
        if got and got[0] >= since:
            first[got[1]] += 1
    found = {p for p, n in on.items() if n >= RESPONDER_ISSUES} | {p for p, n in first.items() if n >= RESPONDER_REVIEWS}
    return (found | triagers(issues, now)) - set(ins)


def triagers(issues: list[dict], now: datetime) -> set[str]:
    """People who labelled, assigned, marked a duplicate or closed someone else's issue in the last 360 days: GitHub lets
    only people with triage rights do that, so they act for the project whatever role their comments show. On labelled
    public issues this found 8 project answers among 11 comments the regular-responder rule missed (bench/accuracy/community)."""
    since = _iso(now - timedelta(days=RESPONDER_DAYS))
    out = set()
    for r in issues:
        # Each act counts by its own date: [login, when].
        out |= {t[0] for t in r.get("tr") or [] if isinstance(t, (list, tuple)) and len(t) == 2 and (t[1] or "") >= since}
        closer = _closer(r)
        if closer and closer != r.get("au") and not closer.endswith("[bot]") and (r.get("cl") or "") >= since:
            out.add(closer)
    return out


def _for(rec: dict, ins: set, resp: set | None) -> set:
    # Regular responders answer issues and discussions for the project; PRs still need a maintainer, as the crawl
    # benchmarks count them.
    return resp if resp is not None and rec.get("t") in ("issue", "discussion") else ins


def bursts(prs: list[dict], issues: list[dict], ins: set | frozenset = frozenset()) -> set[str]:
    # An outside account opening BURST items on one day is automated (bat: 73 PRs on one day); maintainers do this too.
    days = Counter((r["au"], r["cr"][:10]) for r in prs + issues if r.get("au") and r.get("cr") and r["au"] not in ins
                   and r.get("as") not in INSIDERS)
    return {au for (au, _), n in days.items() if n >= BURST}


def outside(rec: dict, ins: set | frozenset = frozenset(), skip: set | frozenset = frozenset()) -> bool:
    au = rec.get("au")
    return rec.get("as") not in INSIDERS and _human(au, rec.get("at")) and au not in ins and au not in skip


def _closer(rec: dict) -> str | None:
    if rec.get("clb"):
        return rec["clb"]
    closes = sorted((e for e in rec.get("ev") or [] if e[0] == "closed" and len(e) > 2), key=lambda e: e[1])
    return closes[-1][2] if closes else None


def answered_at(rec: dict, ins: set | None = None, comments: bool = True) -> str | None:
    """The first answer: with the maintainers given, a maintainer's review or reply, a merge, or a close by someone other
    than the author. Without them it is the crawl benchmarks' answer: any other person's review, a merge or a close."""
    au, strict = rec.get("au"), ins is not None
    times = [rec.get("mg")]
    # A close counts unless we know the author closed it (records saved before closers were kept count it); a
    # discussion's closer isn't read, so its close never counts.
    if rec.get("cl") and rec.get("t") != "discussion" and not (strict and _closer(rec) == au):
        times.append(rec["cl"])
    for e in rec.get("ev") or []:
        if e[0] == "review" and len(e) > 5 and e[5] == "User" and e[2] and e[2] != au and not e[2].endswith("[bot]") \
                and e[3] != "PENDING" and (not strict or e[2] in ins or e[4] in INSIDERS):
            times.append(e[1])
    if comments:
        for c in rec.get("cm") or []:
            if c[0] and c[1] != au and _human(c[1], c[3]) and (not strict or c[1] in ins or c[2] in INSIDERS):
                times.append(c[0])
    times = [x for x in times if x and x >= (rec.get("cr") or "")]
    return min(times) if times else None


def covered_since(prs: list[dict], issues: list[dict]) -> str | None:
    """How far back the history is complete: items are read when updated in the last 360 days, so an old item updated
    lately doesn't mean everything since it was seen."""
    recs = [r for r in prs + issues if r.get("cr")]
    if not recs:
        return None
    oldest = min(r["cr"] for r in recs)
    first_fetch = min((r["f"] for r in recs if r.get("f")), default=None)
    return max(oldest, _iso(_dt(first_fetch) - timedelta(days=360))) if first_fetch else oldest


def _contributions(prs: list[dict], issues: list[dict], ins=frozenset(), skip=frozenset()) -> dict[str, list[dict]]:
    by = {}
    for r in sorted(prs + issues, key=lambda r: (r.get("cr") or "", r.get("n") or 0)):
        if r.get("cr") and outside(r, ins, skip):
            by.setdefault(r["au"], []).append(r)
    return by


def _came_back(items: list[dict]) -> bool:
    # New work at least a day later: an issue and the PR fixing it minutes apart are one contribution.
    first = items[0]["cr"]
    return any(24 <= _hours(first, r["cr"]) <= RETURN_DAYS * 24 for r in items[1:])


def funnel(prs: list[dict], issues: list[dict], now: datetime, ins: set | None = None) -> dict:
    """First-time contributors of the last year, how many came back within 90 days, regulars and maintainers."""
    ins = insiders(prs, issues) if ins is None else ins
    skip = bursts(prs, issues, ins)
    start = covered_since(prs, issues) or _iso(now)
    new_from = max(_iso(_dt(start) + timedelta(days=HISTORY_DAYS)), _iso(now - timedelta(days=365)))
    judged_until = _iso(now - timedelta(days=RETURN_DAYS))
    newcomers = judged = returned = 0
    quarters = {}
    for login, items in _contributions(prs, issues, ins, skip).items():
        for r in items:
            age = (now - _dt(r["cr"])).days
            if age < 364:
                quarters.setdefault(login, set()).add(age // 91)
        if items[0]["cr"] < new_from:
            continue
        newcomers += 1
        if items[0]["cr"] <= judged_until:
            judged += 1
            returned += _came_back(items)
    year = _iso(now - timedelta(days=365))
    active = set()
    for r in prs + issues:
        if r.get("au") in ins and (r.get("cr") or "") >= year:
            active.add(r["au"])
        active |= {e[2] for e in r.get("ev") or [] if e[0] in ("review", "merged") and len(e) > 2 and e[2] in ins and e[1] >= year}
        active |= {c[1] for c in r.get("cm") or [] if c[1] in ins and c[0] >= year}
    return {"newcomers": newcomers, "judged": judged, "returned": returned,
            "return_rate": round(returned / judged, 4) if judged else None,
            "regulars": sum(1 for q in quarters.values() if len(q) >= 3), "maintainers": len(active)}


def _answers(items: list[dict], ins: set, earlier: int, now: datetime | None = None, resp: set | None = None) -> dict:
    answers = [answered_at(r, _for(r, ins, resp)) for r in items]
    waits = [_hours(r["cr"], a) for r, a in zip(items, answers) if a]
    # Items still waiting count as "not answered after this long" (Kaplan-Meier), so slow repos can't look fast.
    km = None
    if now:
        # An item closed without an answer stops the clock at its close; only open ones are still waiting.
        km = stats.km_median([_hours(r["cr"], a or r.get("cl") or r.get("mg") or _iso(now)) for r, a in zip(items, answers)],
                             [bool(a) for a in answers])
        km["closed_unanswered"] = sum(1 for r, a in zip(items, answers) if not a and (r.get("cl") or r.get("mg")))
        km["waiting"] = sum(1 for r, a in zip(items, answers) if not a and not (r.get("cl") or r.get("mg")))
    return {"items": len(items), "answered": round(len(waits) / len(items), 4) if items else None,
            "median_hours": _median(waits), "km": km,
            "within_1d": round(sum(w <= 24 for w in waits) / len(items), 4) if items else None, "earlier": earlier}


def first_answer(prs: list[dict], issues: list[dict], now: datetime, days: int = 90, ins: set | None = None,
                 resp: set | None = None, discussions: list[dict] | None = None) -> dict:
    """Outside contributors' PRs and issues of the last `days` (at least a day old): how often and how fast the project
    answered (a maintainer, or for issues also a regular responder); automated accounts are left out and counted, and
    the 9 months before say whether outside work stopped."""
    ins = insiders(prs, issues) if ins is None else ins
    resp = set(ins) | regular_responders(prs, issues, ins, now) if resp is None else resp
    skip = bursts(prs, issues, ins)
    lo, hi, year = _iso(now - timedelta(days=days)), _iso(now - DAY), _iso(now - timedelta(days=365))

    def pick(rs):
        return [r for r in rs if outside(r, ins, skip) and lo <= (r.get("cr") or "") < hi and not r.get("draft")]

    def before(rs):
        return sum(1 for r in rs if outside(r, ins, skip) and year <= (r.get("cr") or "") < lo)
    left = [r for r in prs + issues if r.get("au") in skip and lo <= (r.get("cr") or "") < hi]
    return {"days": days, "prs": _answers(pick(prs), ins, before(prs), now),
            "issues": {**_answers(pick(issues), ins, before(issues), now, resp), "responders": len(set(resp) - set(ins))},
            "left_out": {"accounts": len({r["au"] for r in left}), "items": len(left)} if left else None,
            "discussions": _discussions(pick(discussions or []), ins, before(discussions or []), now, resp)}


def _discussions(items: list[dict], ins: set, earlier: int, now: datetime, resp: set) -> dict | None:
    """Outside discussions answered by the project (the issue rule), and how many questions got an accepted answer from
    anyone (a peer's answer still helped the asker)."""
    if not items:
        return None
    asked = [r for r in items if r.get("qa")]
    return {**_answers(items, ins, earlier, now, resp),
            "answer_chosen": round(sum(1 for r in asked if r.get("ans")) / len(asked), 4) if asked else None}


def weekly_changes(prs: list[dict], issues: list[dict], now: datetime, ins: set | None = None,
                   resp: set | None = None) -> list[dict]:
    """This week's first answers to outside contributors against the four weeks before, judged against how much this
    repo's weeks usually swing."""
    ins = insiders(prs, issues) if ins is None else ins
    resp = set(ins) | regular_responders(prs, issues, ins, now) if resp is None else resp
    skip = bursts(prs, issues, ins)
    items = [(r, answered_at(r, _for(r, ins, resp))) for r in prs + issues
             if r.get("cr") and not r.get("draft") and outside(r, ins, skip)]

    def week(t: datetime) -> list[dict]:
        (ws, we), (bs, be) = changes.windows(t)
        # Answers after the week being judged hadn't happened yet then.
        waits = lambda a, b: [_hours(r["cr"], x) for r, x in items if a <= r["cr"] < b and x and x < we]  # noqa: E731
        return [changes.times("community.first_answer", "first answer to outside contributors", waits(ws, we), waits(bs, be),
                              better=-1, unit="h")]
    return changes.annotate(changes.calibrate(week, now))


def quarterly(prs: list[dict], issues: list[dict], now: datetime, count: int = 4, ins: set | None = None,
              resp: set | None = None) -> list[dict]:
    """The last four calendar quarters (this one so far): outside PRs and issues, how fast the project first answered,
    and how many people contributed here for the first time."""
    ins = insiders(prs, issues) if ins is None else ins
    resp = set(ins) | regular_responders(prs, issues, ins, now) if resp is None else resp
    skip = bursts(prs, issues, ins)
    year, q, quarters = now.year, (now.month - 1) // 3, []
    for _ in range(count):
        quarters.append((f"{year} Q{q + 1}", f"{year}-{3 * q + 1:02d}-01T00:00:00Z"))
        year, q = (year, q - 1) if q else (year - 1, 3)
    quarters.reverse()
    label = lambda ts: f"{ts[:4]} Q{(int(ts[5:7]) - 1) // 3 + 1}"  # noqa: E731
    hi, items = _iso(now - DAY), {k: [] for k, _ in quarters}
    for r in prs + issues:
        cr = r.get("cr") or ""
        if cr and cr < hi and not r.get("draft") and outside(r, ins, skip) and label(cr) in items:
            items[label(cr)].append(r)
    new_from = _iso(_dt(covered_since(prs, issues) or _iso(now)) + timedelta(days=HISTORY_DAYS))
    firsts = Counter(label(xs[0]["cr"]) for xs in _contributions(prs, issues, ins, skip).values() if xs[0]["cr"] >= new_from)
    out = []
    for k, start in quarters:
        a = _answers(items[k], ins, 0, resp=resp)
        # Before the history can tell a newcomer from an earlier contributor, the quarter has no newcomer count.
        out.append({"quarter": k, "items": a["items"], "median_hours": a["median_hours"], "within_1d": a["within_1d"],
                    "newcomers": firsts[k] if start >= new_from else None})
    return out


def newcomers_waiting(prs: list[dict], issues: list[dict], now: datetime, ins: set | None = None,
                      resp: set | None = None) -> list[dict]:
    """Open PRs and issues that are someone's first contribution here and that nobody answered for the project, oldest
    first. GitHub's CONTRIBUTOR association marks people who contributed before our history began."""
    ins, out = (insiders(prs, issues) if ins is None else ins), []
    resp = set(ins) | regular_responders(prs, issues, ins, now) if resp is None else resp
    # Only items inside the complete history can be called someone's first, and only threads we see whole are unanswered.
    since = covered_since(prs, issues) or ""
    for login, items in _contributions(prs, issues, ins, bursts(prs, issues, ins)).items():
        first = items[0]
        seen_whole = len(first.get("cm") or []) < 10 and (first.get("cmn") or 0) <= len(first.get("cm") or [])
        if first.get("st") == "OPEN" and not first.get("draft") and first.get("as") in FIRST_TIMERS and first["cr"] >= since \
                and seen_whole and answered_at(first, _for(first, ins, resp)) is None:
            out.append({"kind": first.get("t") or "pr", "n": first["n"], "created": first["cr"],
                        "days": (now - _dt(first["cr"])).days})
    return sorted(out, key=lambda w: w["created"])


def bench_facts(prs: list[dict], now: datetime) -> dict:
    """This repo's community facts with exactly the crawl benchmarks' definitions (PRs only; reviews, merges, closes)."""
    ins = insiders(prs, [])
    skip = bursts(prs, [], ins)
    lo, hi = _iso(now - timedelta(days=90)), _iso(now - DAY)
    recent = [r for r in prs if outside(r, ins, skip) and lo <= (r.get("cr") or "") < hi]
    waits = [(_hours(r["cr"], a) if (a := answered_at(r, comments=False)) else None) for r in recent]
    enough = len(recent) >= MIN_PRS
    new_from = _iso(_dt(covered_since(prs, []) or _iso(now)) + timedelta(days=HISTORY_DAYS))
    seen_until, judged_until = _iso(now - timedelta(days=14)), _iso(now - timedelta(days=RETURN_DAYS + 30))
    firsts = [items for items in _contributions(prs, [], ins, skip).values() if items[0]["cr"] >= new_from]
    seen = [items[0] for items in firsts if items[0]["cr"] <= seen_until]
    judged = [items for items in firsts if items[0]["cr"] <= judged_until]
    answered = [f for f in seen if (a := answered_at(f, comments=False)) and _hours(f["cr"], a) <= 14 * 24]
    back = [items for items in judged if _came_back(items)]
    return {"first_answer_hours": _median([w for w in waits if w is not None]) if enough else None,
            "answered_1d_share": round(sum(1 for w in waits if w is not None and w <= 24) / len(recent), 4) if enough else None,
            "newcomer_answered_share": round(len(answered) / len(seen), 4) if len(seen) >= MIN_NEWCOMERS else None,
            "newcomer_return_rate": round(len(back) / len(judged), 4) if len(judged) >= MIN_NEWCOMERS else None}


def dependency(prs: list[dict], now: datetime, days: int = DEPENDENCY_DAYS) -> dict | None:
    """Who carries the merged work of the last 180 days, without names: how many people, the top person's share and the
    bus factor (CHAOSS: the fewest people behind half of it). Bots and AI agents don't count; None under 20 merged PRs."""
    since = _iso(now - timedelta(days=days))
    counts = Counter(r["au"] for r in prs if r.get("mg") and r["mg"] >= since and _human(r.get("au"), r.get("at")))
    total = sum(counts.values())
    if total < MIN_MERGED:
        return None
    ranked, running, bus = sorted(counts.values(), reverse=True), 0, 0
    for n in ranked:
        running, bus = running + n, bus + 1
        if running * 2 >= total:
            break
    return {"days": days, "merged": total, "people": len(counts), "top_share": round(ranked[0] / total, 4), "bus_factor": bus}


def elephant(prs: list[dict], affiliation: dict[str, str | None], now: datetime, days: int = DEPENDENCY_DAYS) -> dict | None:
    """The organisations behind the merged work (CHAOSS elephant factor: the fewest behind half of it) and their shares;
    work by people with no known organisation is shown as unknown, and no factor is claimed when it is most of it."""
    from stackvitals.community.affiliation import key
    since = _iso(now - timedelta(days=days))
    people = Counter(r["au"] for r in prs if r.get("mg") and r["mg"] >= since and _human(r.get("au"), r.get("at")))
    total = sum(people.values())
    if total < MIN_MERGED:
        return None
    orgs, members = Counter(), Counter()
    for login, n in people.items():
        org = affiliation.get(key(login)) or None
        orgs[org] += n
        members[org] += 1
    unknown = orgs.pop(None, 0)
    known = total - unknown
    factor = None
    if known * 2 > total:
        running = 0
        for factor, (_org, n) in enumerate(orgs.most_common(), 1):
            running += n
            if running * 2 >= known:
                break
    return {"days": days, "merged": total, "people": len(people), "factor": factor,
            "unknown_share": round(unknown / total, 4),
            # Organisations of one person are named together, never alone: a single name would point at that person.
            "orgs": [{"org": o, "prs": n, "share": round(n / total, 4)} for o, n in orgs.most_common() if members[o] > 1][:5]
            + ([{"org": "organisations of one person", "prs": solo, "share": round(solo / total, 4)}]
               if (solo := sum(n for o, n in orgs.items() if members[o] == 1)) else [])}


def cohorts(prs: list[dict], issues: list[dict], now: datetime, ins: set | None = None, months: int = 12) -> dict:
    """Newcomers by the month they first contributed, and how many came back within 90 days and between 90 and 180 days
    (a month too recent to judge says None)."""
    ins = insiders(prs, issues) if ins is None else ins
    first = (now.year * 12 + now.month - 1) - (months - 1)
    keep = {f"{(first + i) // 12:04d}-{(first + i) % 12 + 1:02d}" for i in range(months)}
    # As in the funnel: the first 60 days of known history can't tell a newcomer from someone who came before.
    new_from = _iso(_dt(covered_since(prs, issues) or _iso(now)) + timedelta(days=HISTORY_DAYS))
    out = {}
    for _login, items in _contributions(prs, issues, ins, bursts(prs, issues, ins)).items():
        month = items[0]["cr"][:7]
        if month not in keep or items[0]["cr"] < new_from:
            continue
        c = out.setdefault(month, {"month": month, "newcomers": 0, "back_by_90d": 0, "back_90_180d": 0})
        c["newcomers"] += 1
        later = [_hours(items[0]["cr"], r["cr"]) / 24 for r in items[1:]]
        c["back_by_90d"] += any(1 <= d <= 90 for d in later)
        c["back_90_180d"] += any(90 < d <= 180 for d in later)
    for c in out.values():
        start = _dt(c["month"] + "-01T00:00:00Z")
        # A cohort is judged once its last day is 90 (or 180) days old.
        end = start + timedelta(days=31)
        if now < end + timedelta(days=90):
            c["back_by_90d"] = None
        if now < end + timedelta(days=180):
            c["back_90_180d"] = None
    return {"months": [out[m] for m in sorted(out)]}


def answers_by_tenure(prs: list[dict], issues: list[dict], now: datetime, days: int = 90, ins: set | None = None,
                      resp: set | None = None) -> dict:
    """First answers to outside contributors' PRs and issues of the last `days`, for newcomers (their first contribution
    here) and regulars (they contributed before): how many, the median wait and the share answered within a day."""
    ins = insiders(prs, issues) if ins is None else ins
    resp = set(ins) | regular_responders(prs, issues, ins, now) if resp is None else resp
    skip = bursts(prs, issues, ins)
    lo, hi = _iso(now - timedelta(days=days)), _iso(now - DAY)
    # A repo's first 60 days of history can't tell a newcomer from someone who came before.
    new_from = _iso(_dt(covered_since(prs, issues) or _iso(now)) + timedelta(days=HISTORY_DAYS))
    firsts = {id(items[0]) for items in _contributions(prs, issues, ins, skip).values()}
    waits = {"newcomers": [], "regulars": []}
    for r in prs + issues:
        if not outside(r, ins, skip) or not lo <= (r.get("cr") or "") < hi or r.get("draft"):
            continue
        first = id(r) in firsts
        if first and r["cr"] < new_from:
            continue
        a = answered_at(r, _for(r, ins, resp))
        waits["newcomers" if first else "regulars"].append(_hours(r["cr"], a) if a else None)
    out = {"days": days}
    for group, ws in waits.items():
        got = [w for w in ws if w is not None]
        enough = len(ws) >= MIN_TENURE
        out[group] = {"n": len(ws), "median_h": _median(got) if enough and got else None,
                      "answered_1d_share": round(sum(1 for w in got if w <= 24) / len(ws), 4) if enough else None}
    return out


def peer_range(bench: dict | None, language: str | None, stars: int | None, metric: str) -> dict | None:
    """Similar public repos' typical value and middle half for a metric, shown instead of a rank: counts like the bus
    factor tie too often for a rank to mean much."""
    found = _group(bench, language, stars, metric)
    if not found:
        return None
    key, g = found
    q = g[metric]
    return {"group": _label(key), "repos": q.get("repos") or g.get("repos"), "typical": q["p50"], "low": q["p25"], "high": q["p75"]}


def _ok(q) -> bool:
    return isinstance(q, dict) and all(isinstance(q.get(f"p{int(r * 100)}"), (int, float)) for r in RANKS)


def _group(bench: dict | None, language: str | None, stars: int | None, metric: str) -> tuple[str, dict] | None:
    groups = (bench or {}).get("groups") if isinstance(bench, dict) else None
    if not isinstance(groups, dict):
        return None
    size = tier(stars)
    for key in (f"{language}|{size}", f"{language}|all", f"all|{size}", "all|all"):
        g = groups.get(key)
        if isinstance(g, dict) and _ok(g.get(metric)):
            return key, g
    return None


def score(facts: dict, bench: dict | None, language: str | None, stars: int | None) -> dict | None:
    """0-100: on average, the share of similar repos this one does better than, over the facts it has; each fact is shown,
    a missing one is left out (never scored as zero), and fewer than two facts give no score."""
    found = _group(bench, language, stars, "first_answer_hours") or _group(bench, language, stars, "newcomer_answered_share")
    if not found:
        return None
    key, g = found
    shown, left_out = [], []
    for name, label, kind, better in SCORE_FACTS:
        if facts.get(name) is None or not _ok(g.get(name)):
            left_out.append(name)
            continue
        r = _rank(facts[name], g[name])
        beats = 1 - r if better < 0 else r
        # Whole percents, and the score is exactly their average: anyone can recompute it from the page.
        shown.append({"key": name, "name": label, "kind": kind, "you": facts[name], "typical": g[name]["p50"],
                      "better_than": int(beats * 100 + 0.5)})
    if len(shown) < 2:
        return None
    return {"score": int(sum(f["better_than"] for f in shown) / len(shown) + 0.5), "group": _label(key), "repos": g["repos"],
            "built_at": (bench or {}).get("built_at"), "facts": shown, "left_out": left_out}


def star_trend(weeks: dict, stars: int | None, now: datetime, bench: dict | None = None,
               language: str | None = None) -> dict | None:
    """Weekly stars (GitHub's history, no names), the gain over the last 12 complete weeks and its place among peers."""
    rows = [{"week": int(k), "total": int(v)} for k, v in (weeks or {}).items() if str(k).isdigit()]
    if not rows:
        return None
    series = [[datetime.fromtimestamp(r["week"], now.tzinfo).strftime("%Y-%m-%d"), r["total"]]
              for r in sorted(rows, key=lambda r: r["week"])][-52:]
    out = {"weeks": series, "stars": stars, **(star_stats(rows, stars, now) or {"gained_12w": None, "growth_12w": None})}
    found = _group(bench, language, stars, "growth_12w") if out["growth_12w"] is not None and (stars or 0) >= 100 else None
    if found:
        key, g = found
        r = _rank(out["growth_12w"], g["growth_12w"])
        place = f"above about {_about(r)}%" if r >= 0.5 else f"below about {_about(1 - r)}%"
        out["peers"] = {"group": _label(key), "repos": g["repos"], "place": place,
                        "typical_gain": (g.get("gained_12w") or {}).get("p50")}
    return out


def traffic_summary(traffic: dict, now: datetime, days: int = 90) -> dict | None:
    """Views and clones per day (kept past GitHub's 14 days) and the latest top referrers."""
    if not traffic or not traffic.get("views"):
        return None
    lo = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    pick = lambda key: sorted([d, *v] for d, v in (traffic.get(key) or {}).items() if d >= lo)  # noqa: E731
    views, clones = pick("views"), pick("clones")
    latest = max(traffic.get("referrers") or {"": []}, default="")
    return {"days": days, "since": min(traffic["views"]), "views": views, "clones": clones,
            "views_total": sum(v[1] for v in views), "visitors_total": sum(v[2] for v in views),
            "clones_total": sum(v[1] for v in clones),
            "referrers": (traffic.get("referrers") or {}).get(latest, []), "referrers_day": latest or None}
