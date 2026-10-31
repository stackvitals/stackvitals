"""Connectors to outside services, each read with one optional key from the repo's secrets: the Action's Connectors step,
the status the Integrations page shows, and everything pulled so far for Delivery to join."""
import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from stackvitals.connectors import ai_spend, copilot, discord, discourse, incident_io, jira, linear, pagerduty, slack, sonar
from stackvitals.connectors.base import BACKFILL_DAYS, ConnectorError
from stackvitals.connectors.store import ConnectorStore

CONNECTORS = {"jira": jira, "linear": linear, "pagerduty": pagerduty, "incident_io": incident_io, "copilot": copilot,
              "discourse": discourse, "slack": slack, "discord": discord, "ai_spend": ai_spend, "sonar": sonar}
NAMES = {"jira": "Jira", "linear": "Linear", "pagerduty": "PagerDuty", "incident_io": "incident.io", "copilot": "Copilot",
         "discourse": "Discourse", "slack": "Slack", "discord": "Discord", "ai_spend": "AI spend",
         "sonar": "SonarQube"}
TRACKERS = ("jira", "linear", "pagerduty", "incident_io")
COPILOT_WINDOW = 28
WARN_DAYS = 14


def public(ws) -> bool:
    """Unless the repo is known to be private, its data branch is readable by anyone: no titles, links or names."""
    return not (ws.cache.get("repo_info") or {}).get("private")


def active(env: dict, cfg: dict) -> list[str]:
    """The trackers and pager tools with a key in this job: one whose key was removed stops counting."""
    return [name for name in TRACKERS if name in CONNECTORS and CONNECTORS[name].configured(env, cfg)]


def load(root: Path, redact: bool = False, names=TRACKERS) -> dict | None:
    """Everything the named connectors pulled: {"sources", "issues", "changes", "sprints"}, or None before the first pull."""
    out = {"sources": [], "issues": [], "changes": [], "sprints": []}
    for name in (n for n in TRACKERS if n in names):
        got = ConnectorStore(root, name, redact).load()
        got = getattr(CONNECTORS.get(name), "finish", lambda g: g)(got)
        if got["issue"] or got["sprint"]:
            out["sources"].append(name)
            out["issues"] += got["issue"]
            out["changes"] += got["change"]
            out["sprints"] += got["sprint"]
    return out if out["sources"] else None


# What a record holds; a new field (2: an issue's epic or project, 3: its assignee, 4: its name) reads everything again once.
RECORDS = 4


def fingerprint(cfg: dict, name: str, redact: bool, records: int | None = None) -> str:
    """What decides which records a connector keeps: its read settings (not the key's expiry or write-back), whether
    titles are hidden, and what a record holds (records=0 leaves that out: what decides which answers are read)."""
    kept = {k: v for k, v in cfg["connectors"][name].items() if k not in ("key_expires", "write_back", "done_transition", "done_state")}
    shape = RECORDS if records is None else records
    # ASKED counts what a connector asks its service for: kept answers from before a new field can't be rebuilt from.
    asked = getattr(CONNECTORS.get(name), "ASKED", 1)
    return hashlib.sha1(json.dumps([kept, redact, *([shape] if shape else []), *([asked] if asked > 1 else [])],
                                   sort_keys=True).encode()).hexdigest()[:12]


# What the framework keeps in a connector's state across a rewind (connectors_step's own keys).
KEEP = ("scope", "reads", "raw_full")


def rewind(root: Path, name: str, since: str | None, now: datetime) -> str:
    """Make a connector's next pull read again from `since` (a date; None or older than the window means the whole
    window), keeping its records; a sentence saying what will happen."""
    if name not in CONNECTORS:
        raise ConnectorError(f"{name!r} has nothing to read again; use one of {', '.join(CONNECTORS)}.")
    floor = (now - timedelta(days=BACKFILL_DAYS)).date()
    day = date.fromisoformat(since) if since else None
    if day and day > now.date():
        raise ConnectorError(f"{since} is in the future; pick a past date to read {NAMES[name]} again from.")
    store = ConnectorStore(root, name)
    kept = {k: v for k, v in store.state().items() if k in KEEP}
    whole = day is None or day <= floor or name in ("slack", "discord", "discourse")
    if name == "copilot":
        new = {} if whole else {"through": (day - timedelta(days=1)).isoformat()}
    elif whole:
        new = {}
    else:
        start = f"{day.isoformat()}T00:00:00Z"
        new = {"since": start, **({"incident_since": start} if name == "jira" else {})}
    store.save_state({**kept, **new})
    return f"{NAMES[name]} reads again from {'180 days back' if whole else day.isoformat()}."


def reprocess(root: Path, name: str, day: str | None = None) -> int:
    """Rebuild a connector's records from the answers it kept, with no call to the service; the records written."""
    mod, store = CONNECTORS[name], ConnectorStore(root, name)
    kept = list(store.raw())
    if not kept or not hasattr(mod, "extract"):
        raise ConnectorError(f"{NAMES[name]} kept no answers to rebuild from; it reads them again instead.")
    store.clear_records()
    day = day or date.today().isoformat()
    written = 0
    for entry in kept:
        records = mod.extract(entry["k"], entry["c"], entry["b"])
        store.add(records, day)
        written += len(records)
    return written


def copilot_summary(root: Path, now: datetime) -> dict | None:
    """The last 28 days of the org's Copilot reports and this repo's: active users, suggestions accepted, Copilot's pull
    requests; None before the first report."""
    got = ConnectorStore(root, "copilot").load()
    days = sorted(got.get("org_day") or [], key=lambda d: d["day"])
    if not days:
        return None
    since = (now.date() - timedelta(days=COPILOT_WINDOW)).isoformat()
    recent = [d for d in days if d["day"] >= since] or days[-1:]
    repo = [d for d in got.get("repo_day") or [] if d["day"] >= since]
    total = lambda rows, k: sum((r.get("pull_requests") or {}).get(k) or 0 for r in rows)  # noqa: E731
    gen = sum(d.get("code_generation_activity_count") or 0 for d in recent)
    acc = sum(d.get("code_acceptance_activity_count") or 0 for d in recent)
    latest = recent[-1]
    return {"org": latest.get("org"), "days_kept": len(days), "first_day": days[0]["day"], "last_day": latest["day"],
            "monthly_active_users": latest.get("monthly_active_users"), "monthly_active_agent_users": latest.get("monthly_active_agent_users"),
            "acceptance": round(acc / gen, 4) if gen else None,
            "org_prs_by_copilot": total(recent, "total_created_by_copilot"),
            "org_prs_merged_by_copilot": total(recent, "total_merged_created_by_copilot"),
            "repo_prs_by_copilot": total(repo, "total_created_by_copilot"),
            "repo_prs_merged_by_copilot": total(repo, "total_merged_created_by_copilot"), "window_days": COPILOT_WINDOW}


def _write_back(ws, name: str, store, env: dict, cfg: dict, now: datetime, client=None) -> dict:
    """Opt-in: comment on (and move) the Jira or Linear issues that newly merged pull requests name. The pairs are picked
    and recorded before the data branch is saved and sent after it, so a retried push never sends them twice."""
    import base64

    import httpx

    from stackvitals.connectors import jira, linear, writeback
    from stackvitals.flow.store import FlowStore
    c = cfg["connectors"][name]
    prs = (ws.cache.get("flow") or FlowStore(ws.path).load()).get("closed") or []
    pairs = writeback.plan(store, prs, now.strftime("%Y-%m-%dT%H:%M:%SZ"))
    if not pairs:
        return {"planned": 0}

    def after_commit():
        http = client or (httpx.Client(base_url=c["url"], timeout=30, follow_redirects=False) if name == "jira"
                          else httpx.Client(timeout=30))
        try:
            if name == "jira":
                email = (env.get(jira.EMAIL_ENV) or "").strip() or c["email"]
                auth = "Basic " + base64.b64encode(f"{email}:{env.get(jira.TOKEN_ENV, '').strip()}".encode()).decode()
                got = writeback.send(pairs, ws.repo, lambda i, text: writeback.jira_comment(http, auth, i["key"], text),
                                     lambda i: writeback.jira_move(http, auth, i["key"], c["done_transition"]))
            else:
                key = env.get(linear.TOKEN_ENV, "").strip()
                got = writeback.send(pairs, ws.repo, lambda i, text: writeback.linear_comment(http, key, i["id"], text),
                                     lambda i: writeback.linear_move(http, key, i["id"], i["key"], c["done_state"]))
        finally:
            if client is None:
                http.close()
        lines = [f"{NAMES[name]} write-back: {got['wrote']} comment(s), {got['moved']} issue(s) moved."]
        if got["refused"]:
            lines.append(f"Writing stopped ({got['refused']}); the rest of this run's {len(pairs)} aren't retried. "
                         "Give the key permission to comment, or set write_back = false.")
        lines += [f"Not moved: {u}" for u in got["unmoved"][:3]]
        summary = env.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as f:
                f.write("\n\n".join(lines) + "\n")
        ws.cache.setdefault("write_back", {})[name] = got
    ws.after_commit(after_commit, f"{NAMES[name]} write-back")
    return {"planned": len(pairs)}


def connectors_step(ws, env: dict, now: datetime, clients: dict | None = None) -> dict | None:
    """Pull every connector with a key; a refused key or a missing setting is said on the Integrations page and in the job
    summary, and what was pulled before stays."""
    from stackvitals.core.config import parse
    from stackvitals.core.store import published, write_if_changed
    cfg = ws.cache.get("settings") or parse("")[0]
    try:
        old = json.loads((ws.path / "docs" / "connectors.json").read_text(encoding="utf-8")).get("connectors") or {}
    except (OSError, ValueError):
        old = {}
    status, results = {}, {}
    for name, mod in CONNECTORS.items():
        if not mod.configured(env, cfg):
            continue
        store, before = ConnectorStore(ws.path, name, redact=public(ws)), old.get(name) or {}
        scope, reads = fingerprint(cfg, name, public(ws)), fingerprint(cfg, name, public(ws), records=0)
        state = store.state()
        if state.get("scope", scope) != scope and state.get("reads") == reads and state.get("raw_full") \
                and hasattr(mod, "extract"):
            # Only what a record holds changed, and every answer was kept: rebuild from them instead of asking again.
            reprocess(ws.path, name, now.date().isoformat())
            store = ConnectorStore(ws.path, name, redact=public(ws))
            ws.notes.append(f"{NAMES[name]}: what StackVitals keeps changed, so its records were rebuilt from the answers "
                            "it kept, with no new reads.")
        elif state.get("scope", scope) != scope:
            # Narrower settings must drop what they now leave out, wider ones read back; a repo gone public loses titles.
            store.reset()
            ws.notes.append(f"{NAMES[name]}: its settings, the repo's visibility or what StackVitals keeps changed, so it "
                            "reads everything again "
                            f"({BACKFILL_DAYS} days back).")
        expires = cfg["connectors"][name].get("key_expires") or None
        entry = {"name": NAMES[name], "as_of": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "key_expires": expires,
                 "scope": getattr(mod, "scope", lambda cfg: None)(cfg),
                 "expiring": bool(expires and date.fromisoformat(expires) - now.date() <= timedelta(days=WARN_DAYS)),
                 **({"check": before["check"]} if before.get("check") else {})}  # the last Test connection result stays
        # Every answer is kept from the first read on (private repos only), or a rebuild would miss the older ones.
        full = not public(ws) and hasattr(mod, "extract") and (store.state().get("raw_full") or not store.days.is_dir())
        try:
            got = mod.pull(store, env, cfg, now, client=(clients or {}).get(name))
            if cfg["connectors"][name].get("write_back"):
                entry["write_back"] = _write_back(ws, name, store, env, cfg, now, (clients or {}).get(name))
            elif store.state().get("write_since"):
                store.save_state({k: v for k, v in store.state().items() if k != "write_since"})
            store.save_state({**{k: v for k, v in store.state().items() if k != "raw_full"}, "scope": scope, "reads": reads,
                              **({"raw_full": True} if full else {})})
            store.compress(now.date().isoformat())
            rows = {k: len(v) for k, v in store.load().items()}
            entry.update(error=None, rows=rows, complete=got["complete"])
            results[name] = {"read": got["read"], "complete": got["complete"], "error": None}
            if got.get("note"):
                ws.notes.append(f"{NAMES[name]}: {got['note']}")
        except Exception as exc:  # a bug or an answer no one expected stops this connector, never the whole job
            said = str(exc) if isinstance(exc, ConnectorError) else \
                f"stopped on an unexpected {type(exc).__name__}; what was pulled before stays, and the next run tries again."
            entry.update(error=said, rows=before.get("rows") or {}, complete=before.get("complete"))
            results[name] = {"read": 0, "complete": False, "error": said}
            ws.notes.append(f"{NAMES[name]}: {said}")
        if entry["expiring"]:
            ws.notes.append(f"{NAMES[name]}: the key expires on {expires}; create a new one and update the secret.")
        status[name] = entry
    if not status:
        return None
    # Tested services that aren't pulled (chat webhooks, the bucket, model triage) keep their last check.
    status.update({n: {"name": e.get("name"), "check": e["check"]} for n, e in old.items()
                   if n not in CONNECTORS and isinstance(e, dict) and e.get("check")})
    docs = ws.path / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    write_if_changed(docs / "connectors.json", published({"connectors": status}))
    ws.cache["tracker"] = load(ws.path, redact=public(ws), names=active(env, cfg))
    return results


__all__ = ["CONNECTORS", "ConnectorError", "active", "connectors_step", "copilot_summary", "load", "reprocess"]
