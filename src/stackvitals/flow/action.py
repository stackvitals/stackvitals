import json
from datetime import datetime, timezone
from pathlib import Path

from mergescout.github.graphql import GitHubGraphQL
from stackvitals.ci.action import BRANCH, DataBranch, GitError
from stackvitals.ci.api import ActionsAPI, APIError, OutOfBudget
from stackvitals.core.actors import People
from stackvitals.core.config import parse
from stackvitals.core.delivery import apply_identity
from stackvitals.core.store import published
from stackvitals.core.summary import write_pr_summary
from stackvitals.flow.report import _md
from stackvitals.flow import peers
from stackvitals.flow.build import build
from stackvitals.flow.collect import collect
from stackvitals.flow.preflight import Habits, collect_asks, gaps
from stackvitals.flow.report import render_html, render_markdown
from stackvitals.flow.store import FlowStore
from stackvitals import shell

# Team Flow runs on the schedule and manual runs (the user's choice: every 3 hours), when the settings file is pushed and
# when someone makes a decision on GitHub (so a change applies at once), never on each CI run.
# Comment commands run light (Requests and CI Health), so a burst of them finishes fast.
FLOW_EVENTS = {"schedule", "workflow_dispatch", "push", "issues"}
LABEL = "Team Flow"


def make_gql(token: str) -> GitHubGraphQL:
    # Inside Actions nothing waits for the hourly reset; the next scheduled run continues.
    return GitHubGraphQL(token, max_wait=0, reserve=50)


def write_flow_outputs(root: Path, result: dict, repo: str) -> None:
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    # The public page and file never carry people's answer times.
    public = {k: v for k, v in result.items() if k != "responders"}
    (docs / "flow.html").write_text(render_html(public, repo, shell.present(docs) | {"flow.html"}), encoding="utf-8")
    (docs / "flow.json").write_text(json.dumps(published(public), indent=1), encoding="utf-8")
    (docs / ".nojekyll").write_text("", encoding="utf-8")


PREFLIGHT_MARKER = "<!-- stackvitals:preflight -->"


def _quiet(text: str) -> str:
    # Escaped, and with @ and www. broken by a zero-width space, so a note can never ping people or become a link.
    return _md(text).replace("@", "@​").replace("www.", "www​.")


def _preflight_targets(data: dict, since: str, done: set[int], now: datetime) -> list[tuple[int, str]]:
    """New PRs from outside contributors that differ from what merged PRs here usually include, with the note to post."""
    habits_index = Habits(data["open"] + data["closed"], now)
    people = People(data["open"] + data["closed"])
    out = []
    for p in data["open"]:
        if p["cr"] <= since or p["n"] in done or p.get("draft") or not people.is_outside(p):
            continue
        habits = habits_index.norms(p.get("paths") or [])
        found = gaps(p, habits)
        if found:
            lines = "\n".join(f"- {_quiet(g['why'])}{'' if g['what'] == 'size' else '; this PR has none.'}" for g in found)
            out.append((p["n"], f"{PREFLIGHT_MARKER}\n### Before review: how this PR compares with merged PRs here\n{lines}\n\n"
                                f"<sub>From this repo's own history ({habits['merged_prs']} merged PRs). The maintainers turned "
                                f"this note on; it is information, not a rule.</sub>"))
    return out


def flow_step(ws, env: dict, now: datetime, months: int = 12, make_gql=make_gql, make_api=ActionsAPI,
              preflight_comments: bool = False) -> dict:
    """Team Flow's part of a job: PRs changed since the last run into the shared checkout, the page, and (after the
    commit) the pre-flight notes and the summary."""
    repo, token = ws.repo, env.get("STACKVITALS_TOKEN") or env.get("GITHUB_TOKEN")
    owner, name = repo.split("/")
    store = FlowStore(ws.path)
    previous_run = store.state().get("last_collect")
    gql = make_gql(token)
    stats = collect(gql, store, owner, name, now, months=months)
    data = store.load()
    ws.cache["flow"] = data
    # Review comments of closed PRs, a few hundred per run (about 6 points per 20 PRs).
    collect_asks(gql, store, owner, name, data["closed"], cap=500)
    from stackvitals.flow import survival
    # How much of each squash-merged PR's code is still there 30 and 90 days on (git blame, about 12 points a run).
    survival.collect(gql, store.dir, owner, name, data["closed"], now)
    # The repo's [identity] settings (bots, people, old logins) shape every number; the stored history stays as GitHub said.
    seen = apply_identity(data, (ws.cache.get("settings") or parse("")[0]).get("identity"))
    # Pull requests the team left out (a label or /stackvitals exclude) leave every number; the page says how many.
    from stackvitals.core.decisions import visible
    seen = visible(ws.path, seen, now.date())
    # Comparisons come from a public file only (none before launch): no extra request otherwise.
    repo_meta = store.repo()
    # Public pages never name the person behind an area unless the repo asks for it.
    names = bool(repo_meta.get("private")) or bool(((ws.cache.get("settings") or {}).get("identity") or {}).get("knowledge_names"))
    result = build(seen, repo_meta, now, owner=owner, asks=store.asks(), bench=peers.load(None, ws.work / "bench"), names=names)
    result["excluded"] = seen.get("excluded", 0)
    to_comment = []
    if preflight_comments and previous_run:
        # Decided and remembered before the commit, so overlapping runs never comment twice.
        done = store.state().get("preflight_commented", [])
        to_comment = _preflight_targets(seen, previous_run, set(done), now)
        if to_comment:
            store.save_state({**store.state(), "preflight_commented": (done + [n for n, _ in to_comment])[-500:]})
    # Team automation (on by default): planned and remembered before the commit, sent after it.
    from stackvitals.flow.automate import plan, send
    switches = (ws.cache.get("settings") or parse("")[0]).get("automation") or {}
    acts, asked = plan(seen["open"], result["queue"], switches, store.state().get("automation") or {})
    if acts:
        store.save_state({**store.state(), "automation": asked})
    # PR rules as code ([[rules]]): planned and remembered the same way, and replayed on past PRs for the app.
    rule_list = (ws.cache.get("settings") or parse("")[0]).get("rules") or []
    if rule_list:
        from stackvitals.flow import rules as pr_rules
        ctx = pr_rules.context(seen, rule_list)
        rule_acts, rule_state, matched = pr_rules.plan(seen["open"], rule_list, ctx, store.state().get("rules") or {})
        if rule_acts:
            store.save_state({**store.state(), "rules": rule_state})
            acts = acts + rule_acts
        merged = sorted((p for p in seen["closed"] if p.get("mg")), key=lambda p: p["mg"])[-200:]
        replayed = pr_rules.replay(rule_list, merged, ctx)
        result["rules"] = [{"name": r["name"], "dry_run": r.get("dry_run", False), "open": matched[r["name"]],
                            "replay": replayed[r["name"]]} for r in rule_list]
    write_flow_outputs(ws.path, result, repo)
    # Dependency-update hygiene from the same pull requests (open updates by age, security ones past 48 h, a quiet bot).
    from stackvitals.core.decisions import Store as Decisions
    from stackvitals.core.store import write_if_changed
    from stackvitals.deps.hygiene import hygiene
    deps = hygiene(seen, Decisions(ws.path).state(now.date()), now)
    if deps is not None:
        write_if_changed(ws.path / "docs" / "deps.json", published(deps))
    write_pr_summary(ws.path, seen, now, repo)
    out = {"prs": stats["prs"], "points": stats["points"], "complete": stats["complete"], "queue": len(result["queue"])}

    def after_commit():
        notes = []
        if acts:
            done = send(make_api(token, repo, max_requests=len(acts) + 5), acts)
            notes.append(f"Team automation: {done['review']} reviewer request(s), {done['label']} label(s) added, "
                         f"{done['unlabel']} removed, {done['comment']} rule comment(s). Turn any part off under [automation] "
                         "in .github/stackvitals.toml (review_requests, size_labels, docs_label), or change [[rules]].")
            if done["refused"]:
                notes.append("Some were refused (" + "; ".join(done["refused"][:2]) + "): they need `pull-requests: write`.")
        if to_comment:
            api = make_api(token, repo, max_requests=len(to_comment) + 5)
            for n, body in to_comment:
                try:
                    api.send("POST", f"/repos/{repo}/issues/{n}/comments", {"body": body})
                except (APIError, OutOfBudget) as exc:
                    notes.append(f"Could not post the pre-flight note on #{n} ({exc}); it needs `pull-requests: write`.")
        summary = env.get("GITHUB_STEP_SUMMARY")
        if summary:
            note = "" if stats["complete"] else "\n\nStill reading older pull requests (GitHub's hourly limit); the next run continues."
            note += "".join(f"\n\n{n}" for n in notes)
            if stats["no_checks"]:
                note += "\n\nAdd `checks: read` and `statuses: read` to the workflow permissions to see which PRs have failing checks."
            if stats.get("no_deployments"):
                note += "\n\nAdd `deployments: read` to the workflow permissions to measure delivery from deployments."
            with open(summary, "a", encoding="utf-8") as f:
                f.write(render_markdown(result, repo) + note + "\n")
    ws.after_commit(after_commit, LABEL)
    return out


def run_flow_action(env: dict, now: datetime | None = None, months: int = 12, make_gql=make_gql, make_api=ActionsAPI,
                    preflight_comments: bool = False, workspace=None) -> dict | None:
    """One Team Flow run: read PRs changed since the last run, keep them in the data branch, rebuild the page."""
    if env.get("GITHUB_EVENT_NAME") not in FLOW_EVENTS:
        return None
    from stackvitals.core.workspace import run_job
    now = now or datetime.now(timezone.utc)

    def step(ws):
        return flow_step(ws, env, now, months, make_gql, make_api, preflight_comments)
    if workspace is not None:
        return step(workspace)
    job = run_job(env, [(LABEL, step)], now, message=f"stackvitals: team flow {now:%Y-%m-%d %H:%M} UTC", catch=False)
    return {**job["results"][LABEL], "pushed": job["outcome"] == "pushed"}
