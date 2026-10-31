"""One reader per capability, shared by the MCP server, the CLIs and the Action, so every surface answers from the same
window, with the same budget and the same evidence."""
import json
from datetime import datetime, timezone
from pathlib import Path

from stackvitals.ci import bench
from stackvitals.ci.action import BRANCH, add_owners
from stackvitals.ci.analyze import analyze
from stackvitals.ci.api import APIError, ActionsAPI
from stackvitals.ci.collect import TEST_ARTIFACTS, collect
from stackvitals.ci.store import DataStore
from stackvitals.ci.triggers import pr_edit_workflows, pr_metadata_workflows
from stackvitals.core.store import accept

DEFAULT_BUDGET = 1500
FRESH_S = 3600


def _fresh(state: dict, now: datetime) -> bool:
    last = state.get("last_collect")
    return bool(last and state.get("default_branch")
                and (now - datetime.fromisoformat(last.replace("Z", "+00:00"))).total_seconds() < FRESH_S)


def ci_result(repo: str, days: int, tok: str | None, home: Path, make_api=ActionsAPI, now: datetime | None = None,
              budget: int = DEFAULT_BUDGET, tests: bool = True, window: int | None = None, log=None,
              artifact_pattern: str = TEST_ARTIFACTS, owners: bool = False) -> tuple[dict, str]:
    """CI Health's findings for a repo and where they came from: the repo's own published file (one request) when it
    runs StackVitals; else a local copy read within the hour; else a live read of the last `days` days, test reports
    included, with the peer benchmark attached. `result["collect"]` says whether the live read was complete."""
    now = now or datetime.now(timezone.utc)
    window = window or days
    api = make_api(tok, repo, max_requests=budget)
    try:
        found = accept(json.loads(api.file("docs/data.json", BRANCH)))
    except (APIError, ValueError):
        found = None
    if found is not None:
        return found, "stackvitals-data branch"
    store = DataStore(Path(home) / "ci" / repo.replace("/", "__"))
    state = store.state()
    if _fresh(state, now):
        info, source = {"default_branch": state["default_branch"], "language": state.get("language"),
                        "stargazers_count": state.get("stars")}, "local copy read within the hour"
        collected, note = {"complete": True, "stopped": None}, ""
    else:
        info = api._get(f"/repos/{repo}")
        stats = collect(api, store, now, days=days, tests=tests, artifact_pattern=artifact_pattern, log=log)
        store.save_state({**store.state(), "default_branch": info.get("default_branch"), "language": info.get("language"),
                          "stars": info.get("stargazers_count")})
        source = f"read live from GitHub, last {days} days"
        note = "" if stats["complete"] else ", partly (GitHub's hourly limit; ask again later for more)"
        collected = {"complete": stats["complete"],
                     "stopped": None if stats["complete"] else store.state().get("last_stop") or "stopped early"}
    data = store.load()
    today = now.date().isoformat()
    meta = pr_metadata_workflows(api, store, data, info.get("default_branch"), today)
    result = analyze(data, now, window, default_branch=info.get("default_branch"), pr_metadata=meta,
                     pr_edits=pr_edit_workflows(store))
    result["benchmark"] = bench.compare(result["pushes"], bench.load(tok, Path(home) / "bench", client=api.client),
                                        info.get("language"), info.get("stargazers_count"))
    if owners:
        add_owners(api, store, result, info.get("default_branch"), today)
    result["collect"] = collected
    return result, source + note


def local_stores(repo: str, days: int, tok: str | None, home: Path, make_api=ActionsAPI, make_gql=None,
                 now: datetime | None = None, budget: int = 3000, log=None) -> tuple[dict, dict, dict]:
    """This machine's copies of a repo's CI runs and pull requests, refreshed unless read within the hour:
    (CI data, pull requests, CI state)."""
    from stackvitals.flow.collect import collect as flow_collect
    from stackvitals.flow.store import FlowStore
    now = now or datetime.now(timezone.utc)
    api = make_api(tok, repo, max_requests=budget)
    store = DataStore(Path(home) / "ci" / repo.replace("/", "__"))
    if not _fresh(store.state(), now):
        info = api._get(f"/repos/{repo}")
        collect(api, store, now, days=days, tests=False, log=log)
        store.save_state({**store.state(), "default_branch": info.get("default_branch"), "language": info.get("language"),
                          "stars": info.get("stargazers_count")})
    data = store.load()
    # Which checks read the PR's own text, kept in the state (each workflow file is read at most once a week).
    pr_metadata_workflows(api, store, data, store.state().get("default_branch"), now.date().isoformat())
    flow = FlowStore(Path(home) / "flow" / repo.replace("/", "__"))
    last = flow.state().get("last_collect")
    if not (last and (now - datetime.fromisoformat(last.replace("Z", "+00:00"))).total_seconds() < FRESH_S):
        if make_gql is None:
            from stackvitals.flow.cli import local_gql as make_gql
        owner, name = repo.split("/", 1)
        flow_collect(make_gql(tok), flow, owner, name, now, months=max(2, days // 30 + 1))
    return data, flow.load(), store.state()


def red_ci(repo: str, days: int, tok: str | None, home: Path, make_api=ActionsAPI, make_gql=None,
           now: datetime | None = None, log=None) -> tuple[dict, str]:
    """How long merged PRs sat with failing checks: the repo's published insight when it runs StackVitals, else computed
    from this machine's copies of its CI runs and pull requests."""
    from stackvitals.core import insights
    now = now or datetime.now(timezone.utc)
    api = make_api(tok, repo, max_requests=20)
    try:
        found = accept(json.loads(api.file("docs/insights.json", BRANCH)))
    except (APIError, ValueError):
        found = None
    if found is not None and found.get("red_ci"):
        return found["red_ci"], "stackvitals-data branch"
    ci, flow, state = local_stores(repo, days, tok, home, make_api, make_gql, now, log=log)
    out = insights.red_ci(flow["open"] + flow["closed"], ci, now, window_days=days, state=state)
    return out, f"CI runs and pull requests read from GitHub, last {days} days"


def delivery(repo: str, days: int, tok: str | None, home: Path, make_api=ActionsAPI, make_gql=None,
             now: datetime | None = None, log=None) -> tuple[dict, str]:
    """Delivery for a repo: its published docs/delivery.json when it runs StackVitals, else computed from this machine's
    copies of its pull requests, CI runs and (when kept) issues, with the repo's own settings file."""
    from stackvitals.core.delivery import build
    now = now or datetime.now(timezone.utc)
    api = make_api(tok, repo, max_requests=20)
    try:
        found = accept(json.loads(api.file("docs/delivery.json", BRANCH)))
    except (APIError, ValueError):
        found = None
    if found is not None and found.get("phases"):
        return found, "stackvitals-data branch"
    flow, info, ci, issues, cfg = delivery_inputs(repo, days, tok, home, make_api=make_api, make_gql=make_gql, now=now, log=log)
    out = build(flow, info, ci, issues, now, days, cfg)
    from stackvitals.core import delivery_peers
    out["peers"] = delivery_peers.compare(delivery_peers.own_metrics(flow["open"] + flow["closed"], now),
                                          delivery_peers.load(tok, Path(home) / "bench"), info.get("language"), info.get("stars"))
    from stackvitals.core.ai_outcomes import baseline
    from stackvitals.flow import peers as flow_peers
    out["ai"]["baseline"] = baseline(flow_peers.load(tok, Path(home) / "bench"), info.get("language"), info.get("stars"))
    return out, f"pull requests and CI runs read from GitHub, last {days} days"


def delivery_inputs(repo: str, days: int, tok: str | None, home: Path, make_api=ActionsAPI, make_gql=None,
                    now: datetime | None = None, log=None) -> tuple[dict, dict, dict, list[dict], dict]:
    """What delivery is computed from: this machine's copies of a repo's pull requests, repo details, CI runs and (when
    kept) issues, brought up to date from GitHub, and the repo's own settings file."""
    from stackvitals.core.config import FILE, parse
    from stackvitals.flow.store import FlowStore
    now = now or datetime.now(timezone.utc)
    try:
        text = make_api(tok, repo, max_requests=5).file(FILE, None).decode("utf-8", "replace")
    except APIError:
        text = None
    cfg = parse(text)[0]
    ci, flow, _state = local_stores(repo, days, tok, home, make_api, make_gql, now, log=log)
    folder = Path(home) / "flow" / repo.replace("/", "__")
    return flow, FlowStore(folder).repo(), ci, local_issues(home, repo), cfg


def local_issues(home: Path, repo: str) -> list[dict]:
    """The issues `community report` keeps on this machine (and the older place next to the PRs), for incidents."""
    from stackvitals.flow.store import FlowStore
    slug = repo.replace("/", "__")
    for root, folder in ((Path(home) / "community" / slug, "issues"), (Path(home) / "flow" / slug, "community/issues")):
        if (root / folder).is_dir():
            got = FlowStore(root, folder).load()
            return got["open"] + got["closed"]
    return []


def findings(repo: str, days: int, tok: str | None, home: Path, make_api=ActionsAPI, make_gql=None,
             now: datetime | None = None, log=None) -> tuple[list[dict], str]:
    """What to fix first in a repo: its published findings when it runs StackVitals, else computed from this machine's
    copies of its CI runs, pull requests and issues, with Team Flow's public numbers only."""
    from stackvitals.core import findings as found_mod
    from stackvitals.core import insights
    from stackvitals.core.delivery import build as delivery_build
    from stackvitals.flow.build import build as flow_build
    now = now or datetime.now(timezone.utc)
    try:
        found = accept(json.loads(make_api(tok, repo, max_requests=20).file("docs/insights.json", BRANCH)))
    except (APIError, ValueError):
        found = None
    if found is not None and found.get("findings") is not None:
        return found["findings"], "stackvitals-data branch"
    flow, info, ci, issues, cfg = delivery_inputs(repo, days, tok, home, make_api=make_api, make_gql=make_gql, now=now, log=log)
    state = DataStore(Path(home) / "ci" / repo.replace("/", "__")).state()
    prs = flow["open"] + flow["closed"]
    red = insights.red_ci(prs, ci, now, window_days=days, state=state)
    meta = {path: set(v.get("jobs") or []) for path, v in (state.get("triggers") or {}).items()}
    public_flow = flow_build(flow, info, now, owner=repo.split("/")[0])
    bumps = found_mod.bump_reds(prs, ci, now, meta, since=red["since"])
    ledger = None
    if bumps:
        from stackvitals.deps.evidence import load_ledger
        ledger = load_ledger(tok, Path(home) / "deps")
    out = found_mod.build(repo, red, delivery_build(flow, info, ci, issues, now, days, cfg), public_flow, bumps, now, ledger)
    return out, f"pull requests and CI runs read from GitHub, last {days} days"


def supply(repo: str, tok: str | None, make_api=ActionsAPI) -> tuple[dict | None, str]:
    """A repo's supply chain as its StackVitals run published it (it needs the repo's own dependency graph and a weekly
    run, so nothing is computed from here)."""
    try:
        found = accept(json.loads(make_api(tok, repo, max_requests=5).file("docs/supply.json", BRANCH)))
    except (APIError, ValueError):
        found = None
    return found, "stackvitals-data branch" if found else "not published: the repo doesn't run StackVitals with the deps module"
