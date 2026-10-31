import json
from datetime import datetime, timezone
from pathlib import Path

from stackvitals.ci.action import BRANCH, DataBranch, GitError
from stackvitals.ci.api import ActionsAPI
from stackvitals.flow.action import FLOW_EVENTS
from stackvitals.flow.action import make_gql as _gql
import httpx

from stackvitals.ci import bench as ci_bench
from stackvitals.flow import peers as flow_peers
from stackvitals.portal.catalog import build_catalog
from stackvitals.ci.api import APIError, OutOfBudget
from stackvitals.portal.catalog import cacheable
from stackvitals.portal.export import entities_yaml
from stackvitals.portal.checks import CAP as CHECKS_CAP
from stackvitals.portal.checks import load_level, plan
from stackvitals.portal.golden import GoldenError, load_paths
from stackvitals.portal.rollup import org_rollup
from stackvitals.portal.checks import send as send_checks
from stackvitals.portal.campaigns import load_campaigns, progress, reminder_text, reminders_due, update_tracking_issue
from stackvitals.portal.github import NA, read, read_file
from stackvitals.portal.history import since
from stackvitals import shell
from stackvitals.portal.pages import _cell, publishable, render_catalog, render_catalog_html
from stackvitals.portal.scorecard import file_rules, rules_or_default, score_catalog
from stackvitals.core.store import accept, published

def _scorecard_client() -> httpx.Client:
    return httpx.Client(timeout=20)


LABEL = "Portal"
SETUP = ("Public mode: only the org's public repos are read. To include private repos, give the Action a token from an "
         "org-owned read-only GitHub App as `portal-token` (see docs/modules.md).")


def _history_row(r: dict) -> dict:
    # One compact line per repo per day: enough for "since when" and campaign progress later.
    o = r.get("owners") or {}
    return {"name": r["name"], "archived": r.get("archived"), "language": r.get("language"), "owners": o.get("status"),
            "why": len(o.get("reasons") or []),
            "level": (r.get("score") or {}).get("level"),
            "failed": [x["id"] for x in (r.get("score") or {}).get("results") or [] if x["result"] == "fail"],
            "modules": r.get("modules"), "rules": r.get("rules"), "checked": r.get("checked")}


def portal_step(ws, env: dict, now: datetime, make_api=ActionsAPI) -> dict:
    """Portal's part of a job: the catalog, a daily history line per repo and the pages into the shared checkout;
    after the commit, the campaign tracking issues and the summary."""
    repo, builtin = ws.repo, env.get("STACKVITALS_TOKEN") or env.get("GITHUB_TOKEN")
    app = (env.get("STACKVITALS_PORTAL_TOKEN") or "").strip()
    org = (env.get("STACKVITALS_PORTAL_ORG") or "").strip() or repo.split("/")[0]
    mode = "private" if app else "public"
    own = make_api(builtin, repo, max_requests=5)
    here = read(own, f"/repos/{repo}")
    # The org's own rules live in this repo as portal.toml; without it the default pack applies.
    text = read_file(own, repo, "portal.toml")
    rules, exemptions, rule_notes = rules_or_default(None if text is NA else text)
    try:
        campaigns = load_campaigns(None if text is NA else text)
    except ValueError:
        campaigns = []  # a broken file was already reported by the rules note
    # Unknown visibility counts as public: the safe side.
    destination_private = bool(here.get("private")) if here is not NA and isinstance(here, dict) else False
    folder = ws.path / "portal"
    folder.mkdir(parents=True, exist_ok=True)
    try:
        previous = accept(json.loads((folder / "catalog.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        previous = None
    api = make_api(app or builtin, repo, max_requests=4000 if app else 700)
    # Conditional reads kept between runs: a repo whose rules and owners didn't change costs nothing the next day.
    try:
        api.etags = json.loads((folder / "etags.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        api.etags = {}
    api.cacheable = cacheable
    catalog = build_catalog(api, org, mode, now, previous=previous, scorecard_client=_scorecard_client(),
                            gql=_gql(app or builtin), file_rules=file_rules(rules))
    # Peer levels need the public benchmark files (none before launch: those rules are "not available").
    bench = {"ci": ci_bench.load(None, ws.work / "bench"), "flow": flow_peers.load(None, ws.work / "bench")}
    score_catalog(catalog, rules, exemptions, now, bench)
    # Since when each repo has had its owner status and level, from the days already kept.
    when = since(folder / "history", catalog["repos"], now.strftime("%Y-%m-%d"))
    for r in catalog["repos"]:
        if r.get("score"):
            r["since"] = when.get(r["name"])
    kept = publishable(catalog["repos"], destination_private)
    # The org view, from the facts the repos this page may show publish themselves.
    catalog["org_view"] = org_rollup(kept)
    # Campaign progress only ever counts repos this page may show.
    catalog["campaigns"] = [progress(c, kept, folder / "history", now) for c in campaigns]
    # The golden paths people may run from the app (what each is, never the App's token).
    try:
        golden = load_paths(None if text is NA else text)
    except (GoldenError, ValueError) as exc:
        golden, rule_notes = {}, [*rule_notes, f"Golden paths in portal.toml: {exc}"]
    catalog["golden"] = [{k: g[k] for k in ("id", "title", "kind", "description", "private")} for g in golden.values()]
    catalog["golden_ready"] = bool(app)
    (folder / "catalog.json").write_text(json.dumps(published({**catalog, "repos": kept}), indent=1), encoding="utf-8")
    # Kept answers name repos and hold their rules: never on a public portal repo that reads private repos, and only
    # for repos still listed.
    if isinstance(getattr(api, "etags", None), dict) and (destination_private or mode == "public"):
        live = tuple(f"/repos/{r['name']}/" for r in catalog["repos"])
        kept_tags = {k: v for k, v in api.etags.items() if k.startswith(live) or k.startswith(f"/orgs/{org}/")}
        (folder / "etags.json").write_text(json.dumps(kept_tags, separators=(",", ":")), encoding="utf-8")
    else:
        (folder / "etags.json").unlink(missing_ok=True)
    (folder / "README.md").write_text(render_catalog(catalog, destination_private), encoding="utf-8")
    # Backstage: one location file for the repos without their own catalog-info.yaml.
    pages = here.get("has_pages") and not destination_private if isinstance(here, dict) else False
    owner, name = repo.split("/")
    (folder / "entities.yaml").write_text(entities_yaml(kept, f"https://{owner.lower()}.github.io/{name}/" if pages else None),
                                          encoding="utf-8")
    docs = ws.path / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "portal.html").write_text(render_catalog_html(catalog, destination_private, shell.present(docs) | {"portal.html"}),
                                      encoding="utf-8")
    (folder / "history").mkdir(exist_ok=True)
    (folder / "history" / f"{now:%Y-%m-%d}.json").write_text(
        json.dumps({"built_at": catalog["built_at"], "repos": [_history_row(r) for r in kept]}, separators=(",", ":")),
        encoding="utf-8")
    left_out = len(catalog["repos"]) - len(kept)
    out = {"mode": mode, "repos": len(kept), "complete": catalog["complete"], "left_out": left_out}
    # Deadline reminders, once each: remembered before the commit so an overlapping run never sends one twice.
    sent_file = folder / "reminders.json"
    try:
        sent = json.loads(sent_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        sent = {}
    remind = reminders_due(catalog.get("campaigns") or [], sent, now)
    if remind:
        for p, days in remind:
            sent.setdefault(p["id"], []).append(days)
        sent_file.write_text(json.dumps(sent, indent=1, sort_keys=True), encoding="utf-8")

    # Opt-in required check: only with the org App (it writes to every repo) and a level in portal.toml.
    level = load_level(None if text is NA else text)
    checks = plan(catalog, level) if level and app else []
    # The cap would always stop at the same repo: each run starts where the last one stopped.
    cursor_file = folder / "checks-cursor.json"
    try:
        start = int(json.loads(cursor_file.read_text(encoding="utf-8")).get("next", 0)) % max(len(checks), 1)
    except (OSError, ValueError, TypeError):
        start = 0
    checks = checks[start:] + checks[:start]
    if checks:
        # Saved before the commit (sends come after it): the next run starts about where this one's cap will end.
        cursor_file.write_text(json.dumps({"next": (start + CHECKS_CAP // 3) % len(checks)}), encoding="utf-8")

    def after_commit():
        issue_notes = []
        if level and not app:
            issue_notes.append(f"[checks] level = \"{level}\" needs the org App (with Checks: write) to post checks.")
        if checks:
            done = send_checks(make_api(app, repo, max_requests=1000), checks)
            issue_notes.append(f"Portal checks: {done['posted']} posted for {level}"
                               + ("; stopped at the cap, the next run carries on" if done["stopped"] else "")
                               + (f"; refused for {len(done['refused'])} repos (the App needs Checks: write)" if done["refused"] else "")
                               + ".")
        for p in catalog.get("campaigns") or []:
            try:
                number = update_tracking_issue(make_api(builtin, repo, max_requests=10), repo, p)
                for q, days in remind:
                    if q["id"] == p["id"] and number:
                        make_api(builtin, repo, max_requests=3).send("POST", f"/repos/{repo}/issues/{number}/comments",
                                                                     {"body": reminder_text(p, days)})
            except (APIError, OutOfBudget):
                issue_notes = ["Add `issues: write` to this workflow's permissions to keep one tracking issue per campaign."]
        summary = env.get("GITHUB_STEP_SUMMARY")
        if summary:
            active = [r for r in kept if not r.get("archived") and not r.get("fork")]
            counts = {s: sum(1 for r in active if (r.get("owners") or {}).get("status") == s) for s in ("valid", "weak", "none")}
            notes = [f"### StackVitals Portal: {_cell(org)}",
                     f"{len(kept)} repos; owners {counts['valid']} valid, {counts['weak']} weak, {counts['none']} without CODEOWNERS. "
                     f"The catalog is in this repo's `{BRANCH}` branch, `portal/README.md`."]
            if mode == "public":
                notes.append(SETUP)
            notes += rule_notes + issue_notes
            if left_out:
                notes.append(f"This portal repo is public, so its private repos were left out ({left_out}).")
            if not catalog["complete"]:
                notes.append("Some repos keep an earlier check (GitHub's hourly limit); the next run continues with them.")
            with open(summary, "a", encoding="utf-8") as f:
                f.write("\n\n".join(notes) + "\n")
    ws.after_commit(after_commit, LABEL)
    return out


def run_portal_action(env: dict, now: datetime | None = None, make_api=ActionsAPI, workspace=None) -> dict | None:
    """One Portal run in the org's portal repo: the catalog, a daily history line per repo and the pages, kept in this
    repo's data branch. A public portal repo never receives private-repo data."""
    if env.get("GITHUB_EVENT_NAME") not in FLOW_EVENTS:
        return None
    from stackvitals.core.workspace import run_job
    now = now or datetime.now(timezone.utc)

    def step(ws):
        return portal_step(ws, env, now, make_api)
    if workspace is not None:
        return step(workspace)
    job = run_job(env, [(LABEL, step)], now, message=f"stackvitals: portal {now:%Y-%m-%d %H:%M} UTC", catch=False)
    return {**job["results"][LABEL], "pushed": job["outcome"] == "pushed"}
