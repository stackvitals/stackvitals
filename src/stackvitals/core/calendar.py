"""A team's working calendar ([calendar] weekends and holidays): hours between two times with the non-working days
(whole UTC days) left out, so a review phase isn't charged a weekend nobody worked."""
from datetime import date, datetime, timedelta, timezone

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _t(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def is_set(cal: dict | None) -> bool:
    return bool(cal and (cal.get("weekends") or cal.get("holidays")))


def elapsed_hours(a: str | None, b: str | None, cal: dict | None) -> float | None:
    """Hours from a to b, without the weekends and holidays in `cal` (None: plain clock hours)."""
    if not a or not b:
        return None
    start, end = _t(a), _t(b)
    total = (end - start).total_seconds() / 3600
    if not is_set(cal) or end <= start:
        return round(total, 4)
    off_days = {DAYS.index(d) for d in cal.get("weekends") or []}
    holidays = {date.fromisoformat(h) for h in cal.get("holidays") or []}
    day = start.date()
    while day <= end.date():
        if day.weekday() in off_days or day in holidays:
            lo = max(start, datetime(day.year, day.month, day.day, tzinfo=timezone.utc))
            hi = min(end, datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(days=1))
            if hi > lo:
                total -= (hi - lo).total_seconds() / 3600
        day += timedelta(days=1)
    return round(max(total, 0.0), 4)
