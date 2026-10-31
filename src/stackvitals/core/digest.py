"""The weekly digest: what changed since last week in each module that ran, what to fix first, and which decisions reach
their review date soon, as one short message posted where people already look (a comment on one pinned issue, so
GitHub's own notifications deliver it, and the chat webhook). Nobody is pinged and item names can't break the Markdown."""
import html
import os
from datetime import date, datetime, timedelta

from stackvitals.core import changes

TOP = 3


def _code(text) -> str:
    # An item name as inline code that nothing inside it can break out of.
    return "`" + " ".join(str(text).replace("`", "'").split()) + "`"


def _quiet(text) -> str:
    # Free text (titles, reasons) that can't ping anyone, become a link or start Markdown.
    out = html.escape(" ".join(str(text).split()), quote=False)
    for ch in "\\*_[]()#|":
        out = out.replace(ch, "\\" + ch)
    return out.replace("@", "@​").replace("www.", "www​.").replace("://", ":​//")


def _pct(x) -> str:
    return f"{x:.0%}"


def _moved(c: dict) -> str:
    # One change that survived the scan, in words: "pickup rose to 30.0 h from 3.0 h (medians, n 6 and 20)".
    verb = "rose" if c["direction"] == "up" else "fell"
    if c["unit"] == "share":
        return f"{c['label']} {verb} to {_pct(c['now'])} from {_pct(c['base'])} (n {c['n_now']} and {c['n_base']})"
    if c["unit"] == "count":
        return f"{c['label']} {verb} to {c['now']} from {c['base']:g} a week"
    return f"{c['label']} {verb} to {c['now']:.1f} {c['unit']} from {c['base']:.1f} {c['unit']} (medians, n {c['n_now']} and {c['n_base']})"


def _could_see(checked: list[dict]) -> str:
    # When review times held steady, how big a change this week's PRs could have shown (so "steady" isn't oversold).
    run = sum(1 for c in checked if c.get("note") is None)
    times = [(changes.detectable(c, run), c) for c in checked if c["metric"] in ("delivery.pickup", "delivery.cycle_to_merge")
             and c.get("note") is None]
    times = [(f, c) for f, c in times if f]
    if not times or any(c["changed"] for c in checked if c["metric"].startswith(("delivery.pickup", "delivery.cycle"))):
        return ""
    f, c = min(times, key=lambda x: x[0])
    size = f"{f:.0f}" if f >= 3 else f"{f:.1f}"
    return (f"; with {c['n_now']} PRs merged this week, review times would have had to change about {size}× to "
            "stand out")


def _verdict(name: str, c: dict) -> str | None:
    # One like-with-like comparison in words: "reverted more often (+8 points, likely +2 to +14)".
    if not c or c.get("verdict") in (None, "too few"):
        return None
    if c["verdict"] == "no measurable difference":
        return f"{name}: no measurable difference (it could detect {round(c['detectable'] * 100)} points or more)"
    pts = lambda x: f"{x * 100:+.0f}"  # noqa: E731
    return f"{name} {'more' if c['verdict'] == 'higher' else 'less'} often ({pts(c['gap'])} points, likely {pts(c['low'])} to {pts(c['high'])})"


def _ai_line(matched: dict, coverage: dict) -> str | None:
    """People's AI-marked PRs against the same authors' other PRs, and agents' PRs against people's of the same month and
    size; only comparisons with enough matched PRs, each with its verdict."""
    a = matched.get("assisted") or {}
    said = [v for v in (_verdict("reverted", a.get("reverted")), _verdict("CI failures", a.get("ci_failed"))) if v]
    agent = _verdict("merged by someone else", (matched.get("agent") or {}).get("merged_by_others"))
    if not said and not agent:
        return None
    text = "**AI-assisted work:**"
    if coverage.get("marked_share") is not None:
        text += (f" {_pct(coverage['marked_share'])} of people's merged PRs carry an AI marker "
                 f"({coverage.get('authors_marking', 0)} of {coverage.get('authors', 0)} authors).")
    if said:
        text += f" Against the same authors' other PRs: {'; '.join(said)}."
    if agent and "no measurable difference" in agent:
        text += f" Coding agents' PRs against people's PRs of the same month and size, {agent}."
    elif agent:
        text += f" Coding agents' PRs: {agent} than people's PRs of the same month and size."
    return text


def _flaky_keys(data: dict) -> list[str]:
    keys = [f"test {t['id']}" for t in data.get("tests") or [] if t.get("state") == "flaky"]
    keys += [f"job {(j.get('workflow') or '?').rsplit('/', 1)[-1]} / {j.get('job')}" for j in data.get("jobs") or []
             if j.get("state") == "flaky"]
    return sorted(keys)


def numbers(docs: dict) -> dict:
    """The figures next week's digest compares with."""
    data, delivery, flow = docs.get("data") or {}, docs.get("delivery") or {}, docs.get("flow") or {}
    phases = delivery.get("phases") or {}
    p75 = lambda name: (phases.get(name) or {}).get("p75_h")
    return {"first_try": (data.get("pushes") or {}).get("first_try_share") if data else None,
            "flaky": _flaky_keys(data) if data else [],
            "pickup_p75_h": p75("pickup"), "review_p75_h": p75("review"), "cycle_p75_h": p75("cycle_to_merge"),
            "deployments": (delivery.get("dora") or {}).get("deployments"), "open_prs": flow.get("open"),
            "newcomers": (docs.get("community") or {}).get("waiting_total")}


def due(state: dict, today: date, days: int = 7) -> list[dict]:
    """Decisions whose review date falls in the next `days` days, soonest first."""
    end = (today + timedelta(days=days)).isoformat()
    return sorted((v for v in state.values() if v.get("until") and today.isoformat() <= v["until"] <= end),
                  key=lambda v: v["until"])


def compose(repo: str, now: datetime, docs: dict, last: dict | None, decisions_due: list[dict],
            app_url: str | None) -> tuple[str, dict]:
    """(Markdown, numbers): this week's digest from the published JSON files, and what to compare against next week."""
    nums, before = numbers(docs), (last or {}).get("numbers") or {}
    week = (now.date() - timedelta(days=now.weekday())).isoformat()
    lines = [f"### StackVitals weekly digest: {_quiet(repo)}, week of {week}", ""]
    findings = (docs.get("insights") or {}).get("findings") or []
    # Findings someone snoozed or acknowledged stay off the list, as on the pages.
    aside = sum(1 for f in findings if f.get("decision"))
    found = sorted((f for f in findings if not f.get("decision")), key=lambda f: -(f.get("hours") or 0))[:TOP]
    if found:
        lines.append("**What to fix first**")
        lines += [f"{i}. {_quiet(f.get('title'))} ({f.get('hours') or 0:.1f} h at stake, n={f.get('n')})"
                  for i, f in enumerate(found, 1)]
        if aside:
            lines.append(f"({aside} set aside by a decision.)")
        lines.append("")
    checked = changes.flag([c for name in ("data", "delivery", "community") for c in (docs.get(name) or {}).get("changes") or []])
    run = [c for c in checked if c.get("note") is None and not c.get("shown_with")]
    if checked and not run:
        lines.append("**This week:** too few PRs, pushes or deployments to compare with the four weeks before.")
    elif run:
        moved = [_moved(c) for c in run if c["changed"]]
        held = len(run) - len(moved)
        tail = (f"{len(run)} number{'' if len(run) == 1 else 's'} checked against the four weeks before; "
                + (f"the other {held} held steady within noise" if moved else "all held steady within noise"))
        tail += _could_see(run)
        lines.append(f"**This week:** {'; '.join(moved)}. {tail}." if moved else f"**This week:** {tail}.")
    if docs.get("data"):
        part = f"first-try green {_pct(nums['first_try'])}" if nums["first_try"] is not None else "first-try green: not enough runs"
        if last:
            new = [k for k in nums["flaky"] if k not in set(before.get("flaky") or [])]
            gone = [k for k in before.get("flaky") or [] if k not in set(nums["flaky"])]
            if new:
                part += "; newly flaky: " + ", ".join(_code(k.split(" ", 1)[1]) for k in new[:5]) + (
                    f" and {len(new) - 5} more" if len(new) > 5 else "")
            if gone:
                part += f"; {len(gone)} recovered"
        else:
            part += f"; {len(nums['flaky'])} flaky now"
        lines.append(f"**CI:** {part}.")
    if docs.get("delivery"):
        parts = []
        for key, label in (("pickup_p75_h", "pickup P75"), ("review_p75_h", "review P75"), ("cycle_p75_h", "cycle to merge P75")):
            value = nums[key]
            parts.append(f"{label} not enough data" if value is None else f"{label} {value:.1f} h")
        dora = docs["delivery"].get("dora") or {}
        shipped = dora.get("deployments") or 0
        tail = (f"; {shipped} deployment{'' if shipped == 1 else 's'} in {docs['delivery'].get('window_days', 90)} days"
                if docs["delivery"].get("deploy_source") else "; no deployment source found yet")
        if dora.get("change_failure_rate") is not None:
            tail += f"; change failure {_pct(dora['change_failure_rate'])}"
        if dora.get("rework_rate") is not None:
            tail += f"; rework {_pct(dora['rework_rate'])}"
        lines.append(f"**Delivery:** {', '.join(parts)}{tail}.")
        ai = (docs["delivery"].get("ai") or {}).get("outcomes") or {}
        line = _ai_line(ai.get("matched") or {}, ai.get("coverage") or {})
        if line:
            lines.append(line)
        agreed = docs["delivery"].get("agreements")
        if agreed:
            n = len(agreed.get("exceptions") or [])
            each = "; ".join(f"{_quiet(label)}: {agreed['counts'].get(rule, 0)}" for rule, label in agreed["labels"].items())
            lines.append(f"**Working agreements:** {n} exception{'' if n == 1 else 's'} in the last "
                         f"{agreed.get('window_days', 14)} days ({each}).")
    if docs.get("flow"):
        n_open, stale = docs["flow"].get("open") or 0, docs["flow"].get("stale") or 0
        lines.append(f"**Pull requests:** {n_open} open pull request{'' if n_open == 1 else 's'}, {stale} stale.")
    deps = docs.get("deps")
    if deps:
        parts = []
        if deps.get("open"):
            n, oldest = len(deps["open"]), max(u["age_hours"] for u in deps["open"]) / 24
            parts.append(f"{n} update pull request{'' if n == 1 else 's'} open (the oldest {oldest:.0f} days)")
        if deps.get("security_overdue"):
            n = len(deps["security_overdue"])
            parts.append(f"{n} security update{'' if n == 1 else 's'} waiting over 48 h")
        if (deps.get("quiet_days") or 0) >= 30:
            parts.append(f"no update pull request from {' or '.join(deps.get('bots') or ['the bot'])} for {deps['quiet_days']} "
                         "days (Dependabot pauses after 90 days without interaction)")
        if parts:
            lines.append(f"**Dependencies:** {'; '.join(parts)}.")
    if docs.get("community"):
        waiting = docs["community"].get("waiting_total") or 0
        lines.append(f"**Community:** {waiting} newcomer{'' if waiting == 1 else 's'} waiting for a first answer."
                     if waiting else "**Community:** no newcomer waiting for a first answer.")
    if decisions_due:
        lines += ["", "**Decisions to review**"]
        lines += [f"- {d['verb']} of {_code(d['id'])} ends {d['until']} (by {_code(d.get('by') or '?')}"
                  + (f": {_quiet(d['reason'])}" if d.get("reason") else "") + ")" for d in decisions_due]
    if app_url:
        lines += ["", f"[Open StackVitals]({app_url})"]
    return "\n".join(lines).strip() + "\n", nums


TITLE = "StackVitals weekly digest"
LABEL = "stackvitals"
INTRO = ("StackVitals posts a short digest here every week: what changed in CI, delivery and pull requests, what to fix "
         "first, and which decisions end soon. Subscribe to this issue to get it by e-mail or in GitHub. Change the day, "
         "hour or channels under `[digest]` in `.github/stackvitals.toml`, or turn it off with `enabled = false`.")
FILES = (("data", "data.json"), ("flow", "flow.json"), ("delivery", "delivery.json"), ("insights", "insights.json"),
         ("community", "community.json"), ("deps", "deps.json"))
EVENTS = ("schedule", "workflow_dispatch")
CATCH_UP = timedelta(hours=12)


def slot(now: datetime, day: int, hour: int) -> tuple[str, datetime] | None:
    """(ISO week, time) of the digest due now: this week's slot once reached, or last week's when missed by under 12
    hours (a Sunday-night slot falls after the week's last run); None when nothing is due."""
    start = datetime(now.year, now.month, now.day, tzinfo=now.tzinfo) - timedelta(days=now.weekday())
    at = start + timedelta(days=day, hours=hour)
    if now < at:
        at -= timedelta(days=7)
        if now - at > CATCH_UP:
            return None
    year, week, _ = at.isocalendar()
    return f"{year}-W{week:02d}", at


def _read(path):
    import json
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _issue(api, repo: str) -> int:
    """The digest issue: the open one with its title and label, else a new one, pinned when GitHub allows it."""
    found = [i for i in api._get(f"/repos/{repo}/issues", {"labels": LABEL, "state": "open", "per_page": 100}) or []
             if i.get("title") == TITLE and "pull_request" not in i]
    if found:
        return found[0]["number"]
    made = api.send("POST", f"/repos/{repo}/issues", {"title": TITLE, "body": INTRO, "labels": [LABEL]})
    try:
        from stackvitals.ci.api import GRAPHQL
        api.client.post(GRAPHQL, headers=api.headers, json={
            "query": "mutation($id: ID!) { pinIssue(input: {issueId: $id}) { issue { number } } }",
            "variables": {"id": made.get("node_id")}})
    except Exception:  # noqa: BLE001 - an unpinned digest still works
        pass
    return made["number"]


def digest_step(ws, env: dict, now: datetime, make_api=None, client=None) -> dict | None:
    """Once per ISO week, on the first scheduled run at or after the repo's day and hour: the digest from the pages this
    job just wrote, saved as sent before the commit and posted after it."""
    import json

    from stackvitals.core import chat
    from stackvitals.core.config import DAYS, parse
    from stackvitals.core.decisions import Store
    from stackvitals.core.time import iso
    cfg = (ws.cache.get("settings") or parse("")[0])["digest"]
    if not cfg["enabled"] or env.get("GITHUB_EVENT_NAME") not in EVENTS:
        return None
    due_slot = slot(now, DAYS.index(cfg["day"]), cfg["hour"])
    path = ws.path / "digest" / "last.json"
    last = _read(path)
    if due_slot is None or (last or {}).get("week") == due_slot[0]:
        return None
    week_id = due_slot[0]
    docs = {name: _read(ws.path / "docs" / file) for name, file in FILES}
    if not any(docs.values()):
        return None
    if make_api is None:
        from stackvitals.ci.api import ActionsAPI as make_api
    api = make_api(env.get("STACKVITALS_TOKEN") or env.get("GITHUB_TOKEN"), ws.repo, max_requests=20)
    try:
        info = api._get(f"/repos/{ws.repo}")
    except Exception:  # noqa: BLE001 - without the link the digest still says everything
        info = {}
    owner, name = ws.repo.split("/")
    app_url = f"https://{owner.lower()}.github.io/{name}/" if info.get("has_pages") and not info.get("private") else None
    text, numbers = compose(ws.repo, due_slot[1], docs, last, due(Store(ws.path).state(now.date()), now.date()), app_url)
    # Last week's pulse, counted from reactions in the digest issue (read before the commit; nothing about who answered).
    pulse = cfg.get("pulse") and "issue" in cfg["channels"]
    if pulse and last and last.get("week"):
        from stackvitals.core.pulse import record, section, tally
        try:
            keep = None
            if not info.get("private"):
                # Anyone can react on a public repo: count only the team's own people.
                from stackvitals.core.actors import People
                from stackvitals.flow.store import FlowStore
                flow = ws.cache.get("flow") or FlowStore(ws.path).load()
                people = People((flow.get("closed") or []) + (flow.get("open") or []))
                keep = lambda login: people.role(login) == "insider"  # noqa: E731
            counts = tally(api, _issue(api, ws.repo), last["week"], since=last.get("sent"), keep=keep)
            record(ws.path, last["week"], counts)  # the week's counts for the app's trend; never who answered
            line = section(counts)
        except Exception:  # noqa: BLE001 - the digest goes out without it
            line = None
        if line:
            text = f"{text}\n\n{line}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"week": week_id, "sent": iso(now), "numbers": numbers}, indent=1), encoding="utf-8")
    notes = []

    def send():
        if "issue" in cfg["channels"]:
            try:
                api.send("POST", f"/repos/{ws.repo}/issues/{_issue(api, ws.repo)}/comments", {"body": text})
                if pulse:
                    from stackvitals.core.pulse import ask
                    ask(api, _issue(api, ws.repo), week_id)
            except Exception as exc:  # noqa: BLE001 - reported, never fails the job
                notes.append(f"Could not post the weekly digest ({type(exc).__name__}); it needs `issues: write`.")
        if "webhook" in cfg["channels"] and env.get("STACKVITALS_WEBHOOK"):
            lines = [x for x in text.splitlines() if x.strip()]
            body = [x for x in lines[1:] if not x.startswith("[Open StackVitals]")]
            msg = chat.message(lines[0].lstrip("# ").strip(), body, [("Open StackVitals", app_url)] if app_url else [],
                               {"repo": ws.repo, "week": week_id})
            failed = chat.post(env["STACKVITALS_WEBHOOK"], msg, client, "the digest webhook")
            if failed:
                notes.append(failed)
        summary = env.get("GITHUB_STEP_SUMMARY")
        if summary and notes:
            with open(summary, "a", encoding="utf-8") as f:
                f.write("### StackVitals digest\n" + "\n".join(notes) + "\n")
    if not os.environ.get("STACKVITALS_READ_ONLY"):  # a local read-only run sends nothing anywhere
        ws.after_commit(send, "Digest")
    return {"week": week_id, "channels": list(cfg["channels"])}
