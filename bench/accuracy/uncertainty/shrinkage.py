"""Does pulling a small sample's first-try share toward similar repos predict the rest of the repo's pushes better?

From the crawl's per-repo CI records (each repo's first-try green share over its last pushes), repos are split in two:
one half fits the Beta prior per group (as the benchmark does), the other half is tested. For each tested repo with at
least m + 10 pushes, m of its pushes are drawn at random (m = 3, 5, 10, 20) and the share of the held-out rest is
predicted from them, raw and pulled. Reported per m: root mean squared error of each (the pulled share is the best
guess under squared error), mean absolute error, and how often the 95% predictive range covers the held-out share
(inclusive, and as randomized PIT, the fair measure for counts). Pass bars: pulled beats raw on squared error for
every m under 30; randomized coverage between 90% and 97%.

    python bench/accuracy/uncertainty/shrinkage.py <folder of ci-YYYY-MM-DD.ndjson.gz> [--draws 20] [--seed 13]
"""
import argparse
import gzip
import json
import math
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

from mergescout.bench.ci import tier
from stackvitals.core.stats import beta_fit, shrink

SIZES = (3, 5, 10, 20)
HELD_OUT = 10  # at least this many pushes kept back to score against
MIN_GROUP = 20


def _records(folder: Path) -> list[dict]:
    latest = {}
    for path in sorted(folder.glob("ci-*.ndjson.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    latest[r["repo"].lower()] = r
    return [r for r in latest.values() if r.get("pushes")]


def _pair(r: dict) -> tuple[int, int]:
    return round(r["first_try_share"] * r["pushes"]), r["pushes"]


def _band(value, edges: tuple) -> int:
    v = float(value or 0)
    return sum(v >= e for e in edges)


# Peer groups to compare, finest first; each falls back to language and size, then to all repos.
GROUPINGS = {
    "lang_size": lambda r: [],
    "lang_size_duration": lambda r: [f"d{_band(r.get('median_s'), (120, 600, 1800))}"],
    "lang_size_workflows": lambda r: [f"w{_band(r.get('workflows'), (2, 4, 8))}"],
    "lang_size_both": lambda r: [f"d{_band(r.get('median_s'), (120, 600, 1800))}w{_band(r.get('workflows'), (2, 4, 8))}"],
}


def keys(r: dict, group: str = "lang_size") -> list[str]:
    base = f"{r.get('language') or 'Other'}|{tier(r.get('stars'))}"
    return [f"{base}|{extra}" for extra in GROUPINGS[group](r)] + [base, "all|all"]


def _priors(fit: list[dict], group: str = "lang_size") -> dict:
    groups = {}
    for r in fit:
        for key in keys(r, group):
            groups.setdefault(key, []).append(_pair(r))
    return {k: beta_fit(v) for k, v in groups.items() if len(v) >= MIN_GROUP}


def _predictive(a: float, b: float, trials: int, q: float) -> int:
    # The beta-binomial quantile: hits among `trials` more pushes given a Beta(a, b) belief about the share.
    lbeta = lambda x, y: math.lgamma(x) + math.lgamma(y) - math.lgamma(x + y)  # noqa: E731
    total = 0.0
    for x in range(trials + 1):
        total += math.exp(math.lgamma(trials + 1) - math.lgamma(x + 1) - math.lgamma(trials - x + 1)
                          + lbeta(x + a, trials - x + b) - lbeta(a, b))
        if total >= q:
            return x
    return trials


def _cdf(a: float, b: float, trials: int, x: int) -> tuple[float, float]:
    # (chance of fewer than x hits, chance of exactly x) under the beta-binomial.
    lbeta = lambda u, v: math.lgamma(u) + math.lgamma(v) - math.lgamma(u + v)  # noqa: E731
    pmf = lambda k: math.exp(math.lgamma(trials + 1) - math.lgamma(k + 1) - math.lgamma(trials - k + 1)  # noqa: E731
                             + lbeta(k + a, trials - k + b) - lbeta(a, b))
    return sum(pmf(k) for k in range(x)), pmf(x)


def run(folder: Path, draws: int, seed: int, group: str = "lang_size") -> dict:
    rng = random.Random(seed)
    recs = _records(folder)
    rng.shuffle(recs)
    fit, test = recs[: len(recs) // 2], recs[len(recs) // 2:]
    priors = _priors(fit, group)
    out = {m: {"raw": 0.0, "pulled": 0.0, "raw2": 0.0, "pulled2": 0.0, "covered": 0, "mid": 0.0, "rate_covered": 0, "n": 0,
               "repos": 0}
           for m in SIZES}
    tested = [r for r in test if r["pushes"] >= SIZES[0] + HELD_OUT]
    for r in tested:
        k, n = _pair(r)
        prior = next(priors[k] for k in keys(r, group) if k in priors)
        pushes = [1] * k + [0] * (n - k)
        for m in SIZES:
            if n < m + HELD_OUT:
                continue
            out[m]["repos"] += 1
            for _ in range(draws):
                rng.shuffle(pushes)
                seen, rest = pushes[:m], pushes[m:]
                hits, truth = sum(seen), sum(rest) / len(rest)
                pulled = shrink(hits, m, prior)
                a, b = prior[0] + hits, prior[1] + m - hits
                lo, hi = _predictive(a, b, len(rest), 0.025) / len(rest), _predictive(a, b, len(rest), 0.975) / len(rest)
                cell = out[m]
                cell["raw"] += abs(hits / m - truth)
                cell["pulled"] += abs(pulled["value"] - truth)
                cell["raw2"] += (hits / m - truth) ** 2
                cell["pulled2"] += (pulled["value"] - truth) ** 2
                cell["covered"] += lo <= truth <= hi
                # Whole pushes can't make an exact 95%: the randomized PIT places the outcome at a random point of its
                # own probability step, and a calibrated prediction puts exactly 95% of those inside 2.5%..97.5%.
                below, at = _cdf(a, b, len(rest), sum(rest))
                pit = below + rng.random() * at
                cell["mid"] += 0.025 <= pit <= 0.975
                cell["rate_covered"] += pulled["low"] <= truth <= pulled["high"]
                cell["n"] += 1
    table = {}
    for m, c in out.items():
        if c["n"]:
            raw, pulled = c["raw"] / c["n"], c["pulled"] / c["n"]
            rmse_raw, rmse_pulled = math.sqrt(c["raw2"] / c["n"]), math.sqrt(c["pulled2"] / c["n"])
            table[str(m)] = {"rmse_raw": round(rmse_raw, 4), "rmse_pulled": round(rmse_pulled, 4),
                             "squared_error_cut": round(1 - (rmse_pulled / rmse_raw) ** 2, 4) if rmse_raw else None,
                             "mae_raw": round(raw, 4), "mae_pulled": round(pulled, 4), "repos": c["repos"],
                             "predictive_coverage": round(c["covered"] / c["n"], 4),
                             "predictive_coverage_pit": round(c["mid"] / c["n"], 4),
                             "rate_range_coverage": round(c["rate_covered"] / c["n"], 4), "draws": c["n"]}
    return {"repos": len(recs), "fit_repos": len(fit), "tested_repos": len(tested), "seed": seed, "group": group,
            "priors": len(priors),
            "prior_all": [round(x, 3) for x in priors["all|all"]], "by_sample_size": table}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("folder", type=Path)
    ap.add_argument("--draws", type=int, default=20)
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--group", choices=sorted(GROUPINGS), default="lang_size")
    ap.add_argument("--out", type=Path, default=Path(__file__).with_name("shrinkage-results.json"))
    args = ap.parse_args(argv)
    out = run(args.folder, args.draws, args.seed, args.group)
    out["generated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    args.out.write_text(json.dumps(out, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
