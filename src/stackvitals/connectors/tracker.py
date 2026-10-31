"""What tracker issues add to delivery: PRs linked to issues by key, lead and cycle time by issue type, sprint scope and
carry-over, and the incidents a tracker holds."""
import re
from collections import defaultdict
from datetime import datetime

from stackvitals.core.stats import percentile
from stackvitals.core.time import iso, parse

KEY = re.compile(r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9]{1,9})-(\d{1,7})(?![0-9])")
# A status no current issue holds is guessed from its name.
BUSY = re.compile(r"(?i)progress|review|doing|started|develop|testing|qa\b")
SPRINTS_SHOWN = 6


def pr_links(prs: list[dict], issues: list[dict]) -> list[tuple[int, str]]:
    """(PR number, issue key) for every known issue key in a PR's title or head branch (any case: feature/web-12-x)."""
    known = {i["key"].upper(): i["key"] for i in issues}
    out = []
    for p in prs:
        found = []
        for text in (p.get("ti") or "", p.get("head") or ""):
            for prefix, number in KEY.findall(text):
                key = known.get(f"{prefix.upper()}-{number}")
                if key and key not in found:
                    found.append(key)
        out += [(p["n"], key) for key in found]
    return out


def _hours(a: str | None, b: str | None) -> float | None:
    if not a or not b or b < a:
        return None
    return round((parse(b) - parse(a)).total_seconds() / 3600, 2)


def _stats(values: list[float], prefix: str, min_n: int = 10) -> dict:
    # Under ten issues the times are left out (the count stays): a P75 of three says little.
    v = [x for x in values if x is not None]
    return {f"{prefix}_n": len(v), f"{prefix}_p50_h": percentile(v, 0.5) if len(v) >= min_n else None,
            f"{prefix}_p75_h": percentile(v, 0.75) if len(v) >= min_n else None}


def lead_times(issues: list[dict], changes: list[dict], start: datetime, end: datetime, min_n: int = 10) -> dict:
    """{type: {n, lead_p50_h, lead_p75_h, cycle_n, cycle_p50_h, cycle_p75_h}} over issues done in the range: lead time from
    created, cycle time from the first move to an in-progress status; canceled ones are left out."""
    s, e = iso(start), iso(end)
    category = {i.get("status"): i.get("cat") for i in issues}
    started = {}
    for c in sorted((c for c in changes if c.get("field") == "status"), key=lambda c: c.get("at") or ""):
        busy = category.get(c.get("to")) == "IN_PROGRESS" or (c.get("to") not in category and BUSY.search(c.get("to") or ""))
        if busy:
            started.setdefault(c["issue"], c["at"])
    groups = defaultdict(list)
    for i in issues:
        if i.get("cat") == "DONE" and not i.get("canceled") and i.get("resolved") and s <= i["resolved"] <= e:
            groups[i.get("type") or "TASK"].append(i)
    out = {}
    for kind in sorted(set(groups) | {"REQUIREMENT", "BUG"}):
        rows = groups.get(kind, [])
        lead = _stats([_hours(i.get("created"), i["resolved"]) for i in rows], "lead", min_n)
        cycle = _stats([_hours(started.get(i["id"]), i["resolved"]) for i in rows], "cycle", min_n)
        out[kind] = {"n": len(rows), **{k: v for k, v in lead.items() if k != "lead_n"}, **cycle}
    return out


def incidents(issues: list[dict]) -> list[dict]:
    """A tracker's incidents in the shape Delivery's own incidents take, with a link to each."""
    return [{"source": i["src"], "number": i["key"], "created": i["created"],
             "resolved": i.get("resolved") if i.get("cat") == "DONE" else None, "url": i.get("url"),
             **({"severity": i["severity"]} if i.get("severity") else {})}
            for i in issues if i.get("incident") and i.get("created")]


def planning(issues: list[dict], changes: list[dict], sprints: list[dict], now: datetime, last: int = SPRINTS_SHOWN,
             since: datetime | None = None) -> list[dict]:
    """The last sprints or cycles, newest last: scope, done by the sprint's end, carried over (open when it closed), added
    after it started, and story points when the team uses them. Sprints that began before `since` (what the connector
    reads back to) are left out, since only some of their issues were read."""
    members = defaultdict(list)
    for i in issues:
        for sid in i.get("sprints") or []:
            members[sid].append(i)
    added = {}
    for c in changes:
        if c.get("field") == "sprint" and c.get("at"):
            for sid in set(c.get("to") or []) - set(c.get("from") or []):
                key = (c["issue"], sid)
                added[key] = min(added.get(key, c["at"]), c["at"])
    floor = iso(since) if since else ""
    shown = sorted((s for s in sprints if s.get("start") and s["start"] >= floor and s.get("state") in ("ACTIVE", "CLOSED")),
                   key=lambda s: s["start"])
    rows = []
    for s in shown[-last:]:
        scope = members.get(s["id"], [])
        end = s.get("complete") or (iso(now) if s["state"] == "ACTIVE" else s.get("end")) or iso(now)
        done = [i for i in scope if i.get("cat") == "DONE" and not i.get("canceled") and (i.get("resolved") or "9") <= end]
        carried = [i for i in scope if s["state"] == "CLOSED" and i not in done and not i.get("canceled")]
        late = [i for i in scope if (i["id"], s["id"]) in added and added[(i["id"], s["id"])] > s["start"]]
        pointed = any(i.get("points") is not None for i in scope)
        points = (lambda xs: sum(i.get("points") or 0 for i in xs)) if pointed else (lambda xs: None)
        # A public repo keeps no sprint names: the dates name it instead.
        name = s.get("name") or f"Sprint ending {(s.get('end') or '')[:10] or 'later'}"
        rows.append({"id": s["id"], "name": name, "state": s["state"], "start": s["start"],
                     "end": s.get("complete") or s.get("end"), "scope": len(scope), "done": len(done),
                     "carried_over": len(carried), "added_after_start": len(late), "points_scope": points(scope),
                     "points_done": points(done)})
    return rows
