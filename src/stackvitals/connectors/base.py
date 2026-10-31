"""What every connector shares: one way to ask a service (retries, rate limits, plain errors), its error, dates in UTC, and
DevLake's issue types and status categories."""
import time
from datetime import datetime, timezone

from stackvitals.core.time import iso

BACKFILL_DAYS = 180
PAGES = 20  # the most pages one run reads per connector; the next run carries on
TRIES = 3
LONGEST_WAIT = 60  # a rate limit asking for longer stops this run; the next one carries on


class ConnectorError(Exception):
    """A plain sentence for the job summary and the Integrations page; never holds a key."""


def json_of(resp, service: str, kinds: tuple = (dict,)):
    """The answer's JSON; a page that is not (a maintenance or login page) is said plainly instead of failing the job."""
    try:
        out = resp.json()
    except ValueError:
        out = None
    if not isinstance(out, kinds):
        raise ConnectorError(f"{service} answered with a page that is not JSON ({resp.status_code}); the next run tries again.")
    return out


def request(client, method: str, url: str, service: str, *, refused: str, bad=None, kinds: tuple = (dict,),
            sleep=time.sleep, **kw):
    """The JSON a service answers. A dropped connection or a server error is tried again, a short rate-limit wait is waited
    out, and anything else is a plain ConnectorError: `refused` says what to check on 401/403, `bad(resp)` may word others."""
    import httpx
    for attempt in range(TRIES):
        last = attempt == TRIES - 1
        try:
            resp = client.request(method, url, **kw)
        except httpx.HTTPError as exc:
            if last:
                raise ConnectorError(f"{service} could not be reached ({type(exc).__name__}); the next run tries again.") from None
            sleep(2 * (attempt + 1))
            continue
        if resp.status_code == 429:
            try:
                wait = float(resp.headers.get("retry-after", 5))
            except ValueError:
                wait = 5.0
            if last or wait > LONGEST_WAIT:
                raise ConnectorError(f"{service}'s rate limit was reached; the next run carries on.")
            sleep(wait)
            continue
        if resp.status_code >= 500 and not last:
            sleep(2 * (attempt + 1))
            continue
        if resp.status_code in (401, 403):
            raise ConnectorError(f"{service} refused the key ({resp.status_code}): {refused}.")
        if resp.status_code != 200:
            said = bad(resp) if bad else None
            raise ConnectorError(said or f"{service} answered {resp.status_code}; the next run tries again.")
        return json_of(resp, service, kinds)


def utc(text: str | None) -> str | None:
    """Any ISO time (Jira's +0200 offsets, Linear's milliseconds) as UTC with a Z."""
    if not text:
        return None
    try:
        return iso(datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc))
    except ValueError:
        return None


def std_type(name: str | None) -> str:
    """DevLake's standard issue types from a tracker's own type or label names."""
    low = (name or "").lower()
    if "incident" in low:
        return "INCIDENT"
    if "bug" in low or "defect" in low:
        return "BUG"
    if any(w in low for w in ("story", "feature", "epic", "requirement", "improvement")):
        return "REQUIREMENT"
    return "TASK"
