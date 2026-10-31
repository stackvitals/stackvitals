import re
from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import datetime, timedelta

from stackvitals.core import metrics
from stackvitals.core.actors import INSIDER_ASSOC, People, kind_of
from stackvitals.core.stats import median as _median
from stackvitals.core.stats import percentile as _pct
from stackvitals.core.time import iso as _iso
from stackvitals.core.time import parse as _t
from stackvitals.core.time import secs as _secs

INSIDERS = INSIDER_ASSOC
FAILING = {"FAILURE", "ERROR"}
STAGES = ("pickup", "review", "merge", "cycle")
# Nothing is "slow" before a day (repos that merge right after approval would flag minutes), and a wait
# beyond 30 days is stale backlog rather than today's work.
SLOW_FLOOR = 24 * 3600
STALE = 30 * 24 * 3600
MIN_BASELINE = 10


def is_bot(p: dict) -> bool:
    # Bots, coding agents and deleted accounts are not people (the crawl's rule).
    return kind_of(p.get("au"), p.get("at")) != "person"


def _human_reviews(p: dict) -> list[list]:
    # GitHub's stage metrics skip bots, the author and Copilot; so do we.
    return [e for e in p["ev"] if e[0] == "review" and e[2] and e[2] != p.get("au") and kind_of(e[2], e[5]) == "person"
            and e[3] != "PENDING"]


def _insider(login: str | None, assoc: str | None, people: People | None) -> bool:
    # With the repo's people known, insiders are found by what they do; without, by GitHub's label alone.
    return people.is_insider(login) if people is not None else assoc in INSIDER_ASSOC


def ready_at(p: dict) -> str | None:
    """When the PR first asked for review: its creation, or leaving draft if it was opened as a draft."""
    toggles = [e for e in p["ev"] if e[0] in ("ready", "draft")]
    if toggles and toggles[0][0] == "ready":
        return toggles[0][1]
    if toggles or not p.get("draft"):
        return p["cr"]
    return None


def stages(p: dict) -> dict:
    ready, merged = ready_at(p), p.get("mg")
    reviews = [e for e in _human_reviews(p) if not merged or e[1] <= merged]
    first = reviews[0][1] if reviews else None
    final = reviews[-1][1] if reviews else None
    return {"ready": ready, "reviewed": bool(reviews),
            "pickup": _secs(ready, first), "review": _secs(first, final) if merged else None,
            "merge": _secs(final, merged), "cycle": _secs(ready, merged)}


def _asks(comment: list) -> bool:
    # Older records have no flag: their comments count as asking, as before.
    return comment[4] if len(comment) > 4 else True


# Bots whose red marks rarely block a merge: performance and coverage reporters.
NOISY = re.compile(r"codspeed|codecov|coverage|benchmark|\bperf\b|performance|sonar|deepsource", re.I)


def _failing_checks(p: dict, shared: set[str]) -> tuple[list[str], list[str]]:
    """Failing checks as (required, other); checks failing on many open PRs at once and noisy bots never count."""
    chk = p.get("chk")
    if not chk:
        return (["checks"] if p.get("ci") in FAILING else []), []
    live = [(name, required) for name, required in chk["failing"] if name not in shared]
    return ([name for name, required in live if required],
            [name for name, required in live if not required and not NOISY.search(name or "")])


# Status labels maintainers set, matched on lower-case names with separators as spaces ("S-waiting-on-author").
AUTHOR_LABEL = re.compile(r"waiting (on|for) (the )?(author|contributor|submitter|op|response|feedback|reporter)"
                          r"|awaiting (author|changes|response|feedback|contributor)|changes requested|pending author"
                          r"|merge conflicts?|has conflicts?"
                          r"|needs? (changes|work|tests?|test coverage|rebase|more info|info|author|update|response|revision)")
CONFLICT_LABEL = re.compile(r"needs? rebase|merge conflicts?|has conflicts?")
READY_LABEL = re.compile(r"ready (to|for) merge|merge ready|waiting (on|for) (the )?(community )?(reviews?|maintainers?|merge)"
                         r"|awaiting (review|merge|maintainers?)|needs? review|ready for review")
# One or two red jobs while a reviewer is asked are often flaky; more than that is the change itself.
BROAD_FAILURE = 3


def _norm(label: str) -> str:
    return " ".join(re.sub(r"[-_:/]+", " ", label.lower()).split())


def _label(p: dict) -> tuple[str, str, str] | None:
    """The newest status label still on the PR, as (author | ready, name, since). The author's turn runs from the first
    such label still on; a review wait from the last status-label change (clippy drops "community reviews" to hand over)."""
    added, changed = {}, ""
    for when, sign, name in p.get("lbe") or []:
        if name and _kind(name):
            changed = max(changed, when)
            if sign == "+":
                added[name] = max(added.get(name, ""), when)
    found = [(added[name], kind, name) for name in p.get("lb") or [] if (kind := _kind(name)) and name in added]
    if not found:
        return None
    when, kind, name = max(found)
    if kind == "author":
        return kind, name, min(w for w, k, _ in found if k == "author")
    return kind, name, max(when, changed)


def _kind(label: str) -> str | None:
    return "author" if AUTHOR_LABEL.search(_norm(label)) else "ready" if READY_LABEL.search(_norm(label)) else None


def _work(p: dict) -> tuple[list[str], list[str]]:
    """The author's new work (own non-merge commits, by authored date) and all their pushes; others' commits don't count."""
    cmt = p.get("cmt")
    if not cmt:
        # Older records know only the last commit, whoever made it.
        return [t for t in [p.get("la") or p.get("lc")] if t], [t for t in [p.get("lc"), p.get("la")] if t]
    mine = [c for c in cmt if c[2] in (p.get("au"), None)]
    return [c[0] for c in mine if not c[3] and c[0]], [c[1] for c in mine if c[1]]


def who_acts_next(p: dict, now: datetime, heads: dict[str, int] | None = None, shared: set[str] | None = None,
                  people: People | None = None) -> dict:
    """Who holds the ball on an open PR, why, and since when (the event that put it there)."""
    w = _decide(p, now, heads, shared, people)
    # A reviewer the repo assigned (rust-clippy's rustbot) is named instead of unnamed maintainers.
    owners = [a for a in p.get("asg") or [] if a != p.get("au")]
    return {**w, "actor": "reviewers", "who": owners} if w["actor"] == "maintainers" and owners else w


def _decide(p: dict, now: datetime, heads: dict[str, int] | None, shared: set[str] | None,
            people: People | None = None) -> dict:
    au = p.get("au")
    parent = (heads or {}).get(p.get("base"))
    if parent and parent != p["n"]:
        # A stacked PR waits for the PR it builds on; that wait is nobody's review delay.
        return {"actor": "nobody", "who": [], "why": f"stacked on #{parent}: waits for it to merge first",
                "since": p["cr"], "step": "stacked"}
    if p.get("draft"):
        since = max([e[1] for e in p["ev"] if e[0] == "draft"] or [p["cr"]])
        return {"actor": "nobody", "who": [au], "why": "draft: the author is still working on it", "since": since,
                "step": "draft"}
    label = _label(p)
    if p.get("mgs") == "CONFLICTING":
        # GitHub keeps no time for a conflict; a "needs rebase" style label set after the last commit dates it better,
        # unless the author already owed work from an earlier point (ansible: changes requested months before the conflict).
        since = max(p.get("lc") or p["up"], label[2] if label and label[0] == "author" else "")
        rest = [x for x in p.get("lb") or [] if not CONFLICT_LABEL.search(_norm(x))]
        before = _decide({**p, "mgs": None, "lb": rest}, now, heads, shared, people)
        if before["actor"] == "author":
            since = min(since, before["since"])
        return {"actor": "author", "who": [au], "why": "has merge conflicts with the base branch", "since": since, "step": "checks"}
    if (p.get("chk") or {}).get("awaiting"):
        return {"actor": "maintainers", "who": [], "why": "CI runs wait for a maintainer to approve them",
                "since": p.get("lc") or p["up"], "step": "pickup"}
    code, pushes = _work(p)
    if label:
        kind, name, when = label
        # A maintainer's status label decides until the author pushes after a "waiting on author" one.
        if kind == "author" and not any(t > when for t in pushes):
            return {"actor": "author", "who": [au], "why": f'labelled "{name}"', "since": when, "step": "author_changes"}
        if kind == "ready":
            return {"actor": "reviewers" if p["rq"] else "maintainers", "who": list(p["rq"]), "why": f'labelled "{name}"',
                    "since": when, "step": "merge" if "merge" in _norm(name) else "pickup"}
    required, other = _failing_checks(p, shared or set())
    # A failing required check is always the author's; others are, unless a reviewer was asked and only one or two fail.
    if required or (other and (not p["rq"] or len(other) >= BROAD_FAILURE)):
        names = required or other
        what = "checks are failing" if names == ["checks"] else f"checks are failing ({', '.join(names[:2])})"
        return {"actor": "author", "who": [au], "why": f"{what} on the latest commit", "since": p.get("lc") or p["up"],
                "step": "checks"}
    # Anyone can press "request changes" on a public repo; only maintainers' reviews decide who holds the ball.
    reviews = [e for e in _human_reviews(p) if _insider(e[2], e[4], people)]
    latest = {}
    for e in reviews:
        if e[3] != "COMMENTED":
            latest[e[2]] = e
    # A formal change request is answered by a reply or new work, judged by when it was written (a rebase keeps that date);
    # a question or comment by any push or reply. The ball moves at the author's first answer, not a later ping.
    replies = [c[0] for c in p["cm"] if c[1] == au]
    activity = sorted(replies + pushes + code)
    blocking = sorted((e for e in latest.values() if e[3] == "CHANGES_REQUESTED"), key=lambda e: e[1])
    if blocking:
        names = [e[2] for e in blocking]
        answers = sorted(t for t in replies + code if t > blocking[-1][1])
        if answers:
            return {"actor": "reviewers", "who": names, "why": f"the author updated it after changes requested by {', '.join(names)}",
                    "since": answers[0], "step": "rereview"}
        return {"actor": "author", "who": [au], "why": f"changes requested by {', '.join(names)}", "since": blocking[-1][1],
                "step": "author_changes"}
    if p["rq"]:
        # Each reviewer's latest request counts: a re-request restarts their clock.
        latest_ask = [max(e[1] for e in p["ev"] if e[0] == "req" and e[2] == who) for who in p["rq"]
                      if any(e[0] == "req" and e[2] == who for e in p["ev"])]
        return {"actor": "reviewers", "who": list(p["rq"]), "why": "review requested",
                "since": min(latest_ask) if latest_ask else ready_at(p) or p["cr"], "step": "rereview" if reviews else "pickup"}
    approvals = [e for e in latest.values() if e[3] == "APPROVED"]
    if approvals:
        last = max(approvals, key=lambda e: e[1])
        # A maintainer's later comment-only review that raised points reopens it until new code arrives (older records lack the flag).
        raised = [e for e in reviews if e[3] == "COMMENTED" and len(e) > 6 and e[6] and e[1] > last[1]]
        if raised:
            r = raised[-1]
            later = sorted(t for t in code if t > r[1])
            if later:
                return {"actor": "reviewers", "who": [r[2]], "why": f"the author updated it after {r[2]}'s review",
                        "since": later[0], "step": "rereview"}
            return {"actor": "author", "who": [au], "why": f"{r[2]} raised points after the approval", "since": r[1],
                    "step": "author_changes"}
        if _insider(au, p.get("as"), people):
            return {"actor": "author", "who": [au], "why": f"approved by {last[2]}; the author (a maintainer) can merge it",
                    "since": last[1], "step": "merge"}
        return {"actor": "maintainers", "who": [], "why": f"approved by {last[2]}, waiting to be merged", "since": last[1],
                "step": "merge"}
    asked = [c[0] for c in p["cm"] if _insider(c[1], c[2], people) and c[1] != au and _asks(c)] + [e[1] for e in reviews]
    spoke = [c[0] for c in p["cm"] if _insider(c[1], c[2], people) and c[1] != au] + [e[1] for e in reviews]
    if asked and max(asked) > (activity[-1] if activity else ""):
        return {"actor": "author", "who": [au], "why": "a maintainer asked something", "since": max(asked), "step": "author_reply"}
    after = [t for t in activity if spoke and t > max(spoke)]
    if after:
        return {"actor": "maintainers", "who": [], "why": "the author replied", "since": after[0], "step": "maintainer_reply"}
    if spoke:
        return {"actor": "maintainers", "who": [], "why": "a maintainer commented but nobody reviewed yet", "since": max(spoke),
                "step": "pickup"}
    return {"actor": "maintainers", "who": [], "why": "ready, but nobody was asked to review", "since": ready_at(p) or p["cr"],
            "step": "pickup"}


def _author_responses(p: dict) -> list[float]:
    # How long authors take to answer a change request: the next commit or comment after it.
    au, out = p.get("au"), []
    acts = sorted([c[0] for c in p["cm"] if c[1] == au] + ([p["lc"]] if p.get("lc") else []))
    for e in _human_reviews(p):
        if e[3] == "CHANGES_REQUESTED":
            later = [a for a in acts if a > e[1]]
            if later:
                out.append(_secs(e[1], later[0]))
    return [x for x in out if x is not None]


def _baselines(prs: list[dict]) -> dict:
    st = [stages(p) for p in prs if p.get("mg")]
    values = {"pickup": [s["pickup"] for s in st if s["pickup"] is not None],
              "merge": [s["merge"] for s in st if s["merge"] is not None],
              "author": [x for p in prs for x in _author_responses(p)]}
    return {**{k: _pct(v, 0.75) for k, v in values.items()}, "n": {k: len(v) for k, v in values.items()}}


def _summary(values: list[float]) -> dict:
    return {"median_s": _median(values), "p90_s": _pct(values, 0.9), "n": len(values)}


def _measures(all_stages: list[dict], outsider: list[dict], humans_open: list[dict], now: datetime, window_days: int) -> dict:
    # The registry's view of the same numbers: id, version, n, range and as-of, for every surface and the benchmarks.
    def pick(name):
        return [s[name] for s in all_stages if s[name] is not None]
    found = [metrics.measure("flow.pickup_time", values=pick("pickup"), as_of=now, window_days=window_days),
             metrics.measure("flow.cycle_time", values=pick("cycle"), as_of=now, window_days=window_days),
             metrics.measure("flow.outsider_merge_rate", hits=sum(1 for p in outsider if p.get("mg")), n=len(outsider),
                             as_of=now, window_days=window_days),
             metrics.measure("flow.open_prs", n=len(humans_open), as_of=now)]
    return {m.metric: m.to_dict() for m in found}


def _group(prs: list[dict]) -> dict:
    merged = [p for p in prs if p.get("mg")]
    unmerged = [p for p in prs if not p.get("mg")]
    st = [stages(p) for p in merged]
    out = {"merged": len(merged), "closed_unmerged": len(unmerged),
           "merge_rate": round(len(merged) / len(prs), 4) if prs else None,
           "merged_without_review": sum(not s["reviewed"] for s in st)}
    for name in STAGES:
        out[name] = _summary([s[name] for s in st if s[name] is not None])
    return out


SHARED_WINDOW = timedelta(days=7)
SHARED_NEAREST = 6


def _broken(name: str, group: list[tuple]) -> bool:
    # Failing for 3+ different authors and on 80%+ of the PRs that ran it; one person's repeated slip stays theirs.
    failing = [au for _, failed, au in group if name in failed]
    return len(set(failing)) >= 3 and len(failing) / max(len(group), 1) >= 0.8


def _nearest(runs: list[tuple], times: list[datetime], t: datetime, k: int) -> list[tuple]:
    # The k runs closest in time to t, from a time-sorted list and its times.
    i = bisect_left(times, t)
    lo, hi, out = i - 1, i, []
    while len(out) < k and (lo >= 0 or hi < len(runs)):
        if hi < len(runs) and (lo < 0 or runs[hi][0] - t <= t - runs[lo][0]):
            out.append(runs[hi])
            hi += 1
        else:
            out.append(runs[lo])
            lo -= 1
    return out


def _shared_breakage(prs: list[dict]) -> dict[int, set[str]]:
    """Per PR, failing checks that were broken for everyone when its checks ran: judged among PRs that ran the same check,
    pushed within 7 days of it or, in a quiet repo, the 6 pushed closest to it; never on today's PRs alone."""
    by_check, mine = defaultdict(list), []
    for p in prs:
        chk = p.get("chk")
        if chk:
            t, failed = _t(p.get("lc") or p["up"]), {name for name, _ in chk.get("failing", [])}
            mine.append((p["n"], t, failed))
            for name in set(chk.get("ran") or failed) | failed:
                by_check[name].append((t, failed, p.get("au")))
    for runs in by_check.values():
        runs.sort(key=lambda r: r[0])
    # Times per check, built once: big repos have hundreds of open PRs with dozens of jobs each.
    times = {name: [r[0] for r in runs] for name, runs in by_check.items()}
    out = {}
    for n, t, failed in mine:
        out[n] = set()
        for name in failed:
            runs, ts = by_check[name], times[name]
            week = runs[bisect_left(ts, t - SHARED_WINDOW):bisect_right(ts, t + SHARED_WINDOW)]
            if _broken(name, week) or _broken(name, _nearest(runs, ts, t, SHARED_NEAREST)):
                out[n].add(name)
    return out


BASELINE_STEPS = {"pickup": "pickup", "rereview": "pickup", "merge": "merge", "author_changes": "author",
                  "author_reply": "author", "checks": "author", "maintainer_reply": "pickup"}


def analyze(data: dict, now: datetime, window_days: int = 90, people_speed: bool = False, owner: str | None = None,
            people: People | None = None) -> dict:
    """Review flow of the last `window_days`, the open-PR queue and review load; people's speed only when asked."""
    since = _iso(now - timedelta(days=window_days))
    if people is None:
        people = People(data["open"] + data["closed"])
    humans_open = [p for p in data["open"] if not is_bot(p)]
    closed = [p for p in data["closed"] if (p.get("cl") or "") >= since]
    humans_closed = [p for p in closed if not is_bot(p)]
    insider = [p for p in humans_closed if people.is_insider(p.get("au"))]
    outsider = [p for p in humans_closed if not people.is_insider(p.get("au"))]
    all_stages = [stages(p) for p in humans_closed if p.get("mg")]
    baselines = _baselines(humans_closed)
    # Outsiders' PRs usually wait longer; each PR is compared with its own group when there's enough history.
    by_group = {"insider": _baselines(insider), "outsider": _baselines(outsider)}
    # Branches of open PRs in this repo itself, to spot PRs stacked on another one.
    heads = {p["head"]: p["n"] for p in data["open"] if owner and p.get("ho") == owner and p.get("head")}
    shared = _shared_breakage(humans_open)
    queue = []
    for p in humans_open:
        w = who_acts_next(p, now, heads, shared.get(p["n"]), people)
        if w["actor"] == "nobody":
            continue
        waited = _secs(w["since"], _iso(now)) or 0.0
        step = BASELINE_STEPS.get(w["step"], "pickup")
        group = "insider" if people.is_insider(p.get("au")) else "outsider"
        base = by_group[group][step] if by_group[group]["n"][step] >= MIN_BASELINE else baselines[step]
        queue.append({"n": p["n"], "title": p.get("ti"), "author": p.get("au"), "outsider": group == "outsider",
                      **w, "waiting_s": waited, "usual_s": base, "stale": waited > STALE,
                      "slow": bool(base is not None and waited > max(base, SLOW_FLOOR))})
    # Today's work first: overdue PRs, then the rest by wait; stale backlog last.
    queue.sort(key=lambda q: (q["stale"], not q["slow"], -q["waiting_s"]))
    load = defaultdict(list)
    for p in humans_open:
        if p.get("draft"):
            continue
        for who in p["rq"]:
            asked = [e[1] for e in p["ev"] if e[0] == "req" and e[2] == who]
            load[who].append(min(asked) if asked else ready_at(p) or p["cr"])
    monthly = defaultdict(lambda: {"opened": 0, "merged": 0, "pickup": [], "cycle": []})
    for p in [*humans_open, *[p for p in data["closed"] if not is_bot(p)]]:
        if p["cr"] >= _iso(now - timedelta(days=365)):
            monthly[p["cr"][:7]]["opened"] += 1
        if p.get("mg") and p["mg"] >= _iso(now - timedelta(days=365)):
            m = monthly[p["mg"][:7]]
            m["merged"] += 1
            if (s := stages(p))["pickup"] is not None:
                m["pickup"].append(s["pickup"])
            if s["cycle"] is not None:
                m["cycle"].append(s["cycle"])
    out = {"generated": _iso(now), "window_days": window_days,
           "open": len(humans_open), "drafts": sum(1 for p in humans_open if p.get("draft")),
           "merged": len(all_stages), "closed_unmerged": sum(1 for p in humans_closed if not p.get("mg")),
           "stages": {name: _summary([s[name] for s in all_stages if s[name] is not None]) for name in STAGES},
           "merged_without_review": sum(not s["reviewed"] for s in all_stages),
           "groups": {"insider": _group(insider), "outsider": _group(outsider)},
           "baselines": {k: v for k, v in baselines.items() if k != "n"}, "queue": queue,
           "stale": sum(q["stale"] for q in queue),
           "load": sorted(({"reviewer": who, "open_requests": len(ts), "oldest_since": min(ts)} for who, ts in load.items()),
                          key=lambda r: (-r["open_requests"], r["oldest_since"])),
           "monthly": [{"month": k, "opened": v["opened"], "merged": v["merged"], "pickup_median_s": _median(v["pickup"]),
                        "cycle_median_s": _median(v["cycle"])}
                       for k, v in sorted(monthly.items())],
           "bots": {"open": len(data["open"]) - len(humans_open), "closed": len(closed) - len(humans_closed)},
           "measures": _measures(all_stages, outsider, humans_open, now, window_days)}
    if people_speed:
        out["responders"] = _responders([*humans_open, *humans_closed])
    return out


def _responders(prs: list[dict]) -> list[dict]:
    # Each reviewer's own answer time, from being asked (or the PR being ready) to their first review after it.
    waits = defaultdict(list)
    for p in prs:
        ready = ready_at(p)
        for who in {e[2] for e in _human_reviews(p)}:
            asked = [e[1] for e in p["ev"] if e[0] == "req" and e[2] == who]
            start = min(asked) if asked else ready
            after = [e[1] for e in _human_reviews(p) if e[2] == who and start and e[1] >= start]
            if start and after:
                waits[who].append(_secs(start, after[0]))
    return sorted(({"reviewer": who, "median_s": _median([w for w in ws if w is not None]), "n": len(ws)}
                   for who, ws in waits.items()), key=lambda r: -r["n"])
