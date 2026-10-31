"""Read one source again from a date: CI Health's runs, Team Flow's pull requests or a connected service. What was kept
stays; records read again replace theirs by id, so nothing is counted twice."""
from datetime import date, datetime
from pathlib import Path

# Names people use for the two GitHub sources.
CI, FLOW = {"ci", "ci health", "runs"}, {"flow", "team flow", "prs", "pull requests"}


def rewind(root: Path, source: str, since: str | None, now: datetime) -> str:
    """Make the next collection of `source` read again from `since` (None: its whole window); a sentence saying what."""
    from stackvitals.connectors import ConnectorError, rewind as rewind_connector
    name = source.strip().lower()
    day = date.fromisoformat(since) if since else None
    if day and day > now.date():
        raise ConnectorError(f"{since} is in the future; pick a past date to read again from.")
    if name in CI:
        from stackvitals.ci.store import DataStore
        store = DataStore(root)
        state = store.state()
        # Days marked done are listed again; runs already kept are skipped, so only missing ones are fetched.
        for key in ("scanned", "scanned_tests"):
            state[key] = {d: v for d, v in (state.get(key) or {}).items() if day and d < day.isoformat()}
        store.save_state(state)
        return f"CI Health reads its runs again from {day.isoformat() if day else 'the start of its window'}."
    if name in FLOW:
        from stackvitals.flow.store import FlowStore
        store = FlowStore(root)
        state = {k: v for k, v in store.state().items() if k != "synced_up_to"}
        if day:
            state["synced_up_to"] = f"{day.isoformat()}T00:00:00Z"
        store.save_state(state)
        return (f"Team Flow reads pull requests updated since {day.isoformat()} again." if day else
                "Team Flow reads its whole window of pull requests again.")
    return rewind_connector(root, name.replace(".", "_") if name == "incident.io" else name, since, now)
