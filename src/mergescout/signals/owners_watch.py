"""Who can publish each package, watched daily: npm maintainers and the publisher of the latest release (and whether it came
through trusted CI publishing), PyPI owners and organization. Registries keep no history of this; the changes are the
signal (a takeover usually starts with a new maintainer or a release published outside the usual CI). Emails are never kept."""
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import quote

from mergescout.signals.deps_map import http_get_json

MAX_EVENTS = 20


def _snapshot(eco: str, name: str, version: str | None, get_json) -> dict | None:
    if eco == "npm":
        d = get_json(f"https://registry.npmjs.org/{quote(name, safe='@')}/latest")
        if not d:
            return None
        user = d.get("_npmUser") or {}
        trusted = bool(user.get("trustedPublisher") or (d.get("dist") or {}).get("attestations"))
        return {"version": d.get("version"), "publisher": user.get("name"), "trusted": trusted,
                "maintainers": sorted(m.get("name") for m in d.get("maintainers") or [] if m.get("name"))}
    if eco == "pypi" and version:
        d = get_json(f"https://pypi.org/pypi/{quote(name, safe='')}/{quote(version, safe='')}/json")
        if not d:
            return None
        own = d.get("ownership") or {}
        return {"version": version, "organization": own.get("organization"),
                "maintainers": sorted(r.get("user") for r in own.get("roles") or [] if r.get("user"))}
    return None


def _events(old: dict, new: dict, day: str) -> list[dict]:
    out = []
    added = sorted(set(new.get("maintainers") or []) - set(old.get("maintainers") or []))
    removed = sorted(set(old.get("maintainers") or []) - set(new.get("maintainers") or []))
    if added:
        out.append({"kind": "maintainer_added", "date": day, "who": added})
    if removed:
        out.append({"kind": "maintainer_removed", "date": day, "who": removed})
    if old.get("trusted") and new.get("trusted") is False:
        out.append({"kind": "trusted_lost", "date": day, "version": new.get("version")})
    if old.get("publisher") and new.get("publisher") and old["publisher"] != new["publisher"]:
        out.append({"kind": "publisher_changed", "date": day, "from": old["publisher"], "to": new["publisher"]})
    if old.get("organization") != new.get("organization") and ("organization" in old or "organization" in new):
        out.append({"kind": "organization_changed", "date": day, "from": old.get("organization"), "to": new.get("organization")})
    return out


def refresh_owners(packages: list[tuple[str, str, str | None]], previous: dict, now: datetime, get_json=http_get_json,
                   workers: int = 16, budget_s: float = 900) -> dict:
    """Today's snapshot per package and the dated changes since watching began; a package not read today (an error or
    the time budget) keeps yesterday's entry and gets no event."""
    day = now.strftime("%Y-%m-%d")
    deadline = time.time() + budget_s
    old = previous.get("packages") or {}

    def read(item):
        eco, name, version = item
        if time.time() > deadline:
            return None
        try:
            return _snapshot(eco, name, version, get_json)
        except Exception:  # noqa: BLE001
            return None
    with ThreadPoolExecutor(workers) as pool:
        snaps = list(pool.map(read, packages))
    out = {}
    for (eco, name, _), snap in zip(packages, snaps):
        key, before = f"{eco}:{name}", old.get(f"{eco}:{name}")
        if snap is None:
            if before:
                out[key] = before
            continue
        if before:
            events = (before.get("events") or []) + _events(before.get("current") or {}, snap, day)
            out[key] = {"current": snap, "since": before.get("since", day), "events": events[-MAX_EVENTS:]}
        else:
            out[key] = {"current": snap, "since": day, "events": []}
    return {"built_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "packages": out}
