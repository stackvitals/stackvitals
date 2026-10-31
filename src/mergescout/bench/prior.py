"""Peer priors for the benchmarks: the Beta(a, b) that best explains many repos' (hits, tries) pairs, so a small repo's
share can be pulled toward repos like it instead of shown raw."""
import math


def _golden(f, lo: float, hi: float, steps: int = 60) -> float:
    # The x in [lo, hi] where f is largest, for f with one peak.
    g = (math.sqrt(5) - 1) / 2
    x1, x2 = hi - g * (hi - lo), lo + g * (hi - lo)
    f1, f2 = f(x1), f(x2)
    for _ in range(steps):
        if f1 < f2:
            lo, x1, f1 = x1, x2, f2
            x2 = lo + g * (hi - lo)
            f2 = f(x2)
        else:
            hi, x2, f2 = x2, x1, f1
            x1 = hi - g * (hi - lo)
            f1 = f(x1)
    return (lo + hi) / 2


def beta_fit(pairs: list[tuple[int, int]]) -> tuple[float, float] | None:
    """The Beta(a, b) prior that best explains many (hits, tries) pairs (beta-binomial maximum likelihood)."""
    from collections import Counter
    counts = Counter((min(k, n), n) for k, n in pairs if n > 0)
    if not counts:
        return None
    lbeta = lambda x, y: math.lgamma(x) + math.lgamma(y) - math.lgamma(x + y)  # noqa: E731

    def loglik(mu: float, log_s: float) -> float:
        s = math.exp(log_s)
        a, b = mu * s, (1 - mu) * s
        return sum(c * (lbeta(k + a, n - k + b) - lbeta(a, b)) for (k, n), c in counts.items())
    total_k, total_n = sum(k * c for (k, n), c in counts.items()), sum(n * c for (k, n), c in counts.items())
    mu, log_s = min(0.999, max(0.001, total_k / total_n)), math.log(10)
    # Alternate between the mean and the strength (a + b); a few rounds settle both.
    for _ in range(6):
        log_s = _golden(lambda v: loglik(mu, v), math.log(0.05), math.log(1e4))
        mu = _golden(lambda v: loglik(v, log_s), 0.001, 0.999)
    s = math.exp(log_s)
    return mu * s, (1 - mu) * s
