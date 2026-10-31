"""Fair comparisons for the accuracy cards: a range for any rate built from several measured rates, and a test for
every "ours against theirs" (Fisher's exact test for independent samples, McNemar's for rules scored on the same items).
"""
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from stackvitals.core.stats import fisher, wilson  # noqa: E402

DRAWS, SEED, ALPHA = 20_000, 7, 0.05


def _quantiles(values: list[float]) -> tuple[float, float]:
    values = sorted(values)
    return values[int(len(values) * 0.025)], values[min(len(values) - 1, int(len(values) * 0.975))]


def mixture(parts: list[tuple[int, int, float]], against: tuple[int, int] | None = None, draws: int = DRAWS,
            seed: int = SEED) -> dict:
    """A weighted rate from (hits, n, weight) parts, with a 95% range from Jeffreys posterior draws of each part.
    With `against`, also the range of against minus the mixture (a part equal to it shares its draws)."""
    rng = random.Random(seed)
    total = sum(w for _k, _n, w in parts)
    point = sum(w * k / n for k, n, w in parts if n) / total
    sims, diffs = [], []
    for _ in range(draws):
        drawn = [rng.betavariate(k + 0.5, n - k + 0.5) for k, n, _w in parts]
        value = sum(w * p for p, (_k, _n, w) in zip(drawn, parts)) / total
        sims.append(value)
        if against:
            same = [p for p, (k, n, _w) in zip(drawn, parts) if (k, n) == tuple(against)]
            mine = same[0] if same else rng.betavariate(against[0] + 0.5, against[1] - against[0] + 0.5)
            diffs.append(mine - value)
    lo, hi = _quantiles(sims)
    out = {"share": round(point, 4), "low": round(lo, 4), "high": round(hi, 4), "method": "Jeffreys draws, seed 7"}
    if against:
        dlo, dhi = _quantiles(diffs)
        out["difference"] = {"value": round(against[0] / against[1] - point, 4), "low": round(dlo, 4),
                             "high": round(dhi, 4), "significant": dlo > 0 or dhi < 0}
    return out


def compare_shares(k1: int, n1: int, k2: int, n2: int) -> dict:
    """Two independent samples: the difference in shares and Fisher's exact two-sided p."""
    p = fisher(k1, n1, k2, n2)
    diff = (k1 / n1 if n1 else 0) - (k2 / n2 if n2 else 0)
    return {"difference": round(diff, 4), "p": round(p, 6), "significant": p < ALPHA, "test": "Fisher's exact"}


def mcnemar(only_a: int, only_b: int) -> dict:
    """Two rules on the same items: items only A got right against items only B got right (exact two-sided)."""
    n = only_a + only_b
    if not n:
        return {"only_a": 0, "only_b": 0, "p": None, "significant": False, "test": "McNemar exact"}
    tail = sum(math.comb(n, i) for i in range(min(only_a, only_b) + 1)) / 2 ** n
    p = min(1.0, 2 * tail)
    return {"only_a": only_a, "only_b": only_b, "p": round(p, 6), "significant": p < ALPHA, "test": "McNemar exact"}


def by_repo(rows: list[tuple[str, bool]], draws: int = 2000, seed: int = SEED) -> dict:
    """A rate whose items cluster by repo: a bootstrap over repos, the range with each repo counted once (the widest
    honest one: it still shows a range when no item hit), and the rate without the biggest repo."""
    repos: dict[str, list[bool]] = {}
    for repo, hit in rows:
        repos.setdefault(repo, []).append(bool(hit))
    if not repos:
        return {"repos": 0}
    k, n = sum(sum(v) for v in repos.values()), sum(len(v) for v in repos.values())
    names = sorted(repos)
    rng = random.Random(seed)
    sims = []
    for _ in range(draws):
        picked = [repos[rng.choice(names)] for _ in names]
        total = sum(len(v) for v in picked)
        sims.append(sum(sum(v) for v in picked) / total if total else 0.0)
    lo, hi = _quantiles(sims)
    r = len(names)
    rlo, rhi = wilson(k / n * r, r)  # the same share, as if there were only one item per repo
    big = max(names, key=lambda x: (len(repos[x]), x))
    bk, bn = k - sum(repos[big]), n - len(repos[big])
    blo, bhi = wilson(bk, bn) if bn else (0.0, 1.0)
    return {"repos": r, "k": k, "n": n, "boot_low": round(lo, 4), "boot_high": round(hi, 4),
            "repo_wilson_low": round(rlo, 4), "repo_wilson_high": round(rhi, 4),
            "biggest": {"repo": big, "items": len(repos[big]), "share": round(len(repos[big]) / n, 4)},
            "without_biggest": {"k": bk, "n": bn, "low": round(blo, 4), "high": round(bhi, 4)},
            "method": f"bootstrap over repos ({draws} draws, seed {seed}); Wilson with each repo counted once"}
