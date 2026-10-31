"""The suite's only statistics helpers: every module computes medians, percentiles and ranges the same way."""
import math

# One implementation each, shared with the crawler that builds the benchmarks.
from mergescout.bench.matched import mh_risk_difference  # noqa: F401
from mergescout.bench.prior import beta_fit  # noqa: F401


def median(values: list[float]) -> float | None:
    if not values:
        return None
    s, n = sorted(values), len(values)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def stdev(values: list[float]) -> float | None:
    """The sample standard deviation, or None under two values."""
    if len(values) < 2:
        return None
    m = sum(values) / len(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / (len(values) - 1))


def percentile(values: list[float], q: float) -> float | None:
    # Nearest rank: the value at ceil(q * n), never interpolated, so small samples show real values.
    if not values:
        return None
    s = sorted(values)
    return s[min(len(s) - 1, max(0, math.ceil(q * len(s)) - 1))]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """A 95% range for a share of k in n; no trials means anything from 0 to 1, and k above n clamps instead of crashing."""
    if n <= 0:
        return 0.0, 1.0
    p = min(k, n) / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


MIN_RANGE = 6


def quantile_range(values: list[float], q: float, z: float = 1.96) -> tuple[float, float] | None:
    """A 95% range for a quantile from the values themselves (binomial order statistics), None under 6 values."""
    n = len(values)
    if n < MIN_RANGE:
        return None
    s = sorted(values)
    half = z * math.sqrt(n * q * (1 - q))
    lo = max(0, math.floor(n * q - half))
    hi = min(n - 1, math.ceil(n * q + half))
    return s[lo], s[hi]


def median_range(values: list[float], z: float = 1.96) -> tuple[float, float] | None:
    return quantile_range(values, 0.5, z)


def _betacf(a: float, b: float, x: float) -> float:
    # Lentz's continued fraction for the incomplete beta (Numerical Recipes, 6.4).
    tiny = 1e-300
    fix = lambda v: v if abs(v) > tiny else tiny  # noqa: E731
    c, d = 1.0, 1 / fix(1 - (a + b) * x / (a + 1))
    h = d
    for m in range(1, 400):
        for aa in (m * (b - m) * x / ((a - 1 + 2 * m) * (a + 2 * m)),
                   -(a + m) * (a + b + m) * x / ((a + 2 * m) * (a + 1 + 2 * m))):
            d = 1 / fix(1 + aa * d)
            c = fix(1 + aa / c)
            h *= d * c
        if abs(d * c - 1) < 3e-14:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """The regularized incomplete beta I_x(a, b): the chance a Beta(a, b) value is at most x."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1) / (a + b + 2):
        return front * _betacf(a, b, x) / a
    return 1 - front * _betacf(b, a, 1 - x) / b


def beta_ppf(q: float, a: float, b: float) -> float:
    """The value a Beta(a, b) stays under with chance q (bisection on betainc)."""
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if betainc(a, b, mid) < q else (lo, mid)
    return (lo + hi) / 2


def shrink(k: int, n: int, prior: tuple[float, float]) -> dict:
    """A share of k in n pulled toward its peers' Beta prior: the posterior mean and its 95% range."""
    a, b = prior[0] + min(k, n), prior[1] + max(0, n - k)
    return {"value": round(a / (a + b), 4), "low": round(beta_ppf(0.025, a, b), 4), "high": round(beta_ppf(0.975, a, b), 4),
            "n": n}


def t_two_sided(t: float, df: float) -> float:
    """Two-sided p-value of a Student t statistic with df degrees of freedom."""
    return min(1.0, betainc(df / 2, 0.5, df / (df + t * t))) if t else 1.0


def t_isf(p: float, df: float) -> float:
    """The |t| whose two-sided p-value with df degrees of freedom is p (bisection on t_two_sided)."""
    if p >= 1:
        return 0.0
    lo, hi = 0.0, 1e4
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if t_two_sided(mid, df) > p else (lo, mid)
    return (lo + hi) / 2


def normal_isf(p: float) -> float:
    """The |z| whose two-sided normal p-value is p (bisection on erfc)."""
    if p >= 1:
        return 0.0
    p = max(p, 1e-300)
    lo, hi = 0.0, 40.0
    for _ in range(100):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if math.erfc(mid / math.sqrt(2)) > p else (lo, mid)
    return (lo + hi) / 2


def _log_comb(n: int, k: int) -> float:
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def fisher(k1: int, n1: int, k2: int, n2: int) -> float:
    """Two-sided p-value that k1 of n1 and k2 of n2 come from the same share (Fisher's exact test)."""
    if n1 <= 0 or n2 <= 0:
        return 1.0
    hits, total = k1 + k2, n1 + n2
    lo, hi = max(0, hits - n2), min(hits, n1)
    log_p = lambda x: _log_comb(n1, x) + _log_comb(n2, hits - x) - _log_comb(total, hits)  # noqa: E731
    seen = log_p(k1)
    return min(1.0, sum(math.exp(log_p(x)) for x in range(lo, hi + 1) if log_p(x) <= seen + 1e-7))


def mann_whitney(x: list[float], y: list[float]) -> float:
    """Two-sided p-value that two samples come from the same distribution (normal approximation, ties averaged)."""
    n1, n2 = len(x), len(y)
    if not n1 or not n2:
        return 1.0
    both = sorted([(v, 0) for v in x] + [(v, 1) for v in y])
    ranks, ties, i = [0.0] * len(both), 0.0, 0
    while i < len(both):
        j = i
        while j + 1 < len(both) and both[j + 1][0] == both[i][0]:
            j += 1
        for t in range(i, j + 1):
            ranks[t] = (i + j) / 2 + 1
        ties += (j - i + 1) ** 3 - (j - i + 1)
        i = j + 1
    n = n1 + n2
    u = sum(r for r, (_v, side) in zip(ranks, both) if side == 0) - n1 * (n1 + 1) / 2
    var = n1 * n2 / 12 * ((n + 1) - ties / (n * (n - 1))) if n > 1 else 0
    if var <= 0:
        return 1.0
    z = max(0.0, abs(u - n1 * n2 / 2) - 0.5) / math.sqrt(var)
    return min(1.0, math.erfc(z / math.sqrt(2)))


def count_change(now: int, before: int, weeks: int) -> float:
    """Two-sided p-value that this week's count fits the `weeks` weeks before it (binomial on the combined count)."""
    total = now + before
    if total <= 0 or weeks <= 0:
        return 1.0
    p0 = 1 / (weeks + 1)
    log_pmf = lambda x: _log_comb(total, x) + x * math.log(p0) + (total - x) * math.log1p(-p0)  # noqa: E731
    seen = log_pmf(now)
    return min(1.0, sum(math.exp(log_pmf(x)) for x in range(total + 1) if log_pmf(x) <= seen + 1e-7))


KM_MIN = 10


def km_median(durations: list[float], answered: list[bool], z: float = 1.96) -> dict:
    """Median time to an answer with items still waiting kept in (Kaplan-Meier): the median and its 95% range
    (Brookmeyer-Crowley on Greenwood's variance), or no median and `at_least` when more than half are still waiting."""
    n, done = len(durations), sum(1 for a in answered if a)
    out = {"median": None, "low": None, "high": None, "at_least": None, "answered": done, "waiting": n - done}
    if n < KM_MIN:
        out["too_few"] = bool(n)
        return out
    s, greenwood, curve = 1.0, 0.0, []
    for t in sorted({d for d, a in zip(durations, answered) if a}):
        at_risk = sum(1 for d in durations if d >= t)
        events = sum(1 for d, a in zip(durations, answered) if a and d == t)
        s *= 1 - events / at_risk
        if at_risk > events:
            greenwood += events / (at_risk * (at_risk - events))
        curve.append((t, s, s * s * greenwood))
    out["median"] = next((t for t, sv, _v in curve if sv <= 0.5), None)
    if out["median"] is None:
        out["at_least"] = max(durations)
        return out
    near = [t for t, sv, var in curve if abs(sv - 0.5) <= z * math.sqrt(var)]
    out["low"], out["high"] = (min(near), max(near)) if near else (out["median"], out["median"])
    # The curve never clearly drops below a half: the range's upper end is beyond what was seen ("or more").
    if curve and abs(curve[-1][1] - 0.5) <= z * math.sqrt(curve[-1][2]):
        out["high"] = None
    return out


def bh(pvalues: list[float], q: float = 0.1) -> list[bool]:
    """Which p-values survive Benjamini-Hochberg at false-discovery rate q, across everything scanned together."""
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: pvalues[i])
    cut = max((rank for rank, i in enumerate(order, 1) if pvalues[i] <= rank * q / m), default=0)
    keep = set(order[:cut])
    return [i in keep for i in range(m)]
