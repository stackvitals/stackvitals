"""Week against baseline: the latest seven days of a number against the four weeks before them, with n on both sides
and a p-value, so the digest flags only the changes that survive false-alarm control across everything it checked."""
import math
from datetime import datetime, timedelta

from stackvitals.core import stats
from stackvitals.core.time import iso

WEEK, BASE_WEEKS = timedelta(days=7), 4
HISTORY_WEEKS = 8  # past weeks that show how much this repo's weeks usually swing
# The typical swing before a repo's own history is known, worth 4 weeks: review times swing 1.5 to 2 times what
# independent PRs would (20 public repos; 1.5 chosen on half of them, checked on the other half); shares and counts 1.
PRIOR_SPREAD, PRIOR_WEEKS = {"share": 1.0, "count": 1.0}, 4
TIME_SPREAD = 1.5
# One wild past week (a backlog merged at once) counts as at most a four-sigma swing: the same catches as three sigma
# on 29 public repos, with fewer false flags (7.6% and 8.8% of shuffled scans on each half against 7.9% and 9.7%).
Z2_CAP = 16.0
MIN_EACH = 5  # fewer on either side and a shift says nothing
Q = 0.1  # the share of flagged changes allowed to be false alarms, across one scan


def windows(now: datetime, weeks: int = 1) -> tuple[tuple[str, str], tuple[str, str]]:
    """(the last `weeks` weeks, the four weeks before them) as ISO bounds, start included and end left out."""
    cut = now - WEEK * weeks
    return (iso(cut), iso(now)), (iso(cut - WEEK * BASE_WEEKS), iso(cut))


def _row(metric: str, label: str, now, base, n_now: int, n_base: int, p: float, better: int, unit: str,
         note: str | None = None, **extra) -> dict:
    direction = None if now is None or base is None else "same" if now == base else "up" if now > base else "down"
    worse = direction in ("up", "down") and better != 0 and (direction == "up") == (better < 0)
    return {"metric": metric, "label": label, "now": now, "base": base, "n_now": n_now, "n_base": n_base,
            "p": round(p, 6), "direction": direction, "better": better, "worse": worse, "unit": unit, "note": note,
            **extra}


def share(metric: str, label: str, k_now: int, n_now: int, k_base: int, n_base: int, better: int) -> dict:
    """A share this week against the weeks before (Fisher's exact test)."""
    enough = min(n_now, n_base) >= MIN_EACH
    p = stats.fisher(k_now, n_now, k_base, n_base) if enough else 1.0
    value = lambda k, n: round(k / n, 4) if n else None  # noqa: E731
    return _row(metric, label, value(k_now, n_now), value(k_base, n_base), n_now, n_base, p, better, "share",
                None if enough else "too few to tell")


def times(metric: str, label: str, now_values: list[float], base_values: list[float], better: int, unit: str,
          span: int = 1) -> dict:
    """A duration over the last `span` weeks against the four before (medians shown, Mann-Whitney tested)."""
    a, b = [v for v in now_values if v is not None], [v for v in base_values if v is not None]
    enough = min(len(a), len(b)) >= MIN_EACH
    p = stats.mann_whitney(a, b) if enough else 1.0
    mid = lambda v: None if not v else round(stats.median(v), 2)  # noqa: E731
    logs = [math.log(max(v, 1 / 60)) for v in b]  # a minute's floor: instant merges would make the log endless
    log_sd = round(stats.stdev(logs), 4) if len(logs) > 1 else None
    return _row(metric, label, mid(a), mid(b), len(a), len(b), p, better, unit, None if enough else "too few to tell",
                log_sd=log_sd, span=span)


def count(metric: str, label: str, now_count: int, base_count: int, better: int) -> dict:
    """A weekly count against the weekly average of the weeks before (binomial on the combined count)."""
    enough = now_count + base_count >= MIN_EACH
    p = stats.count_change(now_count, base_count, BASE_WEEKS) if enough else 1.0
    return _row(metric, label, now_count, round(base_count / BASE_WEEKS, 2), now_count, base_count, p, better, "count",
                None if enough else "too few to tell")


def calibrate(checks_at, now: datetime, weeks: int = HISTORY_WEEKS) -> list[dict]:
    """This week's checks with each p-value judged against the same check in the repo's past weeks.

    Work arrives in batches (a busy review day, a release week), so events in one week are not independent and a
    plain test overstates certainty. Each check is also run for each past week against its own four before it; how
    widely those results swing (their mean squared z, blended with a typical swing worth four weeks) scales this
    week's z, read on a t-distribution with one degree of freedom per week of evidence (an empirical null).
    A check over several weeks is judged against past windows that don't overlap it, so an ongoing slowdown doesn't
    count as the repo's usual swing."""
    current = checks_at(now)
    longest = max((c.get("span", 1) for c in current), default=1)
    past = {j: checks_at(now - WEEK * j) for j in range(1, weeks + longest)}
    out = []
    for i, c in enumerate(current):
        span = c.get("span", 1)
        z2 = [min(stats.normal_isf(week[i]["p"]) ** 2, Z2_CAP) for week in (past[j] for j in range(span, span + weeks))
              if i < len(week) and week[i]["note"] is None]
        if c["note"] is None:
            prior = PRIOR_SPREAD.get(c["unit"], TIME_SPREAD)
            spread = max(1.0, (sum(z2) + PRIOR_WEEKS * prior) / (len(z2) + PRIOR_WEEKS))
            p = stats.t_two_sided(stats.normal_isf(c["p"]) / math.sqrt(spread), len(z2) + PRIOR_WEEKS)
            c = {**c, "p": round(p, 6), "p_raw": c["p"], "spread": round(spread, 2), "weeks_seen": len(z2),
                 "df": len(z2) + PRIOR_WEEKS, "scale": _scale(c, spread)}
        out.append(c)
    return out


def _scale(c: dict, spread: float) -> float | None:
    # One standard error of the change on its own scale (log time, or share), widened by the repo's usual swing.
    if c["unit"] == "count" or not c["n_now"] or not c["n_base"]:
        return None
    both = math.sqrt(1 / c["n_now"] + 1 / c["n_base"]) * math.sqrt(spread)
    if c["unit"] == "share":
        pb = min(max(c["base"] or 0, 0.02), 0.98)
        return round(math.sqrt(pb * (1 - pb)) * both, 5)
    if not c.get("log_sd"):
        return None
    return round(c["log_sd"] * both * 1.023, 5)  # rank tests on skewed times lose about 2% against the ideal test


def detectable(c: dict, run: int, q: float = Q) -> float | None:
    """The change this check would have caught with about 80% chance in a scan of `run` checks: a factor for times,
    points of share for shares, None for counts."""
    if c.get("scale") is None:
        return None
    z = stats.t_isf(q / max(run, 1), c["df"]) + 0.8416
    return round(math.exp(z * c["scale"]) if c["unit"] not in ("share", "count") else z * c["scale"], 4)


def flag(found: list[dict], q: float = Q) -> list[dict]:
    """Every change with `changed` set: True only for those surviving Benjamini-Hochberg over the checks actually run
    in the scan (one with too few items to tell is not a test, so it doesn't count against the others)."""
    run = [i for i, c in enumerate(found) if c.get("note") is None]
    keep = {i for i, k in zip(run, stats.bh([found[i]["p"] for i in run], q)) if k}
    # A pairing from an earlier pass (a module's own) is decided again here, over this scan's checks.
    out = [{**{k: v for k, v in c.items() if k != "shown_with"}, "changed": i in keep and c["direction"] in ("up", "down")}
           for i, c in enumerate(found)]
    # A slowdown flagged both this week and over 14 days is one finding: the 14-day row is shown with the weekly one.
    weekly = {c["metric"]: c for c in out if c["changed"]}
    return [{**c, "shown_with": c["metric"][:-4]} if c["metric"].endswith("_14d") and c["changed"]
            and weekly.get(c["metric"][:-4], {}).get("direction") == c["direction"] else c for c in out]


def annotate(found: list[dict], q: float = Q) -> list[dict]:
    """A module's checks as its page shows them: flagged within the module, each with the change it could have caught."""
    run = sum(1 for c in found if c.get("note") is None)
    return [{**c, "detectable": detectable(c, run, q) if c.get("note") is None else None} for c in flag(found, q)]
