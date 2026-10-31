"""Like-with-like comparisons for the benchmarks: a share compared within matched groups, so a crawl-wide gap is not
just a difference in which repos, months or sizes each kind of pull request comes from."""
import math


def mh_risk_difference(groups: list[tuple[int, int, int, int]]) -> tuple[float | None, float | None]:
    """(difference, standard error) of a share between two kinds of item compared within matched groups: each group is
    (hits, items) of the first kind and (hits, items) of the second. Mantel-Haenszel weights; Sato's variance, which stays
    right when most groups hold one or two items (a plain per-group variance falls to zero there)."""
    w_sum = num = p_sum = q_sum = 0.0
    for a, n1, c, n0 in groups:
        total = n1 + n0
        if not n1 or not n0:
            continue
        w_sum += n1 * n0 / total
        num += (a * n0 - c * n1) / total
        p_sum += (n1 * n1 * c - n0 * n0 * a + n1 * n0 * (n0 - n1) / 2) / (total * total)
        q_sum += (a * (n0 - c) + c * (n1 - a)) / (2 * total)
    if not w_sum:
        return None, None
    rd = num / w_sum
    return rd, math.sqrt(max(0.0, rd * p_sum + q_sum)) / w_sum
