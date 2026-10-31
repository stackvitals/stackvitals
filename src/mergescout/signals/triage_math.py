"""The outside-PR triage model: plain buckets, a small logistic fit and plain reasons. No database or numpy needed,
so the suite can score PRs with the model file the pipeline publishes."""
import math

# The first value of each feature is the reference: its weight is 0 and it is never given as a reason.
FEATURES = {
    # The author's past here: a first PR, earlier PRs none merged, or merged PRs. One input, so the parts can't overlap.
    "history": ["new", "tried", "1-2", "3+"],
    "size": ["<50", "50-199", "200-999", "1000+"],
    "issue": ["no", "yes"],
    "repo_rate": ["unknown", "<30%", "30-60%", "60-80%", "80%+"],
}
WORDS = {
    "history=tried": "has opened PRs here before, none merged yet",
    "history=1-2": "has 1-2 merged PRs in this repo already", "history=3+": "has 3+ merged PRs in this repo already",
    "size=50-199": "changes 50-199 lines", "size=200-999": "changes 200-999 lines", "size=1000+": "changes 1,000+ lines",
    "issue=yes": "links an issue",
    "repo_rate=<30%": "this repo merges under 30% of outside PRs", "repo_rate=30-60%": "this repo merges 30-60% of outside PRs",
    "repo_rate=60-80%": "this repo merges 60-80% of outside PRs", "repo_rate=80%+": "this repo merges 80%+ of outside PRs",
}


def _bucket(value, edges: list[float], names: list[str]) -> str:
    for edge, name in zip(edges, names):
        if value < edge:
            return name
    return names[len(edges)]


def buckets(here_merged: int, lines: int, linked_issue: bool, first_timer: bool, repo_rate: float | None) -> dict:
    # An author's record in other repos was tried and dropped: it added nothing on unseen repos, and the live count
    # (all of GitHub) can't match the training count (crawled repos only).
    history = ("new" if first_timer else "tried") if here_merged < 1 else _bucket(here_merged, [3], ["1-2", "3+"])
    return {"history": history, "size": _bucket(lines, [50, 200, 1000], FEATURES["size"]),
            "issue": "yes" if linked_issue else "no",
            "repo_rate": "unknown" if repo_rate is None else _bucket(repo_rate, [0.3, 0.6, 0.8], FEATURES["repo_rate"][1:])}


COLUMNS = [f"{name}={v}" for name, values in FEATURES.items() for v in values[1:]]


def _x(feats: dict) -> list[float]:
    return [1.0] + [1.0 if feats.get(c.split("=")[0]) == c.split("=", 1)[1] else 0.0 for c in COLUMNS]


def _sigmoid(z: float) -> float:
    return 1 / (1 + math.exp(-max(-30.0, min(30.0, z))))


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        m[col], m[pivot] = m[pivot], m[col]
        for r in range(n):
            if r != col and m[col][col]:
                f = m[r][col] / m[col][col]
                m[r] = [x - f * y for x, y in zip(m[r], m[col])]
    return [m[i][n] / m[i][i] if m[i][i] else 0.0 for i in range(n)]


def fit(rows: list[dict], ridge: float = 1.0, iters: int = 25) -> dict:
    """Logistic regression on aggregated cells (rows sharing every bucket fit as one), Newton steps with a light ridge."""
    cells = {}
    for r in rows:
        key = tuple(r[name] for name in FEATURES)
        n, k = cells.get(key, (0, 0))
        cells[key] = (n + 1, k + bool(r["merged"]))
    xs = [(_x(dict(zip(FEATURES, key))), n, k) for key, (n, k) in cells.items()]
    w = [0.0] * (len(COLUMNS) + 1)
    for _ in range(iters):
        grad = [0.0] * len(w)
        hess = [[0.0] * len(w) for _ in w]
        for x, n, k in xs:
            p = _sigmoid(sum(a * b for a, b in zip(w, x)))
            for i, xi in enumerate(x):
                if xi:
                    grad[i] += xi * (k - n * p)
                    for j, xj in enumerate(x):
                        if xj:
                            hess[i][j] += n * p * (1 - p) * xi * xj
        for i in range(1, len(w)):
            grad[i] -= ridge * w[i]
            hess[i][i] += ridge
        step = _solve(hess, grad)
        w = [a + b for a, b in zip(w, step)]
        if max(abs(s) for s in step) < 1e-6:
            break
    return {"version": 1, "features": FEATURES, "intercept": w[0], "coef": dict(zip(COLUMNS, w[1:]))}


def predict(model: dict, feats: dict) -> float:
    return _sigmoid(model["intercept"] + sum(model["coef"].get(f"{k}={v}", 0.0) for k, v in feats.items()))


def calibration(model: dict, rows: list[dict]) -> dict:
    """Predicted against actual merge share in ten equal bins, and Brier scores against "the repo's usual rate" alone."""
    scored = sorted(((predict(model, r), bool(r["merged"]), r["repo_rate"]) for r in rows), key=lambda t: t[0])
    deciles = []
    for i in range(10):
        part = scored[i * len(scored) // 10:(i + 1) * len(scored) // 10]
        if part:
            deciles.append({"predicted": round(sum(p for p, _, _ in part) / len(part), 4),
                            "actual": round(sum(y for _, y, _ in part) / len(part), 4), "n": len(part)})
    by_rate = {}
    for _, y, rate in scored:
        n, k = by_rate.get(rate, (0, 0))
        by_rate[rate] = (n + 1, k + y)
    brier = sum((p - y) ** 2 for p, y, _ in scored) / len(scored)
    baseline = sum((by_rate[rate][1] / by_rate[rate][0] - y) ** 2 for _, y, rate in scored) / len(scored)
    return {"deciles": deciles, "brier": round(brier, 5), "baseline_brier": round(baseline, 5), "n": len(scored)}


def explain(model: dict, feats: dict, k: int = 3) -> list[dict]:
    """The biggest reasons behind a score, in plain words; reference buckets are never reasons."""
    parts = [(f"{name}={value}", model["coef"].get(f"{name}={value}", 0.0)) for name, value in feats.items()]
    parts = [(key, w) for key, w in parts if key in WORDS and abs(w) >= 0.1]
    parts.sort(key=lambda kw: -abs(kw[1]))
    return [{"why": WORDS[key], "effect": "raises" if w > 0 else "lowers", "weight": round(w, 3)} for key, w in parts[:k]]
