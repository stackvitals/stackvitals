"""GitHub timestamps ("2026-10-20T12:00:00Z") in and out, and spans that are never negative."""
from datetime import datetime, timedelta

FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def parse(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text.replace("Z", "+00:00")) if text else None


def iso(dt: datetime) -> str:
    return dt.strftime(FORMAT)


def secs(start: str | None, end: str | None) -> float | None:
    # Times out of order (clock skew, imported history) give None, never a negative wait.
    a, b = parse(start), parse(end)
    return (b - a).total_seconds() if a and b and b >= a else None


def hours(start: str | None, end: str | None) -> float | None:
    s = secs(start, end)
    return None if s is None else s / 3600


def week_of(t: datetime | str) -> str:
    # Weeks start on Monday.
    t = parse(t) if isinstance(t, str) else t
    return (t - timedelta(days=t.weekday())).strftime("%Y-%m-%d")
