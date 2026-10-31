"""Change risk before merge, from this repo's own history: which merged pull requests caused trouble (later reverted, or
shipped in a small deployment that then failed), how often changes to the same folders, of the same size, by someone
new to those folders, without test changes or by a coding agent did, and a score with its reasons for an open one.
A backtest on the newest pull requests says how much the score is worth here."""
import math
import re
from collections import defaultdict
from datetime import datetime, timedelta

from stackvitals.core.ai_outcomes import BATCH_MAX, _band, is_revert, mode, revert_target

MIN_TROUBLED = 5   # fewer troubled pull requests and there is no score, not a guess
MIN_PRS = 30
PRIOR = 5          # each factor's rate is pulled toward the repo's base rate as if it had 5 more ordinary PRs
NESTED = {"src", "lib", "libs", "packages", "apps", "services", "pkg", "internal", "app", "cmd"}
TESTS = ("test", "spec", "__tests__")


def troubled(rows: list, incidents: list[dict]) -> set[int]:
    """Merged PRs a later revert undid, or that shipped in a small deployment (5 PRs or fewer) that failed."""
    by_number = {p["n"]: p for p, _ph, _d in rows}
    out = {n for p, _ph, _d in rows if is_revert(p) and (n := revert_target(p, by_number)) is not None}
    batch = defaultdict(int)
    for _p, _ph, d in rows:
        if d:
            batch[d["id"]] += 1
    failed = {i.get("deployment") for i in incidents if i.get("deployment")}
    out |= {p["n"] for p, _ph, d in rows if d and d["id"] in failed and batch[d["id"]] <= BATCH_MAX}
    return out


FIX = re.compile(r"\b(fix|fixes|fixed|bug|bugfix|hotfix|regression)\b", re.I)
FOLLOW_UP_DAYS = 14
COMMON = 0.2  # a file most PRs touch (a lockfile, the changelog) links nothing


def _when(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def follow_up_fixes(prs: list[dict], days: int = FOLLOW_UP_DAYS) -> set[int]:
    """Merged PRs that a fix (by its title or a label) changing the same files followed within `days`: the lightweight
    form of SZZ, the standard way to find changes that needed fixing. Files most PRs touch are ignored."""
    merged = sorted((p for p in prs if p.get("mg") and p.get("paths")), key=lambda p: p["mg"])
    if not merged:
        return set()
    touched = defaultdict(int)
    for p in merged:
        for path in set(p["paths"]):
            touched[path] += 1
    common = {f for f, n in touched.items() if n > COMMON * len(merged)}
    is_fix = lambda p: bool(FIX.search(p.get("ti") or "") or any(FIX.search(x) for x in p.get("lb") or []))  # noqa: E731
    out = set()
    for f in (p for p in merged if is_fix(p)):
        files, end = set(f["paths"]) - common, _when(f["mg"])
        if not files:
            continue
        for p in merged:
            if p["n"] != f["n"] and not is_fix(p) and end - timedelta(days=days) <= _when(p["mg"]) < end \
                    and files & set(p["paths"]):
                out.add(p["n"])
    return out


def _dirs(p: dict) -> set[str]:
    out = set()
    for path in p.get("paths") or []:
        parts = path.split("/")
        if len(parts) < 2:
            out.add("(root)")
        else:
            depth = 2 if parts[0] in NESTED and len(parts) > 2 else 1
            out.add("/".join(parts[:depth]) + "/")
    return out


def _tests(p: dict) -> bool:
    return any(any(t in path.lower() for t in TESTS) for path in p.get("paths") or [])


def _facts(p: dict, seen: dict) -> dict:
    dirs = _dirs(p)
    who = (p.get("au") or "").lower()
    return {"dirs": dirs, "band": _band(p), "new": bool(dirs) and not (dirs & seen.get(who, set())),
            "tests": _tests(p), "agent": mode(p) == "agent"}


def fit(prs: list[dict], bad: set[int]) -> dict | None:
    """Each factor's smoothed troubled rate, learnt from merged PRs oldest first (familiarity as it was at the time)."""
    prs = sorted((p for p in prs if p.get("mg") and not is_revert(p)), key=lambda p: p["mg"])
    if len(prs) < MIN_PRS or sum(1 for p in prs if p["n"] in bad) < MIN_TROUBLED:
        return None
    base = sum(1 for p in prs if p["n"] in bad) / len(prs)
    counts = defaultdict(lambda: [0, 0])  # factor -> [PRs, troubled]
    seen: dict[str, set] = defaultdict(set)
    for p in prs:
        f, hit = _facts(p, seen), p["n"] in bad
        for key in [f"dir:{d}" for d in f["dirs"]] + [f"band:{f['band']}", f"new:{f['new']}", f"tests:{f['tests']}",
                                                       f"agent:{f['agent']}"]:
            counts[key][0] += 1
            counts[key][1] += hit
        seen[(p.get("au") or "").lower()] |= f["dirs"]
    rates = {k: (t + PRIOR * base) / (n + PRIOR) for k, (n, t) in counts.items()}
    return {"base": base, "rates": rates, "counts": {k: v for k, v in counts.items()}, "seen": seen, "prs": len(prs)}


def _odds(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return p / (1 - p)


def score(p: dict, model: dict | None) -> dict | None:
    """{"risk", "level", "reasons"} for one PR; None without a model."""
    if not model:
        return None
    base, rates, counts = model["base"], model["rates"], model["counts"]
    f = _facts(p, model["seen"])
    dir_keys = [f"dir:{d}" for d in f["dirs"] if f"dir:{d}" in rates]
    # The riskiest folder speaks for the change; other factors are combined as odds against the base rate.
    keys = ([max(dir_keys, key=lambda k: rates[k])] if dir_keys else []) + \
        [k for k in (f"band:{f['band']}", f"new:{f['new']}", f"tests:{f['tests']}", f"agent:{f['agent']}") if k in rates]
    log_odds = math.log(_odds(base)) + sum(math.log(_odds(rates[k]) / _odds(base)) for k in keys)
    risk = 1 / (1 + math.exp(-log_odds))
    reasons = []
    for k in keys:
        if rates[k] < 1.5 * base:
            continue
        n, t = counts[k]
        kind, value = k.split(":", 1)
        reasons.append({"dir": f"{value}: {t} of {n} changes here caused trouble",
                        "band": f"a change of about {(p.get('add') or 0) + (p.get('del') or 0):,} lines ({t} of {n} this size did)",
                        "new": "the author's first change in these folders",
                        "tests": "no test files changed" if value == "False" else "test files changed",
                        "agent": "written by a coding agent"}[kind])
    level = "high" if risk >= 2 * base and risk >= 0.1 else "medium" if risk >= 1.3 * base else "low"
    return {"risk": round(risk, 4), "level": level, "base": round(base, 4), "reasons": reasons}


def _auc(scored: list[tuple[float, bool]]) -> float | None:
    pos = [s for s, y in scored if y]
    neg = [s for s, y in scored if not y]
    if not pos or not neg:
        return None
    wins = sum((a > b) + 0.5 * (a == b) for a in pos for b in neg)
    return wins / (len(pos) * len(neg))


def backtest(prs: list[dict], bad: set[int], share: float = 0.7) -> dict | None:
    """Learn from the oldest 70% of merged PRs and score the newest 30%: how well the score ranks the troubled ones
    (AUC, 0.5 = no better than chance) and the trouble rate among the top fifth scored."""
    merged = sorted((p for p in prs if p.get("mg") and not is_revert(p)), key=lambda p: p["mg"])
    cut = int(len(merged) * share)
    train, test = merged[:cut], merged[cut:]
    model = fit(train, bad)
    hits = [p for p in test if p["n"] in bad]
    if not model or len(hits) < 3:
        return None
    scored = sorted(((score(p, model)["risk"], p["n"] in bad) for p in test), key=lambda x: -x[0])
    top = scored[:max(1, len(scored) // 5)]
    return {"train": len(train), "test": len(test), "test_troubled": len(hits), "auc": round(_auc(scored), 3),
            "top_fifth_trouble": round(sum(y for _s, y in top) / len(top), 3),
            "overall_trouble": round(len(hits) / len(test), 3)}


MIN_AUC = 0.65  # below this, this repo's own backtest says the score isn't worth showing


def assess(prs: list[dict], bad: set[int], open_prs: list[dict], top: int = 50) -> dict:
    """The backtest first; open PRs scored (riskiest first) only when it shows the score ranks trouble here."""
    bt = backtest(prs, bad)
    if not bt:
        return {"backtest": None, "open": None, "troubled": len(bad),
                "note": "Not enough history yet: it needs about 30 merged pull requests and a few that needed a fix."}
    if bt["auc"] < MIN_AUC:
        return {"backtest": bt, "open": None, "troubled": len(bad),
                "note": f"Not predictive in this repo: on its newest pull requests it ranked trouble about as well as chance "
                        f"(AUC {bt['auc']:.2f}), so no score is shown."}
    model = fit(prs, bad)
    scored = [{"pr": p.get("n"), **score(p, model)} for p in open_prs]
    scored.sort(key=lambda s: -s["risk"])
    return {"backtest": bt, "open": scored[:top], "troubled": len(bad), "note": None}
