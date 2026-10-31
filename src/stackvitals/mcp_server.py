import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from mcp.server.mcpserver import MCPServer

from mergescout.github.graphql import GraphQLError
from mergescout.mcp_server import App
from mergescout.mcp_server import build_server as build_contribute
from stackvitals.ci import cli as ci_cli
from stackvitals.ci.action import BRANCH
from stackvitals.ci.api import ActionsAPI, APIError, OutOfBudget
from stackvitals.ci.collect import TEST_ARTIFACTS, _reports, job_record, run_record
from stackvitals.ci.feedback import KNOWN, SAFE_FLAKES, TRACK_RECORD, classify, error_excerpt, failure_summary
from stackvitals.deps.cli import ORDER as DEPS_ORDER
from stackvitals.deps.cli import find as deps_find
from stackvitals.deps.dossier import dossier as deps_dossier
from stackvitals.deps.evidence import load_evidence
from stackvitals.deps.lockfiles import read_lockfile
from stackvitals.contribute.brief import build_brief, render as render_brief
from stackvitals.core import services
from stackvitals.core.store import accept
from stackvitals.flow import peers as flow_peers
from stackvitals.flow.build import build as flow_build
from stackvitals.flow.cli import local_gql
from stackvitals.flow.collect import collect as flow_collect
from stackvitals.flow.knowledge import codeowners_for, expertise, suggest_reviewers
from stackvitals.flow.preflight import collect_asks, gaps, norms
from stackvitals.flow.preflight import preflight as flow_preflight
from stackvitals.flow.store import FlowStore

DEPS_NOTE = ("Verdicts weigh what happened: upgrade outcomes in public repos, maintainer history, advisories. They never "
             "promise a package is free of risk; read the evidence lines.")
ADVICE = {
    # An agent that trusted this alone called real failures flakes (bench/accuracy/agents): say what to check first.
    "known flaky": "This has failed and then passed with no code change often, so it may be a flake, but history alone is "
                   "no proof: on held-out public CI, 13 of 81 such failures were the change's own. Read the error: re-run it only "
                   "if it shows an outside service, the runner or a wait failing and names no file you changed; otherwise look "
                   "at your change first.",
    "flaked before": "This has flaked before, but rarely: check whether your change caused this failure before re-running it.",
    "already failing": "This was already failing on the default branch: your change is unlikely to be the cause.",
    "maybe flaky": "This never flaked before, but it failed the way flaky checks do (a wait running out, a benchmark gate, a "
                   "live service): re-run it once; if it fails again, look at your change.",
    "PR details": "A check on the pull request's title, description or labels failed: fix those on the PR, not the code; "
                  "it runs again when they change.",
    "no history": "No flaky history for this: treat the failure as most likely caused by the change.",
}


def _default_branch_failures(api, repo: str, data: dict, body: dict, branch: str | None) -> int:
    """Failed pushes of the same workflow to the default branch in the 3 days before this run, added to `data` (one
    list request and one jobs request each), so "already failing" can be judged."""
    if not branch or body.get("head_branch") == branch or not body.get("created_at"):
        return 0
    since = (datetime.fromisoformat(body["created_at"].replace("Z", "+00:00")) - timedelta(days=3)).date().isoformat()
    listed = (api._get(f"/repos/{repo}/actions/runs", {"branch": branch, "event": "push", "status": "failure",
                                                       "created": f">={since}", "per_page": 30}) or {}).get("workflow_runs") or []
    mine = [r for r in listed if r.get("path") == body.get("path") and r.get("id") != body.get("id")][:3]
    for r in mine:
        att = r.get("run_attempt") or 1
        data["runs"].append(run_record(r, att))
        data["jobs"] += [job_record(j, r["id"], att) for j in api.jobs(r["id"], att)]
    return len(mine)


def _as_of(out: dict) -> str:
    # The time the numbers describe: the answer's own stamp, else a module's inside it, else now.
    for value in [out, *(v for v in out.values() if isinstance(v, dict))]:
        for key in ("generated", "as_of", "until"):
            if isinstance(value.get(key), str):
                return value[key]
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe(fn):
    # Agents read plain answers better than stack traces; every answer says when and where its numbers come from.
    def run(*args, **kwargs):
        try:
            out = fn(*args, **kwargs)
        except (APIError, OutOfBudget, ValueError, httpx.HTTPError, GraphQLError) as exc:
            return {"error": str(exc)}
        if isinstance(out, dict) and "error" not in out:
            out.setdefault("as_of", _as_of(out))
            out.setdefault("sources", [out["source"]] if out.get("source") else [])
        return out
    run.__name__, run.__doc__ = fn.__name__, fn.__doc__
    return run


def _brief(entry: dict, kind: str) -> dict:
    name = entry["id"] if kind == "test" else f"{(entry.get('workflow') or '?').rsplit('/', 1)[-1]} / {entry['job']}"
    out = {"kind": kind, "id" if kind == "test" else "job": entry["id"] if kind == "test" else entry["job"], "name": name,
           "state": entry["state"], "flakes": entry["flake_events"], "runs": entry["runs"],
           "last_flake": (entry.get("last_flake") or "")[:10] or None}
    if kind == "test" and entry.get("message"):
        out["fails_with"] = entry["message"]
    if kind == "job" and entry.get("top_step"):
        out["failing_step"] = entry["top_step"]
    if entry.get("owners"):
        out["owners"] = entry["owners"]
    return out


def _hours(secs) -> float | None:
    return None if secs is None else round(secs / 3600, 1)


# The default set: the questions a coding agent asks before and while it changes code, where history and evidence
# across repos beat a live search. Every other tool loads with tools="all" (`stackvitals serve --tools all`).
CORE_TOOLS = ("ci_failure", "is_known_flake", "ci_health", "repo_brief", "preflight", "who_should_review", "pr_queue",
              "check_package", "scan_lockfile", "insights", "delivery_health")


def build_server(app: App | None = None, ci_api=ActionsAPI, ci_home: Path | None = None,
                 ci_token: str | None = None, flow_gql=local_gql, tools: str = "all") -> MCPServer:
    """The suite's one MCP server: MergeScout's contribution tools plus the CI Health tools; tools="core" keeps only the
    default set."""
    server = build_contribute(app or App())

    def result_for(repo: str, days: int) -> tuple[dict, str]:
        # The same reader as the CLI and the brief: published file, else a fresh local copy, else a live read with tests.
        return services.ci_result(repo, days, ci_token or ci_cli.token(), Path(ci_home or ci_cli.home()), make_api=ci_api)

    def local_flow(repo: str, tok: str, months: int = 3) -> tuple[FlowStore, str]:
        # A local copy read within the hour answers at once; otherwise read the last 3 months live.
        now = datetime.now(timezone.utc)
        store = FlowStore(Path(ci_home or ci_cli.home()) / "flow" / repo.replace("/", "__"))
        last = store.state().get("last_collect")
        if not (last and (now - datetime.fromisoformat(last.replace("Z", "+00:00"))).total_seconds() < 3600):
            owner, name = repo.split("/", 1)
            # Three months answer an agent quickly; the CLI reads a full year.
            flow_collect(flow_gql(tok), store, owner, name, now, months=months)
            source = f"read live from GitHub, PRs updated in the last {months} months"
        else:
            source = "local copy read within the hour"
        return store, source

    def flow_for(repo: str) -> tuple[dict, str]:
        tok = ci_token or ci_cli.token()
        try:
            found = accept(json.loads(ci_api(tok, repo, max_requests=10).file("docs/flow.json", BRANCH)))
        except (APIError, ValueError):
            found = None
        if found is not None:
            return found, "stackvitals-data branch"
        store, source = local_flow(repo, tok)
        return flow_build(store.load(), store.repo(), datetime.now(timezone.utc), owner=repo.split("/")[0],
                          people_speed=True, asks=store.asks(),
                          bench=flow_peers.load(tok, Path(ci_home or ci_cli.home()) / "bench")), source

    @server.tool()
    def triage_pr(repo: str, pr: int = 0) -> dict:
        """For maintainers: the chance each open pull request from an outside contributor gets merged within 30 days,
        with the main reasons, from a model trained on outcomes across public repos. Private to you: never stored or
        posted. repo: owner/name; pr: one PR number, or 0 for all open outside PRs."""
        def run():
            from stackvitals.flow import triage as tri
            from stackvitals.flow.cli import load_model
            tok = ci_token or ci_cli.token()
            model = load_model(tok)
            if model is None:
                raise ValueError("the triage model could not be read")
            # Triage needs a year: the repo's rate and the author's history look back that far.
            store, source = local_flow(repo, tok, months=12)
            data = store.load()
            if pr:
                data = {"open": [p for p in data["open"] if p["n"] == int(pr)], "closed": data["closed"]}
            out = tri.triage(data, model, datetime.now(timezone.utc))
            return {"repo": repo, "source": source, **out}
        return _safe(run)()

    @server.tool()
    def preflight(repo: str, paths: list[str], lines: int = 0) -> dict:
        """Before opening a pull request: what merged PRs touching these files usually include (tests, changelog,
        docs, size), what this change is missing, and what maintainers most often ask for in review there.
        repo: owner/name; paths: files the change touches; lines: lines added plus removed."""
        def run():
            tok = ci_token or ci_cli.token()
            store, source = local_flow(repo, tok)
            owner, name = repo.split("/", 1)
            collect_asks(flow_gql(tok), store, owner, name, store.load()["closed"], cap=300)
            data, now = store.load(), datetime.now(timezone.utc)
            prs = data["open"] + data["closed"]
            habits = norms(prs, paths, now)
            return {"repo": repo, "source": source, **habits, "missing": gaps({"paths": paths, "add": lines}, habits),
                    "maintainers_ask_for": flow_preflight(prs, store.asks(), paths, now)["asks"][:5]}
        return _safe(run)()

    @server.tool()
    def repo_brief(repo: str) -> dict:
        """Before working in an unfamiliar repo: how changes get merged there, measured from its history (things its files
        don't say). Per folder: what merged PRs include, who reviews there and how fast, CODEOWNERS; CI jobs and tests
        known to be flaky (re-run before chasing a failure); how outside PRs fare against similar repos. Every number
        comes with its count. repo: owner/name."""
        def run():
            tok = ci_token or ci_cli.token()
            store, source = local_flow(repo, tok, months=12)
            owner, name = repo.split("/", 1)
            collect_asks(flow_gql(tok), store, owner, name, store.load()["closed"], cap=300)
            try:
                ci, ci_source = result_for(repo, 14)
            except (APIError, OutOfBudget) as exc:
                ci, ci_source = None, f"not read ({exc})"
            brief = build_brief(repo, store.load(), store.repo(), store.asks(), ci,
                                flow_peers.load(tok, Path(ci_home or ci_cli.home()) / "bench"), datetime.now(timezone.utc))
            return {"brief": render_brief(brief), "facts": brief, "source": f"pull requests: {source}; CI: {ci_source}"}
        return _safe(run)()

    deps_cache = {}

    def deps_evidence() -> dict | None:
        # Read once an hour: the files are about 6 MB and change once a day.
        if not deps_cache or time.time() - deps_cache["at"] > 3600:
            deps_cache.update(ev=load_evidence(ci_token or ci_cli.token(), (ci_home or ci_cli.home()) / "deps"), at=time.time())
        return deps_cache["ev"]

    @server.tool()
    def supply_chain(repo: str) -> dict:
        """A repo's supply chain from its dependency graph, as its weekly StackVitals run keeps it: packages by
        ecosystem, the ones against its licence rule (and the ones a decision accepted), packages with no known licence,
        licence changes between quarters, and projects whose OpenSSF Scorecard dropped a point or more or is under 4."""
        def run():
            found, source = services.supply(repo, ci_token or ci_cli.token(), make_api=ci_api)
            return {"repo": repo, "source": source, **(found or {})}
        return _safe(run)()

    @server.tool()
    def check_package(name: str, ecosystem: str = "") -> dict:
        """Before adding or upgrading a dependency: how upgrades of this npm or PyPI package went across thousands of
        public repos, whether its maintainers still merge outside fixes, its source repo, advisories and malware records,
        and a verdict (use / monitor / investigate, or none when evidence is thin) with the counts behind it.
        name: "requests" or "pypi:requests"; ecosystem: "npm" or "pypi" (optional)."""
        def run():
            ev = deps_evidence()
            if ev is None:
                return {"error": "The dependency evidence couldn't be loaded (no token or files)."}
            return {"results": deps_find(name, ev, datetime.now(timezone.utc), ecosystem or None), "note": DEPS_NOTE}
        return _safe(run)()

    @server.tool()
    def scan_lockfile(path: str) -> dict:
        """Every package a lockfile pins, the ones that need a look first, each with its verdict and main reason.
        Reads package-lock.json, npm-shrinkwrap.json, requirements*.txt, uv.lock, poetry.lock and Pipfile.lock.
        path: the lockfile on this machine."""
        def run():
            ev = deps_evidence()
            if ev is None:
                return {"error": "The dependency evidence couldn't be loaded (no token or files)."}
            now = datetime.now(timezone.utc)
            pinned = dict.fromkeys((e, n) for e, n, _ in read_lockfile(Path(path)))
            found = sorted((deps_dossier(e, n, ev, now) for e, n in pinned), key=lambda d: (DEPS_ORDER[d["verdict"]], d["package"]))
            return {"counts": {v or "not_enough_evidence": sum(1 for d in found if d["verdict"] == v) for v in DEPS_ORDER},
                    "packages": [{"ecosystem": d["ecosystem"], "package": d["package"], "verdict": d["verdict"],
                                  "reason": (d["reasons"] or [None])[0]} for d in found], "note": DEPS_NOTE}
        return _safe(run)()

    @server.tool()
    def who_should_review(repo: str, pr: int) -> dict:
        """Up to 3 people who should review an open pull request: who wrote and reviewed the same areas, code owners,
        how many reviews each already has open and how fast they usually answer. repo: owner/name; pr: its number."""
        def run():
            store, source = local_flow(repo, ci_token or ci_cli.token())
            data, now = store.load(), datetime.now(timezone.utc)
            target = next((p for p in data["open"] if p["n"] == int(pr)), None)
            if target is None:
                raise ValueError(f"#{pr} is not an open pull request updated in the last 3 months")
            result = flow_build(data, store.repo(), now, owner=repo.split("/")[0], people_speed=True)
            text = store.repo().get("codeowners")
            owners = {path: codeowners_for(path, text) for path in target.get("paths") or []} if text else {}
            speed = {r["reviewer"]: r["median_s"] for r in result.get("responders", [])}
            load = {r["reviewer"]: r["open_requests"] for r in result["load"]}
            picks = suggest_reviewers(target, expertise(data["open"] + data["closed"], now), load, owners, speed)
            return {"repo": repo, "pr": int(pr), "source": source, "already_requested": target["rq"],
                    "suggested": [{"login": s["login"], "why": s["why"]} for s in picks]}
        return _safe(run)()

    @server.tool()
    def pr_queue(repo: str) -> dict:
        """Open pull requests and who has to act next on each (reviewers, the author or maintainers), since when,
        and whether that is longer than usual for this repo. repo: owner/name."""
        def run():
            result, source = flow_for(repo)
            live = [q for q in result["queue"] if not q["stale"]]
            return {"repo": repo, "source": source, "stale": result["stale"],
                    "waiting": [{"pr": q["n"], "title": q["title"], "author": q["author"], "outsider": q["outsider"],
                                 "waiting_on": q["who"] or [q["actor"]], "actor": q["actor"], "why": q["why"],
                                 "for_hours": _hours(q["waiting_s"]), "usual_hours": _hours(q["usual_s"]),
                                 "overdue": q["slow"]} for q in live[:20]]}
        return _safe(run)()

    @server.tool()
    def flow_health(repo: str) -> dict:
        """How a repo's pull requests flow: hours waiting for a first review, in review and to merge (GitHub's stages),
        and how insiders and outside contributors fare (merge rate, first-review wait). repo: owner/name."""
        def run():
            result, source = flow_for(repo)
            group = lambda g: {"merge_rate": result["groups"][g]["merge_rate"],  # noqa: E731
                               "first_review_median_hours": _hours(result["groups"][g]["pickup"]["median_s"]),
                               "merged": result["groups"][g]["merged"]}
            return {"repo": repo, "source": source, "window_days": result["window_days"], "open": result["open"],
                    "stages": {k: {"median_hours": _hours(v["median_s"]), "p90_hours": _hours(v["p90_s"]), "n": v["n"]}
                               for k, v in result["stages"].items()},
                    "merged_without_review": result["merged_without_review"],
                    "insiders": group("insider"), "outsiders": group("outsider"),
                    "delivery": result.get("delivery"), "compared_with_similar_repos": result.get("peers"),
                    "known_by_one_person": [{"area": a["area"], "owner": a["owner"], "share": a["share"]}
                                            for a in (result.get("knowledge") or {}).get("areas", []) if a["single_owner"]][:10]}
        return _safe(run)()

    def community_for(repo: str) -> tuple[dict, str]:
        tok = ci_token or ci_cli.token()
        try:
            found = accept(json.loads(ci_api(tok, repo, max_requests=10).file("docs/community.json", BRANCH)))
        except (APIError, ValueError):
            found = None
        if found is not None:
            return found, "stackvitals-data branch"
        from stackvitals.community.cli import local_community
        result, stats = local_community(repo, tok, datetime.now(timezone.utc), make_gql=flow_gql, make_api=ci_api,
                                        root=Path(ci_home or ci_cli.home()))
        note = "" if stats["complete"] else ", partly (GitHub's hourly limit; ask again later for more)"
        return result, f"read live from GitHub, last 12 months{note}"

    @server.tool()
    def community_health(repo: str) -> dict:
        """How a repo treats newcomers: first-time contributors and how many came back, how fast outside PRs and issues
        get a first answer (newcomers and regulars apart), who carries the merged work (people, the top person's share and
        the bus factor, no names, with similar public repos' typical values), its community score against similar public
        repos (with the facts behind it), star growth, and what keeps newcomers across public repos. repo: owner/name."""
        def run():
            result, source = community_for(repo)
            f, st, tr = result["funnel"], result.get("stars") or {}, result.get("traffic")
            return {"repo": repo, "source": source, "score": result.get("score"), "facts": result.get("facts"),
                    "newcomers": {"first_time": f["newcomers"], "judged": f["judged"], "came_back": f["returned"],
                                  "return_rate": f["return_rate"], "regulars": f["regulars"], "maintainers": f["maintainers"]},
                    "first_answers": result["answers"], "first_answers_by_tenure": result.get("tenure"),
                    "who_carries_the_work": result.get("dependency"), "newcomers_waiting": result["waiting_total"],
                    "stars": {k: st.get(k) for k in ("gained_12w", "growth_12w", "peers")},
                    "traffic": ({k: tr[k] for k in ("days", "since", "views_total", "visitors_total", "clones_total", "referrers")} if tr
                                else "not kept (needs a token with Administration read)"),
                    "what_keeps_newcomers": result.get("lever")}
        return _safe(run)()

    @server.tool()
    def newcomers_waiting(repo: str) -> dict:
        """Open pull requests and issues that are someone's first contribution to a repo and that nobody has answered yet,
        oldest first: the replies that most help a project keep new contributors. repo: owner/name."""
        def run():
            result, source = community_for(repo)
            kind = {"pr": "pull", "issue": "issues"}
            return {"repo": repo, "source": source, "total": result["waiting_total"],
                    "waiting": [{"kind": w["kind"], "number": w["n"], "days": w["days"],
                                 "url": f"https://github.com/{repo}/{kind.get(w['kind'], 'issues')}/{w['n']}"}
                                for w in result["waiting"][:30]]}
        return _safe(run)()

    def portal_for(org: str) -> tuple[dict, str]:
        tok = ci_token or ci_cli.token()
        try:
            found = accept(json.loads(ci_api(tok, f"{org}/portal", max_requests=10).file("portal/catalog.json", BRANCH)))
        except (APIError, ValueError):
            found = None
        if found is not None:
            return found, f"{org}/portal {BRANCH} branch"
        from stackvitals.portal.catalog import build_catalog
        from stackvitals.portal.scorecard import rules_or_default, score_catalog
        now = datetime.now(timezone.utc)
        catalog = build_catalog(ci_api(tok, f"{org}/portal", max_requests=600), org, "local", now, None)
        rules, exemptions, _ = rules_or_default(None)
        score_catalog(catalog, rules, exemptions, now, None)
        return catalog, "read live from GitHub (up to 600 requests; no published portal catalog was found)"

    def _active(catalog: dict) -> list[dict]:
        return [r for r in catalog.get("repos") or [] if not r.get("archived") and not r.get("fork")]

    @server.tool()
    def org_catalog(org: str) -> dict:
        """An org's repos at a glance: how many reach each scorecard level (bronze, silver, gold), owner status counts,
        the rules that fail most often, and the typed catalog from repos' catalog-info.yaml files (kind, type, lifecycle,
        owner checked against CODEOWNERS, system, depends on). Reads the org's Portal catalog when it publishes one.
        org: the org name."""
        def run():
            from stackvitals.portal.pages import catalog_entities
            catalog, source = portal_for(org)
            active = _active(catalog)
            entities, problems, files = catalog_entities(active)
            scored = [r for r in active if r.get("score")]
            failed = {}
            for r in scored:
                for res in r["score"].get("results") or []:
                    if res.get("result") == "fail":
                        failed[res["id"]] = failed.get(res["id"], 0) + 1
            levels = {"gold": 0, "silver": 0, "bronze": 0, "below bronze": 0}
            for r in scored:
                levels[r["score"].get("level") or "below bronze"] += 1
            return {"org": org, "source": source, "built_at": catalog.get("built_at"), "repos": len(active), "levels": levels,
                    "most_failed_rules": [{"rule": k, "repos": v} for k, v in sorted(failed.items(), key=lambda kv: (-kv[1], kv[0]))[:10]],
                    "repos_list": [{"repo": r["name"], "level": (r.get("score") or {}).get("level"),
                                    "owners": (r.get("owners") or {}).get("status")} for r in active[:50]],
                    "catalog": {"repos_with_file": files, "problems": [f"{repo}: {p}" for repo, p in problems[:20]],
                                "entities": [{k: e.get(k) for k in ("repo", "kind", "name", "type", "lifecycle", "owner", "owner_check",
                                                                    "system", "depends_on", "provides_apis")} for e in entities[:100]]}}
        return _safe(run)()

    @server.tool()
    def repo_scorecard(repo: str) -> dict:
        """One repo's scorecard level and the evidence behind every failing rule, from its org's Portal catalog.
        repo: owner/name."""
        def run():
            catalog, source = portal_for(repo.split("/")[0])
            entry = next((r for r in catalog.get("repos") or [] if r.get("name", "").lower() == repo.lower()), None)
            if entry is None or not entry.get("score"):
                raise ValueError(f"{repo} isn't in its org's catalog yet (archived, a fork, or not checked yet)")
            results = entry["score"].get("results") or []
            return {"repo": repo, "source": source, "level": entry["score"].get("level"),
                    "failing": [{"rule": x["id"], "evidence": x["evidence"]} for x in results if x["result"] == "fail"],
                    "passing": [x["id"] for x in results if x["result"] in ("pass", "exempt")],
                    "not_available": [x["id"] for x in results if x["result"] == "not available"]}
        return _safe(run)()

    @server.tool()
    def owners_health(org: str) -> dict:
        """Who owns what in an org, checked: repos whose CODEOWNERS has errors, empty teams or departed people (weak), and
        repos without a CODEOWNERS file (with suggestions from recent committers). org: the org name."""
        def run():
            catalog, source = portal_for(org)
            active = [r for r in _active(catalog) if r.get("owners")]
            counts = {s: sum(1 for r in active if r["owners"].get("status") == s) for s in ("valid", "weak", "none")}
            return {"org": org, "source": source, "counts": counts,
                    "weak": [{"repo": r["name"], "reasons": r["owners"].get("reasons") or []}
                             for r in active if r["owners"].get("status") == "weak"][:30],
                    "none": [{"repo": r["name"], "suggested": r["owners"].get("suggested") or []}
                             for r in active if r["owners"].get("status") == "none"][:30]}
        return _safe(run)()

    @server.tool()
    def ci_health(repo: str, days: int = 14) -> dict:
        """A repo's CI health: flaky jobs and tests (failed, then passed with no code change), jobs that keep
        failing, jobs that got slower, line coverage with each pull request's patch coverage when CI uploads a
        coverage report, pushes green on the first try with their likely ranges, and this week against the four before
        (only changes beyond noise are flagged; steady ones say how big a change they could have shown). repo: owner/name."""
        def run():
            result, source = result_for(repo, max(1, min(days, 90)))
            flaky = lambda items: [i for i in items if i["state"] in ("flaky", "suspect")]
            return {"repo": repo, "source": source, "window_days": result["window_days"], "runs": result["runs"],
                    "rerun_share": result["rerun_share"],
                    "flaky_tests": [_brief(t, "test") for t in flaky(result.get("tests", []))][:10],
                    "flaky_jobs": [_brief(j, "job") for j in flaky(result["jobs"])][:10],
                    "keeps_failing": [_brief(j, "job") for j in result["jobs"] if j["state"] == "broken"]
                    + [_brief(t, "test") for t in result.get("tests", []) if t["state"] == "broken"],
                    "getting_slower": [{"job": j["job"], **j["slower"]} for j in result["jobs"] if j["slower"]],
                    "coverage": result.get("coverage"), "compared_with_similar_repos": result.get("benchmark"),
                    "pushes": result.get("pushes"), "this_week": result.get("changes")}
        return _safe(run)()

    @server.tool()
    def is_known_flake(repo: str, name: str) -> dict:
        """Before fixing a failing test or job, check whether it is a known flake in this repo.
        name: part of the test or job name (e.g. "test_upload" or "e2e")."""
        def run():
            result, source = result_for(repo, 30)
            needle = name.lower()
            matches = [(t, "test") for t in result.get("tests", []) if needle in t["id"].lower()]
            matches += [(j, "job") for j in result["jobs"] if needle in j["job"].lower()]
            matches.sort(key=lambda m: (m[0]["state"] not in KNOWN | {"broken"}, -m[0]["flake_events"]))
            best = matches[0][0] if matches else None
            if best and best["state"] in KNOWN and best["flake_events"] + (best["state"] == "fixed") > 0:
                # A job or test is called known flaky only with enough flakes; fewer leave the change a likely cause.
                verdict = "flaked before" if best["flake_events"] < SAFE_FLAKES else "known flaky"
            elif best and best["state"] == "broken":
                verdict = "already failing"
            else:
                verdict = "no history"
            return {"repo": repo, "name": name, "verdict": verdict, "advice": ADVICE[verdict], "source": source,
                    "matches": [_brief(m, k) for m, k in matches[:5]]}
        return _safe(run)()

    @server.tool()
    def ci_failure(run: str) -> dict:
        """Explain a failed CI run: each failure is called known flaky (it flaked before and its log shows a flake's sign:
        check the error, then re-run it), maybe yours (it flaked before, but its error names a file the pull request
        changed), flaked before (it has flaked, but rarely, in another step or with no flake's sign: check the change first), already failing on the default branch (the same error),
        outside failure (a registry, network or runner), maybe flaky (it failed the way flaky checks do: re-run once to
        tell), PR details (a check on the PR's title, description or labels: fix the PR, not the code), or new (likely
        from the change). run: the run's URL."""
        def go():
            m = re.search(r"github\.com/([^/]+/[^/]+)/actions/runs/(\d+)", run)
            if not m:
                raise ValueError("Give the run's URL, like https://github.com/owner/name/actions/runs/123")
            repo, run_id = m[1], int(m[2])
            api = ci_api(ci_token or ci_cli.token(), repo, max_requests=300)
            body = api._get(f"/repos/{repo}/actions/runs/{run_id}")
            att = body.get("run_attempt") or 1
            data = {"runs": [run_record(body, att)],
                    "jobs": [job_record(j, run_id, att) for j in api.jobs(run_id, att)],
                    "tests": _reports(api, body, {att: body.get("run_started_at")}, TEST_ARTIFACTS, 50_000_000, set())}
            result, source = result_for(repo, 30)
            branch = result.get("default_branch")
            try:
                branch = branch or (api._get(f"/repos/{repo}") or {}).get("default_branch")
                mains = _default_branch_failures(api, repo, data, body, branch)
            except APIError:
                mains = 0  # without the default branch's record, "already failing" just can't be said
            cache = {}
            items = classify(api, data, {**result, "default_branch": branch}, run_id, cache)
            logs = cache.get(run_id) or {}
            for i in items:
                # What an agent would otherwise open itself: the job, its error lines, and how often the verdict held.
                if i.get("job_id"):
                    i["url"] = f"https://github.com/{repo}/actions/runs/{run_id}/job/{i['job_id']}"
                    i["errors"] = error_excerpt(logs.get(i["job_id"]))
                i["right_so_far"] = TRACK_RECORD.get(i["verdict"])
            checked = [f"this run's {sum(j['c'] in ('failure', 'timed_out') for j in data['jobs'])} failed jobs and their "
                       f"failing steps' logs ({len(logs)} read)",
                       f"the default branch ({branch}): {mains} failed pushes of this workflow in the 3 days before"
                       if branch and body.get("head_branch") != branch else "this run is on the default branch",
                       f"{result.get('window_days', 30)} days of this repo's CI history ({source})"]
            return {"repo": repo, "run": run_id, "conclusion": body.get("conclusion"), "source": source,
                    "failures": items, "checked": checked, "summary": failure_summary(items)}
        return _safe(go)()

    @server.tool()
    def propose_change(repo: str, settings: dict | None = None, command: str | None = None, note: str = "") -> dict:
        """A link to a prefilled GitHub issue that changes the repo's StackVitals settings and/or records a decision
        (quarantine, mute, acknowledge, snooze, exclude, accept). Nothing changes until a person with access opens the link
        and presses Submit; the StackVitals workflow then applies it and answers. Checked first with the Action's own
        parsers. settings: {"alerts.pickup_p75_hours": 6, ...} (keys as in docs/settings.md); command: one line like
        "/stackvitals mute test:<id> for 7d because <reason>"; note: context for the person. Give the person the url."""
        def run():
            from stackvitals.core.propose import ProposalError, proposal
            try:
                return {"repo": repo, **proposal(repo, settings, command, note)}
            except ProposalError as exc:
                return {"repo": repo, "error": str(exc)}
        return _safe(run)()

    @server.tool()
    def insights(repo: str, days: int = 30) -> dict:
        """What to fix first, across modules, and the findings that join CI and pull requests. findings: each a sentence with
        its number, n, evidence links and the action, ranked by hours of waiting or outage at stake (flaky jobs and tests by
        the PR-hours they cost, reviews asked for and not started, incidents after deployments, dependency updates with
        failing checks, the outside-contributor review gap). red_ci: how long merged PRs sat ready for review with a
        failing check on their newest commit, each wait traced to the run that started it and what ended it, with counts
        and ranges. repo: owner/name; days: history to read (max 90)."""
        def run():
            tok, home = ci_token or ci_cli.token(), Path(ci_home or ci_cli.home())
            found, _ = services.findings(repo, max(1, min(days, 90)), tok, home, make_api=ci_api, make_gql=flow_gql)
            out, source = services.red_ci(repo, max(1, min(days, 90)), tok, home, make_api=ci_api, make_gql=flow_gql)
            return {"repo": repo, "source": source, "findings": found, "red_ci": out}
        return _safe(run)()

    def delivery_for(repo: str) -> tuple[dict, str]:
        return services.delivery(repo, 90, ci_token or ci_cli.token(), Path(ci_home or ci_cli.home()), make_api=ci_api,
                                 make_gql=flow_gql)

    @server.tool()
    def delivery_health(repo: str) -> dict:
        """A repo's delivery: DORA's keys with DevLake's counting and tiers (deployment frequency, lead time for changes,
        change failure rate, recovery) plus deployment rework rate, where deployments came from, cycle time P50/P75, sizes,
        stuck PRs, coding agents' PRs and people's AI-marked PRs each compared like with like (the same author's other PRs,
        or people's PRs of the same month and size) on reverts, CI failures, failed deploys and merges, with ranges,
        matched shares and the gap each could detect,
        merge-queue health, where the work went by month (feature, fix, maintenance, security, docs, with how each PR was
        sorted), and with Jira or Linear connected, issue lead and cycle time by type and the last sprints. Each DORA key
        carries its likely range and, when the range crosses a tier line, both tiers; `this_week` checks the latest week
        against the four before and flags only changes beyond noise."""
        def run():
            out, source = delivery_for(repo)
            keep = ("window_days", "prs", "deploy_source", "deploy_confidence", "deploy_names", "deployments_unreadable", "dora",
                    "sizes", "merge_frequency", "review_depth", "merged_without_review", "outliers", "ai", "tracker",
                    "merge_queue", "investment")
            return {"repo": repo, "source": source, **{k: out.get(k) for k in keep},
                    "cycle_time": {k: out["phases"][k] for k in ("cycle", "cycle_to_merge")},
                    "stuck": {k: len(v) for k, v in out["stuck"].items()}, "this_week": out.get("changes"),
                    "generated": out.get("generated")}
        return _safe(run)()

    @server.tool()
    def cycle_time(repo: str) -> dict:
        """Pull request cycle time in LinearB's four phases (coding, pickup, review, deploy, with review split into approve and merge) with P50, P75,
        a range for the median, sample sizes, LinearB's band for each P75 and the outliers left out."""
        def run():
            out, source = delivery_for(repo)
            return {"repo": repo, "source": source, "phases": out["phases"], "outliers": out["outliers"],
                    "window_days": out["window_days"], "generated": out.get("generated")}
        return _safe(run)()

    @server.tool()
    def stuck_prs(repo: str) -> dict:
        """Open pull requests that are stuck, by LinearB's published cut-offs: review asked 3+ days ago with no review,
        ready for 30+ days, 10+ comments or reviews; and ours: failing checks nobody acted on for a day."""
        def run():
            out, source = delivery_for(repo)
            return {"repo": repo, "source": source, "stuck": out["stuck"], "generated": out.get("generated")}
        return _safe(run)()

    @server.tool()
    def reviewer_load(repo: str) -> dict:
        """Who holds the open pull requests: each reviewer's open review requests, the PRs waiting on them with the
        reason, and (asked on demand with your own token) how fast each one usually answers."""
        def run():
            result, source = flow_for(repo)
            holding = {}
            for q in result.get("queue") or []:
                if q.get("actor") == "reviewers":
                    for who in q.get("who") or []:
                        holding.setdefault(who, []).append({"pr": q["n"], "why": q.get("why"), "since": q.get("since")})
            speed = {r["reviewer"]: {"median_hours": _hours(r["median_s"]), "n": r["n"]} for r in result.get("responders") or []}
            return {"repo": repo, "source": source,
                    "reviewers": [{"reviewer": r["reviewer"], "open_requests": r["open_requests"], "oldest_since": r["oldest_since"],
                                   "holding": holding.get(r["reviewer"], []), "answers": speed.get(r["reviewer"])}
                                  for r in result.get("load") or []]}
        return _safe(run)()

    @server.tool()
    def test_status(repo: str, test: str) -> dict:
        """A test's status and why: flaky, keeps failing, one flake seen or fixed; the monitors holding it there (pass on
        retry, failure rate, keeps failing), labels (slow, timeout inflation), since when, any mute, and the failure group
        it belongs to (other tests failing the same way). test: part of the test's name."""
        def run():
            result, source = result_for(repo, 30)
            groups = {g["id"]: g for g in result.get("failure_groups") or []}
            needle = test.lower()
            hits = [t for t in result.get("tests", []) if needle in t["id"].lower()][:10]
            keep = ("id", "state", "monitors", "labels", "since", "failure_rate", "muted_until", "flake_events", "runs",
                    "failures", "message", "last_flake", "owners")
            return {"repo": repo, "source": source,
                    "matches": [{**{k: t.get(k) for k in keep if k in t},
                                 "group": groups.get(t.get("group"))} for t in hits]}
        return _safe(run)()

    @server.tool()
    def failure_group(repo: str, group: str = "") -> dict:
        """Failures with one cause across tests and runs (same exception at the same place in the code), biggest first,
        with links to example runs and an investigation prompt (what failed, where, how often, the runs, what to find out);
        group: an id (or its start) from test_status or ci_failure, empty for all."""
        def run():
            from stackvitals.ci.investigate import prompt
            result, source = result_for(repo, 30)
            found = [g for g in result.get("failure_groups") or [] if g["id"].startswith(group)]
            for g in found:
                g["investigation_prompt"] = prompt(repo, g, result.get("tests") or [])
                g.pop("prompt", None)
                g["examples"] = [{**x, "url": f"https://github.com/{repo}/actions/runs/{x['run']}/attempts/{x['att']}"}
                                 for x in g.get("examples") or [] if int(x.get("run") or 0) > 0]
            return {"repo": repo, "source": source, "groups": found[:20]}
        return _safe(run)()

    @server.tool()
    def ci_slowest(repo: str) -> dict:
        """The slowest jobs and tests in a repo's CI with daily median times, the ones that got slower in the last 7 days,
        tests added in the last 2 weeks (and whether they already fail or flake) and tests skipped now, since when."""
        def run():
            result, source = result_for(repo, 14)
            jobs = sorted((j for j in result["jobs"] if j["median_s"]), key=lambda j: -j["median_s"])[:10]
            return {"repo": repo, "source": source,
                    "slowest_jobs": [{"job": j["job"], "median_s": j["median_s"], "p95_s": j["p95_s"],
                                      "slower": j["slower"], "trend": j.get("trend")} for j in jobs],
                    "slowest_tests": (result.get("slow_tests") or [])[:10],
                    "new_tests": (result.get("new_tests") or [])[:20], "skipped_tests": (result.get("skipped_tests") or [])[:20]}
        return _safe(run)()

    if tools == "core":
        # Fewer tools keep an agent's context small; the rest stay one flag away.
        for name in [x.name for x in server._tool_manager.list_tools() if x.name not in CORE_TOOLS]:
            server.remove_tool(name)
    return server
