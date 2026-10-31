"""The metric registry: every number the suite shows has an id, a version, a one-sentence definition, a minimum sample,
and comes out as a Measure with n, a range and an as-of time. Benchmarks use the same ids, so a repo's number and its
peer percentile are the same definition by construction."""
from dataclasses import asdict, dataclass
from datetime import datetime

from stackvitals.core import stats
from stackvitals.core.time import iso


@dataclass(frozen=True)
class Metric:
    id: str
    definition: str
    unit: str  # s, share, count, lines, ms
    kind: str  # median, p75, share, count
    min_n: int = 1
    better: int = 0  # -1 lower is better, 1 higher, 0 neither
    version: int = 1


@dataclass
class Measure:
    metric: str
    version: int
    value: float | None
    n: int
    low: float | None
    high: float | None
    unit: str
    as_of: str
    window_days: int | None = None
    note: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


REGISTRY: dict[str, Metric] = {}


def register(metric: Metric) -> Metric:
    REGISTRY[metric.id] = metric
    return metric


def get(metric_id: str) -> Metric:
    return REGISTRY[metric_id]


def all() -> list[Metric]:  # noqa: A001
    return list(REGISTRY.values())


def measure(metric_id: str, values: list[float] | None = None, hits: int | None = None, n: int | None = None,
            as_of: datetime | str = "", window_days: int | None = None) -> Measure:
    """One number with its evidence: a median or percentile of `values`, a share of `hits` in `n`, or a count `n`."""
    m = get(metric_id)
    stamp = as_of if isinstance(as_of, str) else iso(as_of)
    low = high = value = None
    if m.kind in ("median", "p75"):
        values = [v for v in (values or []) if v is not None]
        n = len(values)
        q = 0.5 if m.kind == "median" else 0.75
        if n >= m.min_n and n:
            value = stats.median(values) if m.kind == "median" else stats.percentile(values, q)
            rng = stats.quantile_range(values, q)
            low, high = rng if rng else (None, None)
    elif m.kind == "share":
        n = int(n or 0)
        if n >= m.min_n and n:
            value = round((hits or 0) / n, 4)
            low, high = (round(x, 4) for x in stats.wilson(hits or 0, n))
    else:
        n = int(n or 0)
        value = n
    note = None if value is not None or m.kind == "count" else f"not enough data (n={n}, needs {m.min_n})"
    return Measure(m.id, m.version, value, n, low, high, m.unit, stamp, window_days, note)


# Review flow: LinearB's four phases, review split into its approve and merge metrics, on GitHub's own timestamps; DevLake's four fields are derived from these.
for _id, _definition, _min in (
    ("flow.coding_time", "Seconds from the PR's first commit (authored) to the PR being opened; median.", 10),
    ("flow.pickup_time", "Seconds from the PR being ready for review (opened, or leaving draft) to the first review submitted "
                         "by a person other than the author (approval, change request or review comment); bots and agents "
                         "don't count; median over merged PRs.", 10),
    ("flow.review_time", "Seconds from the first review activity to the merge; median over merged PRs.", 10),
    ("flow.approve_time", "Seconds from the first review activity to the first approval; median.", 10),
    ("flow.merge_time", "Seconds from the first approval to the merge; median.", 10),
    ("flow.deploy_time", "Seconds from the merge to the end of the first successful production deployment that contains it; median.", 10),
    ("flow.cycle_time", "Seconds from ready for review to merged; median over merged PRs.", 10),
):
    register(Metric(_id, _definition, "s", "median", _min, -1))
register(Metric("flow.outsider_merge_rate", "Share of outside contributors' PRs (people who are not insiders; bots and "
                "agents left out) that were merged, among those decided in the window.", "share", "share", 10, 1))
register(Metric("flow.open_prs", "Open PRs by people, drafts included.", "count", "count"))
register(Metric("community.first_answer_time", "Seconds from an outside PR or issue being opened to the first answer by a "
                "maintainer (review, reply, merge or close by someone else); median.", "s", "median", 10, -1))
register(Metric("ci.flake_rate", "Share of runs of a job or test in the window that flaked (failed and passed on the same "
                "code).", "share", "share", 5, -1))
register(Metric("ci.first_try_green", "Share of pushes to the default branch whose checks all passed on the first attempt.",
                "share", "share", 5, 1))
register(Metric("ci.push_wait", "Seconds from a push to the default branch until all its checks finished; median.",
                "s", "median", 5, -1))
# Cross-module: CI Health's runs joined to Team Flow's pull requests.
register(Metric("insight.red_ci_share", "Share of people's merged pull requests that spent time ready for review with a "
                "failing check on their newest commit.", "share", "share", 10, -1))
register(Metric("insight.red_ci_hours", "Hours a merged pull request spent ready for review with a failing check on its "
                "newest commit, among those that did; median.", "h", "median", 5, -1))
