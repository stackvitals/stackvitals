"""Changes people ask for on GitHub, applied by the Action at the start of the job: a request issue from the app (a fenced
```stackvitals block), `/stackvitals` commands in comments, a request handed to a manual run (the app's token mode), and
a flaky-test issue closed as not planned. Only people with the right access change anything (triage for decisions,
write for settings), every change is logged with who and why, and the answer goes on the issue after the data is saved."""
import base64
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

from stackvitals.ci.api import ActionsAPI, APIError, OutOfBudget
from stackvitals.core import decisions as dec
from stackvitals.core.config import FILE, parse
from stackvitals.core.digest import _code, _quiet
from stackvitals.core.time import iso
from stackvitals.core.tomledit import EditError, apply

EVENTS = ("issues", "issue_comment", "workflow_dispatch")
LEVELS = {"none": 0, "read": 0, "triage": 1, "write": 2, "maintain": 3, "admin": 4}
ITEMS = (("Flaky test: ", "test"), ("Flaky job: ", "job"))


def _item(title: str | None) -> tuple[str, str] | None:
    for prefix, kind in ITEMS:
        if (title or "").startswith(prefix):
            return kind, title[len(prefix):]
    return None


def seen_state(result: dict | None, kind: str, ident: str) -> dict | None:
    """What StackVitals said about a test or job in its newest published findings, kept with feedback on that verdict:
    its state and the verdict a failure of it would get now."""
    from stackvitals.ci.automation import job_key
    from stackvitals.ci.feedback import SAFE_FLAKES, _test_verdict, _verdict
    if not result:
        return None
    if kind == "test":
        item = next((t for t in result.get("tests") or [] if t.get("id") == ident), None)
        verdict = _test_verdict(item) if item else None
    else:
        jobs = result.get("jobs") or []
        # Exact names first; the pull request comment writes "<workflow display name> / <job>", so a unique job name
        # at the end matches too.
        item = (next((j for j in jobs if ident in (job_key(j), j.get("job"))), None)
                or (lambda found: found[0] if len(found) == 1 else None)([j for j in jobs if ident.endswith(f" / {j.get('job')}")]))
        verdict = _verdict(item) if item else None
        if verdict == "known flaky" and item.get("flake_events", 0) < SAFE_FLAKES:
            verdict = "flaked before"
    return {"state": item.get("state"), "flake_events": item.get("flake_events", 0), "verdict": verdict} if item else None


def _published(ws) -> dict | None:
    try:
        return json.loads((Path(ws.path) / "docs" / "data.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _payload(env: dict) -> dict:
    try:
        return json.loads(Path(env["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    except (KeyError, OSError, ValueError):
        return {}


def _level(api, login: str | None) -> int:
    if not login:
        return 0
    try:
        body = api._get(f"/repos/{api.repo}/collaborators/{login}/permission")
    except (APIError, OutOfBudget):
        return 0
    # The legacy field maps triage to read and maintain to write; role_name holds the real role.
    role = body.get("role_name")
    return LEVELS[role] if role in LEVELS else LEVELS.get(body.get("permission") or "none", 0)


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _get(cfg: dict, key: str):
    for part in key.split("."):
        cfg = cfg[part]
    return cfg


def _shown(value) -> str:
    return "(not set)" if value is None else json.dumps(value)


def _changes_line(before: dict, after: dict, keys) -> str:
    return "; ".join(f"{_code(k)}: {_code(_shown(_get(before, k)))} to {_code(_shown(_get(after, k)))}" for k in keys)


def _moves(before: dict, settings: dict) -> dict:
    # What changed per key for the log; a null in the request puts the default back.
    return {k: f"{_shown(_get(before, k))} to {'the default' if v is None else json.dumps(v)}" for k, v in settings.items()}


def _apply_settings(api, settings: dict, login: str, number: int | None, now: datetime) -> tuple[str, dict | None, dict]:
    """(answer, the new settings when they took effect now, what changed per key for the log): a commit on the default
    branch, else a branch with a pull request (or a link to open one) when the branch is protected."""
    info = api._get(f"/repos/{api.repo}")
    branch = info.get("default_branch") or "main"
    try:
        got = api._get(f"/repos/{api.repo}/contents/{FILE}", {"ref": branch})
        sha, text = got.get("sha"), base64.b64decode(got.get("content") or "").decode("utf-8")
    except APIError as exc:
        if "404" not in str(exc):
            raise
        sha, text = None, ""
    try:
        new = apply(text, settings)
    except EditError as exc:
        return f"Nothing was changed: {_quiet(exc)}", None, {}
    if new == text:
        return f"{FILE} already says that; nothing to change.", None, {}
    what = _changes_line(parse(text)[0], parse(new)[0], settings)
    moves = _moves(parse(text)[0], settings)
    proposed = {k: f"{m}, proposed in a pull request" for k, m in moves.items()}
    asked = f"asked in #{number}" if number else "asked from the StackVitals app"
    body = {"message": f"chore(stackvitals): Update settings ({asked} by {login})", "content": _b64(new), "branch": branch,
            **({"sha": sha} if sha else {})}
    try:
        api.send("PUT", f"/repos/{api.repo}/contents/{FILE}", body)
        return f"Changed in `{FILE}` on `{branch}`: {what}. It applies from this run.", parse(new)[0], moves
    except APIError as exc:
        if not any(code in str(exc) for code in ("409", "422", "403")):
            raise
    head = f"stackvitals/settings-{number or now.strftime('%Y%m%d%H%M%S')}"
    base = api._get(f"/repos/{api.repo}/git/ref/heads/{branch}")["object"]["sha"]
    try:
        api.send("POST", f"/repos/{api.repo}/git/refs", {"ref": f"refs/heads/{head}", "sha": base})
    except APIError:
        pass  # left by an earlier attempt of this same request
    api.send("PUT", f"/repos/{api.repo}/contents/{FILE}", {**body, "branch": head})
    title = f"Update StackVitals settings ({asked})"
    try:
        pr = api.send("POST", f"/repos/{api.repo}/pulls", {"title": title, "head": head, "base": branch,
                                                          "body": f"Settings change {asked} by {login}: {what}."})
        return f"`{branch}` is protected, so the change waits in a pull request: {pr.get('html_url')} ({what}).", None, proposed
    except APIError:
        link = f"https://github.com/{api.repo}/compare/{branch}...{head}?quick_pull=1"
        return (f"`{branch}` is protected and this repo doesn't let Actions open pull requests; open it here: {link} ({what}).",
                None, proposed)


def _decided(changes: list[dec.Decision]) -> str:
    words = {"quarantine": "quarantined", "unquarantine": "taken out of quarantine", "mute": "muted", "unmute": "unmuted",
             "acknowledge": "acknowledged", "snooze": "snoozed", "reopen": "reopened", "exclude": "excluded from the numbers",
             "include": "counted again", "accept": "accepted as a known risk",
             "confirm": "confirmed: StackVitals' verdict was right", "dispute": "disputed: StackVitals' verdict was wrong"}
    undo = {"quarantine": "unquarantine", "mute": "unmute", "snooze": "reopen", "acknowledge": "reopen", "exclude": "include",
            "accept": "reopen"}
    out = []
    for d in changes:
        line = f"{d.kind} {_code(d.id)} {words[d.verb]}" + (f" until {d.until}" if d.until else "")
        if d.reason:
            line += f" ({_quiet(d.reason)})"
        if d.verb in undo:
            line += f"; undo with `/stackvitals {undo[d.verb]} {d.kind}:{d.id.replace('`', '')}`"
        out.append("- " + line)
    return "\n".join(out)


SWEEP = "decisions/requests.json"
LOOKBACK = timedelta(hours=6)
TRUSTED = ("OWNER", "MEMBER", "COLLABORATOR")
DONE_MAX = 500


def _commanded(body: str | None) -> bool:
    return any(line.strip().lower().startswith("/stackvitals") for line in (body or "").splitlines())


def _missed(api, since: str, done: set) -> list[dict]:
    """Commands and request issues from people with access that no run applied (GitHub cancels a waiting run when a
    newer one queues): the newest comments and open issues since `since`, two requests."""
    out = []
    comments = api._get(f"/repos/{api.repo}/issues/comments", {"since": since, "sort": "created", "direction": "desc",
                                                               "per_page": 100}) or []
    for c in reversed(comments):
        key = f"comment:{c.get('id')}"
        if (key not in done and (c.get("created_at") or "") >= since and c.get("author_association") in TRUSTED
                and _commanded(c.get("body"))):
            number = int(str(c.get("issue_url") or "/0").rsplit("/", 1)[-1] or 0)
            out.append({"key": key, "kind": "comment", "number": number, "login": (c.get("user") or {}).get("login"),
                        "body": c.get("body") or ""})
    for i in reversed(api._get(f"/repos/{api.repo}/issues", {"state": "open", "since": since, "per_page": 100}) or []):
        key = f"issue:{i.get('number')}"
        if (key not in done and "pull_request" not in i and (i.get("created_at") or "") >= since
                and i.get("author_association") in TRUSTED and "```stackvitals" in (i.get("body") or "")):
            out.append({"key": key, "kind": "issue", "number": i["number"], "login": (i.get("user") or {}).get("login"),
                        "body": i.get("body") or ""})
    return out


def _from_event(event: str, payload: dict, env: dict) -> dict | None:
    issue = payload.get("issue") or {}
    if event == "issues" and payload.get("action") == "opened":
        return {"key": f"issue:{issue.get('number')}", "kind": "issue", "number": issue.get("number"),
                "login": (issue.get("user") or {}).get("login"), "body": issue.get("body") or ""}
    if event == "issue_comment" and payload.get("action") == "created":
        comment = payload.get("comment") or {}
        # On a flaky-test issue the command is about its test; on a pull request, about that pull request.
        default = _item(issue.get("title")) or (("pr", str(issue.get("number"))) if issue.get("pull_request") else None)
        return {"key": f"comment:{comment.get('id')}", "kind": "comment", "number": issue.get("number"),
                "login": (comment.get("user") or {}).get("login"), "body": comment.get("body") or "", "default": default}
    if event == "workflow_dispatch":
        raw = ((payload.get("inputs") or {}).get("request") or "").strip()
        if raw:
            return {"key": None, "kind": "dispatch", "number": None, "body": raw,
                    "login": (payload.get("sender") or {}).get("login") or env.get("GITHUB_ACTOR")}
    return None


APPROVE = "/stackvitals approve"
WAITING = "Waiting for approval:"


def approval_code(body: str | None) -> str:
    # Ties an approval to the request as it reads now: an edit to the issue changes the code, so the approval must be given again.
    return hashlib.sha256(" ".join(str(body or "").split()).encode()).hexdigest()[:8]


def _golden(env: dict, api, golden: dict, login: str, approver: str | None = None, body: str | None = None,
            issue: bool = True) -> str:
    """Runs a Portal golden path with the org App, from the portal repo's portal.toml; says what happened or why not. A
    path with `approvals = 1` waits until someone else with write access comments the approval."""
    from stackvitals.portal.golden import GoldenError, load_paths, run
    token = (env.get("STACKVITALS_PORTAL_TOKEN") or "").strip()
    if not token:
        return "Golden paths run with the Portal's org App (the portal-token input); nothing was run."
    try:
        paths = load_paths(api.file("portal.toml", None).decode("utf-8", "replace"))
    except (APIError, GoldenError, ValueError) as exc:
        return f"The golden paths in portal.toml couldn't be read ({_quiet(exc)}); nothing was run."
    path = paths.get(golden["path"])
    if not path:
        return f"portal.toml has no golden path {_code(golden['path'])}; nothing was run."
    if path.get("approvals") and not approver:
        if not issue:
            return (f"Golden path {_code(path['id'])} needs someone else's approval, given on a request issue: send it "
                    "from the app as a request (not \"run now\"); nothing was run.")
        return (f"{WAITING} golden path {_code(path['id'])} runs once someone else with write access to this repo "
                f"comments `{APPROVE} {approval_code(body)}` here (the code changes if the request is edited).")
    org = (env.get("STACKVITALS_PORTAL_ORG") or "").strip() or api.repo.split("/")[0]
    try:
        text, url = run(ActionsAPI(token, api.repo, max_requests=60), api, api.repo, org, path, golden["inputs"], login)
    except (GoldenError, APIError, OutOfBudget) as exc:
        return f"Golden path {_code(path['id'])} stopped: {_quiet(str(exc)[:200])}"
    return f"{text} {url}".strip()


def _approve(ws, api, store, item: dict, now: datetime, say, env: dict) -> dict:
    """`/stackvitals approve` on a waiting golden path request: someone with write access other than the requester lets it
    run, as the requester (whose own access the golden path still checks)."""
    number, approver = item.get("number"), item.get("login")
    issue = api._get(f"/repos/{api.repo}/issues/{number}") if number else {}
    requester = (issue.get("user") or {}).get("login")
    try:
        req = dec.parse_request(issue.get("body") or "", now.date())
    except dec.CommandError:
        req = None
    if not req or not req.golden or issue.get("state") != "open":
        say(number, "There is no golden path waiting for approval here; nothing was run.", None)
        return {"decisions": 0, "settings": False}
    if approver == requester:
        say(number, "A golden path needs someone other than the person who asked for it to approve; nothing was run.", None)
        return {"decisions": 0, "settings": False, "refused": True}
    if _level(api, approver) < 2 or _level(api, requester) < 2:
        say(number, "Approving needs write access to this repo, for both the approver and the requester; nothing was run.", None)
        return {"decisions": 0, "settings": False, "refused": True}
    given = (item.get("body") or "").strip()[len(APPROVE):].split()
    code = approval_code(issue.get("body"))
    if not given or given[0].lower() != code:
        say(number, f"The approval needs the request's current code: comment `{APPROVE} {code}` (it changes when the request "
                    "is edited, so what was read is what runs); nothing was run.", None)
        return {"decisions": 0, "settings": False, "refused": True}
    memo = getattr(ws, "memo", {})
    key = ("golden", f"approved:{number}")
    if key not in memo:
        memo[key] = _golden(env, api, req.golden, requester, approver=approver)
    store.record([dec.Decision("run", "golden", req.golden["path"], None, f"approved by {approver}: {memo[key][:180]}")],
                 by=requester, source=f"comment on #{number}", now=now)
    say(number, f"Approved by {approver}. {memo[key]}", "completed")
    return {"decisions": 1, "settings": False}


def _apply(ws, api, store, item: dict, now: datetime, say, env: dict | None = None) -> dict:
    """One request or command: parsed, checked against the sender's access, recorded, settings committed; `say` answers."""
    today, number, login = now.date(), item.get("number"), item.get("login")
    source = {"issue": f"issue #{number}", "comment": f"comment on #{number}"}.get(item["kind"], "manual run")
    if item["kind"] == "comment" and item["body"].strip().lower().startswith(APPROVE):
        return _approve(ws, api, store, item, now, say, env or {})
    try:
        asked = _check_command(item["body"]) if item["kind"] == "comment" else None
        again = _resync_command(item["body"]) if item["kind"] == "comment" else None
        if asked is not None:
            req = dec.Request([], {}, check=asked)
        elif again is not None:
            req = dec.Request([], {}, resync=again)
        elif item["kind"] == "comment":
            default = item.get("default")
            if "default" not in item and number:
                found = api._get(f"/repos/{api.repo}/issues/{number}")
                default = _item(found.get("title")) or (("pr", str(number)) if found.get("pull_request") else None)
            changes = dec.parse_command(item["body"], today, default=default)
            req = dec.Request(changes, {}) if changes else None
        else:
            raw = item["body"]
            block = raw if item["kind"] == "issue" or "```stackvitals" in raw else f"```stackvitals\n{raw}\n```"
            req = dec.parse_request(block, today)
    except dec.CommandError as exc:
        say(number, f"StackVitals couldn't read that: {_quiet(exc)} Nothing was changed.", None)
        return {"decisions": 0, "settings": False, "error": str(exc)}
    if req is None or not (req.changes or req.settings or req.golden or req.check or req.resync):
        return {"decisions": 0, "settings": False}
    # A connection test uses the repo's keys and may post to its chat, and a re-sync spends their limits: write access.
    need = 2 if req.settings or req.golden or req.check or req.resync else 1
    if _level(api, login) < need:
        say(number, ("Only people with write access to this repo can change its StackVitals settings" if need == 2 else
                     "Only people with triage or write access can make StackVitals decisions here") + "; nothing was changed.",
            None)
        return {"decisions": 0, "settings": False, "refused": True}
    lines, changed, moves = [], False, {}
    if req.changes:
        feedback = [c for c in req.changes if c.verb in dec.FEEDBACK]
        published = _published(ws) if feedback else None
        seen = {(c.kind, c.id): seen_state(published, c.kind, c.id) for c in feedback}
        store.record(req.changes, by=login, source=source, now=now, seen=seen)
        lines += ["Recorded:", _decided(req.changes)]
    if req.settings:
        memo = getattr(ws, "memo", {})
        key = ("settings", item["key"] or source)
        if key not in memo:
            # Once per job: a rejected data push runs this step again, and the file on GitHub already changed.
            memo[key] = _apply_settings(api, req.settings, login, number, now)
        text, cfg, moves = memo[key]
        lines.append(text)
        # Settings changes join the log too, so the app's Activity shows who changed what, and how.
        store.record([dec.Decision("set", "setting", k, None, why) for k, why in moves.items()], by=login, source=source, now=now)
        if cfg is not None:
            ws.cache["settings"], changed = cfg, True
    if req.golden:
        memo = getattr(ws, "memo", {})
        key = ("golden", item["key"] or source)
        if key not in memo:
            # Once per job, like settings: a retried data push must never create a repo or a PR twice.
            memo[key] = _golden(env or {}, api, req.golden, login, body=item.get("body"), issue=item["kind"] == "issue")
        lines.append(memo[key])
        store.record([dec.Decision("run", "golden", req.golden["path"], None, memo[key][:200])], by=login, source=source,
                     now=now)
    checked = None
    if req.check:
        memo = getattr(ws, "memo", {})
        key = ("check", item["key"] or source)
        if key not in memo:
            # Once per job: a retried data push must not post the chat test message twice.
            memo[key] = _run_checks(ws, req.check, env or {})
        checked = memo[key]
        if isinstance(checked, dict):
            from stackvitals.connectors import check, public
            check.save(ws.path, checked, public(ws))
            shown = check.shown(checked, public(ws))
            lines += ["Connection checks:", *(f"- {check.line(n, r)}" for n, r in shown.items())] if shown else \
                ["No connector is set up yet, so there was nothing to test."]
        else:
            lines.append(checked)
    resynced = 0
    if req.resync:
        from stackvitals.connectors import ConnectorError
        from stackvitals.core.resync import rewind
        lines.append("Read again:")
        for r in req.resync:
            # The connectors step runs after this one, so the same run reads the window again.
            try:
                lines.append(f"- {rewind(ws.path, r['source'].strip().lower(), r['since'], now)}")
                resynced += 1
            except (ConnectorError, ValueError) as exc:
                lines.append(f"- {r['source']}: {_quiet(exc)}")
        store.record([dec.Decision("run", "resync", r["source"], None, f"since {r['since'] or 'the whole window'}")
                      for r in req.resync], by=login, source=source, now=now)
    waiting = bool(req.golden) and any(line.startswith(WAITING) for line in lines)
    close = (None if waiting else "completed" if req.changes or moves or req.golden or req.check or resynced
             else "not_planned") if item["kind"] == "issue" else None
    say(number, "\n".join(lines), close)
    out = {"decisions": len(req.changes), "settings": changed, **({"resynced": resynced} if req.resync else {})}
    if isinstance(checked, dict):
        out.update(checks=len(checked), working=sum(1 for r in checked.values() if r["ok"]))
    return out


def _run_checks(ws, asked, env: dict) -> dict | str:
    """The asked connection checks, or a sentence when the names can't be read."""
    from stackvitals.connectors import check, public
    cfg = ws.cache.get("settings") or parse("")[0]
    try:
        names = check.resolve(asked, cfg, env)
    except ValueError as exc:
        return f"Nothing was tested: {_quiet(exc)}"
    # A public repo's answers name no channel, team or bucket: they land on a readable branch and issue.
    return check.run(names, cfg, env, public=public(ws))


def _check_command(body: str | None):
    """`/stackvitals check jira slack` (or `check` / `check all`): the names asked for, else None."""
    for line in (body or "").splitlines():
        words = line.strip().split()
        if words and words[0].lower() == "/stackvitals":
            if len(words) > 1 and words[1].lower() == "check":
                rest = [w.strip(",") for w in words[2:] if w.strip(",")]
                return "all" if not rest or [w.lower() for w in rest] == ["all"] else rest
            return None
    return None


def _resync_command(body: str | None) -> list | None:
    """`/stackvitals resync jira linear since 2026-09-01`: the services to read again and from when, else None."""
    for line in (body or "").splitlines():
        words = [w.strip(",") for w in line.strip().split() if w.strip(",")]
        if words and words[0].lower() == "/stackvitals":
            if len(words) < 3 or words[1].lower() != "resync":
                return None
            since = words[words.index("since") + 1] if "since" in words[:-1] else None
            names = [w.lower() for w in words[2:] if w not in ("since", since)]
            return [{"source": n, "since": since} for n in names] or None
    return None


def check_only(env: dict) -> bool:
    """Whether this run's own request only asks for connection checks, so the job can skip every module."""
    item = _from_event(env.get("GITHUB_EVENT_NAME"), _payload(env), env)
    if not item:
        return False
    if item["kind"] == "comment":
        return _check_command(item["body"]) is not None
    raw = item["body"]
    block = raw if item["kind"] == "issue" or "```stackvitals" in raw else f"```stackvitals\n{raw}\n```"
    try:
        req = dec.parse_request(block, datetime.now().date())
    except dec.CommandError:
        return False
    return bool(req and req.check and not (req.changes or req.settings or req.golden))


def _closed_or_reopened(store, payload: dict, now: datetime, api=None) -> dict | None:
    """A flaky-test issue closed as not planned: the team lives with it; reopened: that decision is undone."""
    issue = payload.get("issue") or {}
    item = _item(issue.get("title"))
    if not (item and any((label or {}).get("name") == "flaky-test" for label in issue.get("labels") or [])):
        return None
    by, source = (payload.get("sender") or {}).get("login") or "?", f"issue #{issue.get('number')}"
    if payload.get("action") == "closed":
        if issue.get("state_reason") != "not_planned":
            return None
        # An issue's author can close it too; only triage or write access makes it a team decision.
        if api is None or _level(api, by if by != "?" else None) < 1:
            print(f"{by} closed {source} as not planned without triage or write access; no decision was recorded.")
            return {"decisions": 0, "settings": False, "refused": True}
        store.record([dec.Decision("acknowledge", item[0], item[1], None, "closed as not planned")], by=by, source=source, now=now)
    else:
        current = store.state(now.date()).get(f"{item[0]}:{item[1]}") or {}
        if current.get("verb") != "acknowledge":
            return None
        store.record([dec.Decision("reopen", item[0], item[1], None, "issue reopened")], by=by, source=source, now=now)
    return {"decisions": 1, "settings": False}


def requests_step(ws, env: dict, now: datetime, make_api=ActionsAPI) -> dict | None:
    event, payload = env.get("GITHUB_EVENT_NAME"), _payload(env)
    store = dec.Store(ws.path)
    api = make_api(env.get("STACKVITALS_TOKEN") or env.get("GITHUB_TOKEN"), ws.repo, max_requests=40)
    if event == "issues" and payload.get("action") in ("closed", "reopened"):
        return _closed_or_reopened(store, payload, now, api)
    replies: list[tuple[int, str, str | None]] = []
    unanswered: list[str] = []

    def say(number, text, close):
        if number:
            replies.append((number, text, close))
        else:
            unanswered.append(text)

    def answer():
        for n, text, close in replies:
            api.send("POST", f"/repos/{ws.repo}/issues/{n}/comments", {"body": text})
            if close:
                api.send("PATCH", f"/repos/{ws.repo}/issues/{n}", {"state": "closed", "state_reason": close})
        # A manual run has no issue to answer on: its answer goes to the job summary.
        for text in unanswered:
            print(text)
            if env.get("GITHUB_STEP_SUMMARY"):
                with open(env["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
                    f.write(f"### StackVitals request\n{text}\n")
    ws.after_commit(answer, "Requests")
    path = ws.path / SWEEP
    try:
        kept = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        kept = None
    done = list((kept or {}).get("done") or [])
    own = _from_event(event, payload, env)
    todo = [own] if own else []
    if kept is not None:
        since = max(now - LOOKBACK, datetime.fromisoformat(kept["since"].replace("Z", "+00:00")))
        try:
            todo += [m for m in _missed(api, iso(since), set(done)) if m["key"] != (own or {}).get("key")]
        except (APIError, OutOfBudget):
            pass  # the next run looks again
    totals = {"decisions": 0, "settings": False}
    for item in todo:
        out = _apply(ws, api, store, item, now, say, env)
        totals["decisions"] += out["decisions"]
        totals["settings"] = totals["settings"] or out["settings"]
        totals.update({k: v for k, v in out.items() if k in ("error", "refused")})
        for k in ("checks", "working", "resynced"):
            if k in out:
                totals[k] = totals.get(k, 0) + out[k]
        if item["key"]:
            done.append(item["key"])
    # Written only when something new was handled (tracking starts with the first), so a quiet run commits nothing.
    if len(done) != len((kept or {}).get("done") or []):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"since": (kept or {}).get("since") or iso(now), "done": done[-DONE_MAX:]}, indent=1),
                        encoding="utf-8")
    return totals if todo else None
