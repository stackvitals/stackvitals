import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from stackvitals.ci import bench as ci_bench
from stackvitals.ci.action import BRANCH, DataBranch, GitError
from stackvitals.ci.api import ActionsAPI, APIError, OutOfBudget
from stackvitals.community import affiliation
from stackvitals.connectors.store import ConnectorStore
from stackvitals.community.build import build
from stackvitals.community.context import read_context
from stackvitals.community.collect import _read, collect_discussions, collect_issues, collect_stars, collect_traffic
from stackvitals.community.report import badges, render_html, render_markdown
from stackvitals.core.store import published
from stackvitals.flow.action import FLOW_EVENTS
from stackvitals.flow.action import LABEL as FLOW_LABEL
from stackvitals.flow.action import make_gql
from stackvitals.flow.collect import collect
from stackvitals.flow.store import FlowStore
from stackvitals import shell
from stackvitals.core.actors import kind_of
from stackvitals.core.config import parse
from stackvitals.core.delivery import apply_identity

BENCH_FILE, STARS_FILE = "community-benchmarks.json", "stars-benchmarks.json"
LABEL = "Community"


def load_benchmarks(cache_dir: Path, token: str | None = None) -> tuple[dict | None, dict | None]:
    # In the Action: public files only (none before launch). Locally, the user's own token may read them.
    ok = lambda d: d if isinstance(d, dict) and isinstance(d.get("groups"), dict) else None  # noqa: E731
    return (ci_bench.load(token, cache_dir, name=BENCH_FILE, url_env="STACKVITALS_COMMUNITY_BENCH_URL", validate=ok, default_url=None),
            ci_bench.load(token, cache_dir, name=STARS_FILE, url_env="STACKVITALS_STARS_BENCH_URL", validate=ok, default_url=None))


def write_community_outputs(root: Path, result: dict, repo: str) -> None:
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "community.html").write_text(render_html(result, repo, shell.present(docs) | {"community.html"}), encoding="utf-8")
    (docs / "community.json").write_text(json.dumps(published(result), indent=1), encoding="utf-8")
    for name, badge in badges(result).items():
        (docs / name).write_text(json.dumps(badge), encoding="utf-8")
    (docs / ".nojekyll").write_text("", encoding="utf-8")


def community_step(ws, env: dict, now: datetime, make_gql=make_gql, make_api=ActionsAPI, flow_ran: bool | None = None) -> dict:
    """Community's part of a job: issues, star history and (with its own token) traffic into the shared checkout,
    beside Team Flow's PR history; the page, the badges and (after the commit) the summary."""
    repo, token = ws.repo, env.get("STACKVITALS_TOKEN") or env.get("GITHUB_TOKEN")
    traffic_token = (env.get("STACKVITALS_TRAFFIC_TOKEN") or "").strip()
    owner, name = repo.split("/")
    if flow_ran is None:
        # Team Flow ran earlier in this same job: its PRs are already in the checkout.
        flow_ran = ws.results.get(FLOW_LABEL) is not None
    notes = []
    prs, gql = FlowStore(ws.path), make_gql(token)
    # Team Flow already read the PRs this run; otherwise Community keeps the same history itself.
    points = 0 if flow_ran else collect(gql, prs, owner, name, now)["points"]
    issues = FlowStore(ws.path, "community/issues")
    got = collect_issues(gql, issues, owner, name, now)
    if got.get("refused"):
        notes.append("Add `issues: read` to the workflow permissions to include issues.")
    folder = ws.path / "community"
    try:
        collect_stars(make_api(token, repo, max_requests=110), folder, now)
    except (APIError, OutOfBudget) as exc:
        notes.append(f"Star history wasn't read this time ({exc}).")
    if traffic_token:
        try:
            collect_traffic(make_api(traffic_token, repo, max_requests=10), folder, now)
        except (APIError, OutOfBudget) as exc:
            notes.append("The traffic token can't read traffic: it needs the repository permission "
                         f"\"Administration: read\" ({str(exc)[:120]}).")
    bench, star_bench = load_benchmarks(ws.work / "bench")
    # The repo's [identity] settings decide who is a bot or a newcomer; the stored history stays as GitHub said.
    settings = ws.cache.get("settings") or parse("")[0]
    ident = settings.get("identity")
    pr_data = apply_identity(prs.load(), ident)
    context = _context(gql, folder, owner, name, now)
    stated = {k: v for k, v in (settings.get("community") or {}).items() if v}
    if stated:
        context = {**(context or {}), "stated": stated}
    talks = FlowStore(ws.path, "community/discussions")
    if (context or {}).get("discussions"):
        points += collect_discussions(gql, talks, owner, name, now)["points"]
    # The people behind the last 180 days' merged work, busiest first, for the elephant factor.
    since = (now - timedelta(days=180)).strftime("%Y-%m-%dT%H:%M:%SZ")
    authors = Counter(p["au"] for p in pr_data.get("closed") or [] if p.get("mg") and p["mg"] >= since and p.get("au")
                      and kind_of(p["au"], p.get("at")) == "person")
    aff = affiliation.collect(gql, [a for a, _n in authors.most_common()])
    result = build(pr_data, apply_identity(issues.load(), ident), _read(folder / "stars.json"),
                   _read(folder / "traffic.json"), prs.repo(), now, bench=bench, star_bench=star_bench,
                   context=context, affiliation=aff, discussions=talks.load(),
                   forum=ConnectorStore(ws.path, "discourse").load().get("topic"),
                   chat=[t for n in ("slack", "discord") for t in ConnectorStore(ws.path, n).load().get("topic") or []])
    write_community_outputs(ws.path, result, repo)
    out = {"issues": got["issues"], "points": points + got["points"], "complete": got["complete"],
           "waiting": result["waiting_total"], "score": (result.get("score") or {}).get("score")}

    def after_commit():
        summary = env.get("GITHUB_STEP_SUMMARY")
        if summary:
            note = "" if got["complete"] or got.get("refused") else "\n\nStill reading older issues (GitHub's hourly limit); the next run continues."
            note += "".join(f"\n\n{n}" for n in notes)
            with open(summary, "a", encoding="utf-8") as f:
                f.write(render_markdown(result, repo) + note + "\n")
    ws.after_commit(after_commit, LABEL)
    return out


def _context(gql, folder: Path, owner: str, name: str, now: datetime) -> dict | None:
    """What the repo states about itself, read once a week (a file changes rarely)."""
    kept = _read(folder / "context.json")
    if kept.get("at", "") >= (now - timedelta(days=7)).strftime("%Y-%m-%d"):
        return kept.get("facts")
    facts = read_context(gql, owner, name)
    if facts is None:
        return kept.get("facts")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "context.json").write_text(json.dumps({"at": now.strftime("%Y-%m-%d"), "facts": facts}, indent=1),
                                         encoding="utf-8")
    return facts


def run_community_action(env: dict, now: datetime | None = None, make_gql=make_gql, make_api=ActionsAPI,
                         flow_ran: bool | None = None, workspace=None) -> dict | None:
    """One Community run on the schedule or by hand: issues, star history and (with its own token) traffic, kept in the
    data branch beside Team Flow's PR history, then the page, the badges and the summary."""
    if env.get("GITHUB_EVENT_NAME") not in FLOW_EVENTS:
        return None
    from stackvitals.core.workspace import run_job
    now = now or datetime.now(timezone.utc)

    def step(ws):
        return community_step(ws, env, now, make_gql, make_api, bool(flow_ran) if workspace is None else flow_ran)
    if workspace is not None:
        return step(workspace)
    job = run_job(env, [(LABEL, step)], now, message=f"stackvitals: community {now:%Y-%m-%d %H:%M} UTC", catch=False)
    return {**job["results"][LABEL], "pushed": job["outcome"] == "pushed"}
