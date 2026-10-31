"""What AI-assisted work does to a repo, month by month: coding agents' PRs, people's PRs with an AI marker and the rest
side by side on review wait, size, CI failures, reverts and failed deployments; each AI kind compared like with like
(the same authors' other PRs, or people's PRs of the same month and size) with the gap it could detect; and DORA's
fifth metric, deployment rework rate."""
import math
import re
from collections import Counter, defaultdict
from datetime import datetime

from stackvitals.core.actors import kind_of
from stackvitals.core.joins import runs_by_pr
from stackvitals.core.stats import mh_risk_difference, wilson
from stackvitals.core.time import iso

# Labels coding tools put on the PRs they helped with (Claude Code adds claude-code-assisted).
AI_LABELS = {"claude-code-assisted": "claude", "ai-assisted": "ai", "ai-generated": "ai", "copilot": "copilot", "cursor": "cursor",
             "codex": "codex", "devin": "devin"}
AGENTS = ("copilot", "devin", "claude", "cursor", "codex", "openhands", "sweep")
MONTHS = 6
BATCH_MAX = 5
MIN_N = 10  # fewer PRs on a side and its numbers are left out (its count stays)
# The branches cloud agents open PRs from (AIDev's public rule), whoever's account opens them.
AGENT_BRANCH = re.compile(r"^(copilot|codex|cursor|devin|claude)[/-]", re.I)
MIN_MATCHED = 5  # fewer matched PRs and a comparison says nothing
SIDES = {"agent": "agent", "assisted": "assisted", "person": "others"}
KEYS = ("pickup_p75_h", "review_p75_h", "size_p75", "ci_n", "ci_failed_share", "flaky_share", "reverted_share",
        "failed_deploy_share")


def assisted_by(p: dict) -> list[str]:
    """The tools that helped with a PR: commit trailers, labels, or a coding agent as its author."""
    tools = set(p.get("ai") or [])
    # "AI Generated" and "ai_generated" are the same label as ai-generated.
    marks = {x.lower().replace(" ", "-").replace("_", "-") for x in p.get("lb") or []}
    tools |= {AI_LABELS[x] for x in marks if x in AI_LABELS}
    login = (p.get("au") or "").lower()
    branch = AGENT_BRANCH.match(p.get("head") or "")
    if branch:
        tools.add(f"{branch.group(1).lower()} agent")
    if kind_of(p.get("au"), p.get("at")) == "agent":
        tools.add(f"{next((a for a in AGENTS if a in login), 'coding')} agent")
    return sorted(tools)


def mode(p: dict) -> str:
    """'agent' (a coding agent opened it: its account, or an agent's branch such as codex/), 'assisted' (a person's PR
    with an AI marker: a trailer or a label), or 'person'."""
    if kind_of(p.get("au"), p.get("at")) == "agent" or AGENT_BRANCH.match(p.get("head") or ""):
        return "agent"
    return "assisted" if assisted_by(p) else "person"


def _band(p: dict) -> int:
    return int(math.log2((p.get("add") or 0) + (p.get("del") or 0) + 1))


def _merger(p: dict) -> str | None:
    return next((e[2] for e in p.get("ev") or [] if e and e[0] == "merged" and len(e) > 2), None)


def matched(treated: list, control: list, key, hit) -> dict:
    """A share compared within matched groups (Mantel-Haenszel with Sato's variance): the gap with its 95% range, the gap
    it could detect (80% power), how many treated items found a match, and a plain verdict."""
    groups = defaultdict(lambda: [0, 0, 0, 0])
    for x in treated:
        g = groups[key(x)]
        g[0], g[1] = g[0] + hit(x), g[1] + 1
    for x in control:
        if (k := key(x)) in groups:
            groups[k][2], groups[k][3] = groups[k][2] + hit(x), groups[k][3] + 1
    used = [tuple(g) for g in groups.values() if g[1] and g[3]]
    n = sum(g[1] for g in used)
    out = {"matched": n, "of": len(treated), "matched_share": round(n / len(treated), 4) if treated else None}
    if n < MIN_MATCHED:
        return {**out, "gap": None, "verdict": "too few"}
    rd, se = mh_risk_difference(used)
    weight = sum(g[1] * g[3] / (g[1] + g[3]) for g in used)
    total = sum(g[1] + g[3] for g in used)
    # What it could detect is judged with no gap (a pooled share), so a rare outcome never claims a zero-point reach.
    pooled = min(max(sum(g[0] + g[2] for g in used) / total, 1 / total), 1 - 1 / total)
    null_se = math.sqrt(pooled * (1 - pooled) / weight)
    # Sato's variance is zero when every pair goes the same way; the no-gap error keeps the range honest then.
    se = se or null_se
    low, high = max(-1.0, rd - 1.96 * se), min(1.0, rd + 1.96 * se)
    verdict = "higher" if low > 0 else "lower" if high < 0 else "no measurable difference"
    return {**out, "gap": round(rd, 4), "low": round(low, 4), "high": round(high, 4),
            "detectable": round(2.8 * null_se, 4), "verdict": verdict}


# Greedy to the last quote, and open at the end: 'Revert "X" because it broke CI' counts too.
REVERT_TITLE = re.compile(r'^Revert "(.*)"')
REVERT_NUMBER = re.compile(r"^Revert\s+#(\d+)\b", re.I)
SQUASH_SUFFIX = re.compile(r"\s*\(#(\d+)\)\s*$")


def is_revert(p: dict) -> bool:
    title = p.get("ti") or ""
    return bool(REVERT_TITLE.match(title) or REVERT_NUMBER.match(title))


def revert_target(p: dict, by_number: dict[int, dict]) -> int | None:
    """The PR a revert undid: the number in a squash-merge suffix ("Title (#12)") or "Revert #12", else the PR with that
    title merged latest before the revert (so a re-landed PR with the same title is never marked)."""
    title = p.get("ti") or ""
    found = REVERT_NUMBER.match(title)
    if found:
        return int(found.group(1)) if int(found.group(1)) in by_number else None
    found = REVERT_TITLE.match(title)
    if not found:
        return None
    inner = found.group(1)
    suffix = SQUASH_SUFFIX.search(inner)
    if suffix and int(suffix.group(1)) in by_number:
        return int(suffix.group(1))
    bare = SQUASH_SUFFIX.sub("", inner)
    earlier = [q for q in by_number.values() if q["n"] != p["n"] and q.get("mg") and q["mg"] <= (p.get("mg") or "~")
               and SQUASH_SUFFIX.sub("", q.get("ti") or "") == bare]
    return max(earlier, key=lambda q: q["mg"])["n"] if earlier else None


def _p75(values) -> float | None:
    v = sorted(x for x in values if x is not None)
    return round(v[min(len(v) - 1, int(0.75 * (len(v) - 1) + 0.5))], 2) if v else None


def _share(rows, hit) -> float | None:
    return round(sum(1 for r in rows if hit(r)) / len(rows), 4) if rows else None


def _flaky(runs: list[dict]) -> bool:
    """A run that failed and then passed on a re-run of the same commit."""
    by_id = defaultdict(list)
    for r in runs:
        by_id[r.get("id")].append(r)
    for attempts in by_id.values():
        attempts.sort(key=lambda r: r.get("att") or 1)
        failed = next((i for i, r in enumerate(attempts) if r.get("c") in ("failure", "timed_out")), None)
        if failed is not None and any(r.get("c") == "success" for r in attempts[failed + 1:]):
            return True
    return False


def outcomes(rows: list, ci: dict, incidents: list[dict], now: datetime, months: int = MONTHS, decided: list | None = None,
             min_n: int = MIN_N) -> dict:
    """{"window": {"assisted", "others"}, "monthly": [{"month", "assisted", "others"}]} over merged PRs `rows` (pr, phases,
    deployment); CI failures from runs that name the PR, reverts by title, failed deployments from attributed incidents;
    merge rate over `decided` (merged and closed PRs) when given."""
    runs = ci.get("runs") or []
    # Fork PRs' runs don't name the PR: they are matched by head owner and branch. PRs merged before the first stored
    # run are left out of the CI shares, since CI can say nothing about them.
    by_pr = runs_by_pr(runs, [r[0] for r in rows])
    ci_from = min((r["cr"] for r in runs if r.get("cr")), default=None)
    failed_ci = {n for n, rs in by_pr.items() if any(r.get("c") in ("failure", "timed_out") for r in rs)}
    flaky = {n for n, rs in by_pr.items() if _flaky(rs)}
    # An incident can be pinned near a PR only in a small deployment; release-sized batches are left out.
    batch = Counter(d["id"] for _p, _ph, d in rows if d)
    by_number = {p["n"]: p for p, _ph, _d in rows}
    reverted = {n for p, _ph, _d in rows if is_revert(p) and (n := revert_target(p, by_number)) is not None}
    failed_deps = {i.get("deployment") for i in incidents if i.get("deployment")}

    def stats(rs):
        if len(rs) < min_n:
            return {"n": len(rs), **{k: None for k in KEYS}}
        seen = [r for r in rs if ci_from and (r[0].get("mg") or "") >= ci_from]
        return {"n": len(rs), "pickup_p75_h": _p75(ph.get("pickup") for _p, ph, _d in rs),
                "review_p75_h": _p75(ph.get("review") for _p, ph, _d in rs),
                "size_p75": _p75((p.get("add") or 0) + (p.get("del") or 0) for p, _ph, _d in rs),
                "ci_n": len(seen), "ci_failed_share": _share(seen, lambda r: r[0]["n"] in failed_ci),
                "flaky_share": _share(seen, lambda r: r[0]["n"] in flaky),
                "reverted_share": _share(rs, lambda r: r[0]["n"] in reverted),
                "failed_deploy_share": _share([r for r in rs if r[2] and batch[r[2]["id"]] <= BATCH_MAX],
                                              lambda r: r[2]["id"] in failed_deps)}
    # Calendar months, this one included, and one start for every number (31-day steps landed a month early).
    start = now.year * 12 + now.month - 1 - (months - 1)
    first = f"{start // 12:04d}-{start % 12 + 1:02d}"
    groups = defaultdict(lambda: {"agent": [], "assisted": [], "others": []})
    window = {"agent": [], "assisted": [], "others": []}
    for row in rows:
        month = (row[0].get("mg") or "")[:7]
        if month < first:
            continue
        side = SIDES[mode(row[0])]
        window[side].append(row)
        groups[month][side].append(row)
    tools = defaultdict(int)
    for p, _ph, _d in window["agent"] + window["assisted"]:
        for t in assisted_by(p):
            tools[t] += 1
    rates = {"agent": [], "assisted": [], "others": []}
    for p in decided or []:
        if (p.get("mg") or p.get("st") == "CLOSED") and (p.get("mg") or p.get("cl") or "")[:7] >= first:
            rates[SIDES[mode(p)]].append(p)
    out = {side: stats(rs) for side, rs in window.items()}
    if decided is not None:
        for side, ps in rates.items():
            out[side]["merge_rate"] = round(sum(1 for p in ps if p.get("mg")) / len(ps), 4) if ps and len(ps) >= min_n else None
            out[side]["merge_rate_n"] = len(ps)
    # Like with like: people's AI-marked PRs against the same authors' other PRs of the same size; agents' PRs against
    # people's PRs of the same month and size (an agent has no "same author").
    same_author = lambda r: ((r[0].get("au") or "").lower(), _band(r[0]))  # noqa: E731
    same_month = lambda r: ((r[0].get("mg") or r[0].get("cl") or "")[:7], _band(r[0]))  # noqa: E731
    seen = lambda rs: [r for r in rs if ci_from and (r[0].get("mg") or "") >= ci_from]  # noqa: E731
    small = lambda rs: [r for r in rs if r[2] and batch[r[2]["id"]] <= BATCH_MAX]  # noqa: E731
    checks = {"ci_failed": (seen, lambda r: r[0]["n"] in failed_ci), "reverted": (lambda rs: rs, lambda r: r[0]["n"] in reverted),
              "failed_deploy": (small, lambda r: r[2]["id"] in failed_deps)}
    pairs = {"assisted": same_author, "agent": same_month}
    compared = {side: {name: matched(pick(window[side]), pick(window["others"]), key, hit) for name, (pick, hit) in checks.items()}
                for side, key in pairs.items()}
    if decided is not None:
        # Merged at all, and merged by someone other than its author (most agents' PRs are merged by whoever ran them).
        wrap = lambda ps: [(p, {}, None) for p in ps]  # noqa: E731
        by_others = lambda r: bool(r[0].get("mg")) and (_merger(r[0]) or "").lower() != (r[0].get("au") or "").lower()  # noqa: E731
        for side, key in pairs.items():
            compared[side]["merged"] = matched(wrap(rates[side]), wrap(rates["others"]), key, lambda r: bool(r[0].get("mg")))
            # A merged PR whose merger isn't known says nothing about who merged it: left out of this one.
            known = lambda ps: [p for p in ps if not p.get("mg") or _merger(p)]  # noqa: E731
            compared[side]["merged_by_others"] = matched(wrap(known(rates[side])), wrap(known(rates["others"])), key, by_others)
    people = window["assisted"] + window["others"]
    authors = {(r[0].get("au") or "").lower() for r in people}
    marking = {(r[0].get("au") or "").lower() for r in window["assisted"]}
    coverage = {"people_prs": len(people), "marked": len(window["assisted"]),
                "marked_share": round(len(window["assisted"]) / len(people), 4) if people else None,
                "authors": len(authors), "authors_marking": len(marking)}
    return {"window": out, "tools": dict(tools), "matched": compared, "coverage": coverage,
            "monthly": [{"month": m, **{side: stats(g[side]) for side in ("agent", "assisted", "others")}}
                        for m, g in sorted(groups.items())]}


def baseline(bench: dict | None, language: str | None, stars: int | None) -> dict | None:
    """How often coding agents' PRs get merged in similar public repos (the crawl's median repo, last 6 months), with
    people's outside PRs in the same repos for scale. A bad or missing file gives None."""
    from mergescout.bench.ci import tier
    from stackvitals.ci.bench import _label
    groups = (bench or {}).get("agent_prs") or {}
    size = tier(stars)
    for key in (f"{language}|{size}", f"{language}|all", f"all|{size}", "all|all"):
        g = groups.get(key)
        if not isinstance(g, dict):
            continue
        a, o = (g.get("agent") or {}).get("merged"), (g.get("outsider") or {}).get("merged")
        if isinstance(g.get("repos_with_agent_prs"), int) and all(isinstance(x, (int, float)) for x in (a, o)):
            out = {"group": _label(key), "repos": g["repos_with_agent_prs"], "agent_merged": a, "outsider_merged": o}
            m = ((bench or {}).get("agent_matched") or {}).get(key)
            if isinstance(m, dict) and all(isinstance(m.get(k), dict) and isinstance(m[k].get("gap"), (int, float))
                                           for k in ("merged", "merged_by_others")):
                # The same group's like-for-like gap: agents' PRs against people's of the same repo, month and size.
                out["matched"] = {k: m[k] for k in ("repos", "agent_prs", "merged", "merged_by_others") if k in m}
            return out
    return None


def rework_rate(deps: list[dict], rows: list, incidents: list[dict], start: datetime, end: datetime) -> dict:
    """Deployments in the range that shipped an unplanned fix for a production problem (a revert, a hotfix, or a PR whose
    title names an incident issue), over all."""
    s, e = iso(start), iso(end)
    in_win = [d for d in deps if s <= d["finished"] <= e]
    fixes = {i["number"] for i in incidents if i.get("source") in ("revert", "hotfix")}
    issues = {i["number"] for i in incidents if i.get("source") == "issue"}
    shipped, deployed = defaultdict(set), {}
    for p, _ph, dep in rows:
        if dep:
            shipped[dep["id"]].add(p["n"])
            deployed[p["n"]] = dep["id"]
            # A PR whose title names an incident issue is a fix for it.
            if {int(n) for n in re.findall(r"#(\d+)", p.get("ti") or "")} & issues:
                fixes.add(p["n"])
    by_number = {p["n"]: p for p, _ph, _d in rows}
    for p, _ph, _d in rows:
        # A revert that went out with the change it undid never fixed anything users saw.
        target = revert_target(p, by_number) if p["n"] in fixes and is_revert(p) else None
        if target is not None and deployed.get(target) is not None and deployed.get(target) == deployed.get(p["n"]):
            fixes.discard(p["n"])
    rework = [d for d in in_win if shipped[d["id"]] & fixes]
    return {"rework_rate": round(len(rework) / len(in_win), 4) if in_win else None, "rework_deployments": len(rework),
            "deployments_n": len(in_win),
            "rework_range": [round(x, 4) for x in wilson(len(rework), len(in_win))] if in_win else None}
