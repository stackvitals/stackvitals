"""Delivery intelligence: LinearB's six PR phases (coding, pickup, review, approve, merge, deploy) with P50 and P75 and its
outlier rule, DevLake's DORA counting with its 2023 and 2021 tier tables, deployments and incidents found from what a
GitHub repo already has, stuck pull requests, PR sizes, and what can be said in public about AI-assisted work."""
import math
import re
from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from stackvitals.connectors import tracker as tracked
from stackvitals.core import investment
from stackvitals.connectors.base import BACKFILL_DAYS
from stackvitals.core.actors import kind_of
from stackvitals.core.ai_outcomes import assisted_by, is_revert, outcomes, revert_target, rework_rate
from stackvitals.core import agent_ledger, bugs, change_risk, changes, identity, releases, what_changed
from stackvitals.core.stats import median, percentile, quantile_range, wilson
from stackvitals.core.time import iso, secs

PHASES = ("coding", "pickup", "review", "approve", "merge", "deploy", "cycle", "cycle_to_merge")
# LinearB's 2026 bands on P75 hours (elite below the first number, good up to the second, fair up to the third).
LINEARB_BANDS = {"coding": (0.9, 4, 23), "pickup": (1, 4, 16), "review": (3, 14, 24), "approve": (10, 22, 42),
                 "merge": (1, 3, 16), "deploy": (16, 106, 277), "cycle": (25, 72, 161)}
SIZE_EDGES = (100, 155, 228)
OUTLIER_HOURS = 60 * 24
OUTLIER_MIN_PRS = 30
EVIDENCE_MAX = 500  # items kept per number in delivery.json; the longest lead times first, and the total is said
PHASE_EVIDENCE_MAX = 200  # pull requests kept per review phase, longest first
MIN_PRS = 10  # under this a phase shows its n and "not enough data"
LIGHTNING_HOURS = 20 / 60
HANGING_HOURS = 72
LONG_LIVED_HOURS = 30 * 24
BUSY_COMMENTS = 10
# Review bots that leave AI reviews on pull requests (their reviews never count as a person's pickup).
AI_REVIEWERS = {"coderabbitai", "copilot-pull-request-reviewer", "gemini-code-assist", "sourcery-ai", "greptile-apps",
                "cursor", "qodo-merge-pro", "codeant-ai", "ellipsis-dev", "korbit-ai", "bito-code-review"}


def _hours(a: str | None, b: str | None) -> float | None:
    s = secs(a, b)
    return None if s is None else s / 3600


def _minutes_up(a: str | None, b: str | None) -> int | None:
    s = secs(a, b) if a and b else None
    return None if s is None else math.ceil(s / 60)


def _minutes_down(a: str | None, b: str | None) -> int | None:
    s = secs(a, b) if a and b else None
    return None if s is None else int(s // 60)


def _person(login: str | None, typ: str | None, author: str | None) -> bool:
    return bool(login) and login != author and kind_of(login, typ) == "person"


def phases(p: dict, deployed_at: str | None = None, cal: dict | None = None) -> dict:
    """One merged PR's phases in hours, LinearB's definitions: coding (first commit to opened), pickup (ready to the first
    other person's comment or review; to the merge when nobody answered), review (that to merge), approve (first activity
    to first approval), merge (approval to merge), deploy (merge to the deployment that shipped it)."""
    from stackvitals.core.calendar import elapsed_hours, is_set
    from stackvitals.flow.analyze import ready_at
    # With a working calendar, weekends and holidays are left out of every phase (DevLake's minutes below stay exact).
    _hours = (lambda a, b: elapsed_hours(a, b, cal)) if is_set(cal) else globals()["_hours"]  # noqa: N806
    au, merged = p.get("au"), p.get("mg")
    ready = ready_at(p) or p["cr"]
    events = p.get("ev") or []
    acts = [e[1] for e in events if e[0] == "review" and len(e) > 5 and e[3] != "PENDING" and _person(e[2], e[5], au)]
    acts += [c[0] for c in p.get("cm") or [] if len(c) > 3 and c[0] and _person(c[1], c[3], au)]
    acts = sorted(a for a in acts if a >= ready and (not merged or a <= merged))
    first = acts[0] if acts else None
    approvals = sorted(e[1] for e in events if e[0] == "review" and len(e) > 5 and e[3] == "APPROVED" and _person(e[2], e[5], au)
                       and (first is None or e[1] >= first) and (not merged or e[1] <= merged))
    approval = approvals[0] if approvals else None
    coding = max(0.0, (_hours(p.get("fa"), p["cr"]) or 0.0)) if p.get("fa") else None
    pickup = _hours(ready, first or merged)
    review = (_hours(first, merged) if first else 0.0) if merged else None
    deploy = _hours(merged, deployed_at) if merged and deployed_at else None
    to_merge = (coding or 0.0) + pickup + review if merged and pickup is not None and review is not None else None
    # DevLake's pr_cycle_time: coding + opened to merged + deploy, each in whole minutes rounded up; its lead time's basis.
    devlake = sum(_minutes_up(a, b) or 0 for a, b in ((p.get("fa"), p["cr"]), (p["cr"], merged), (merged, deployed_at))) \
        if merged else None
    return {"coding": coding, "pickup": pickup, "review": review, "approve": _hours(first, approval) if first and approval else None,
            "merge": _hours(approval, merged) if approval and merged else None, "deploy": deploy,
            "cycle_to_merge": to_merge, "cycle": to_merge + deploy if to_merge is not None and deploy is not None else None,
            "devlake_cycle_min": devlake, "devlake_cycle": None if devlake is None else devlake / 60,
            "reviewed": first is not None, "first_activity": first}


# Words that mark a workflow as something other than shipping (labelled on 112 workflows of 30 public repos, 2026-10-20).
DEPLOY_DENY = re.compile(r"(?i)(preview|prepare|draft|create|check|verify|validat|\bdocs?\b|storybook|\btest|smoke|blog|notes|"
                         r"beta|pre-?release|canary|nightly|\bnext\b|\bdev\b|continuous|experiment|bump|sbom|\bsign|mirror|notif|populate|cleanup|"
                         r"ensure|block|schedule|pointer|merge|promote|update|\bstart|(?<![a-z])post(?![a-z])|gate\b|"
                         r"temporary|\btmp\b|scratch|\btag\b|authoriz|pages-build|snapshot|\bpr\b|pull request)")
# A plain deploy.yml still says when it ships somewhere else than production.
PLAIN_DENY = re.compile(r"(?i)(preview|\bdocs?\b|storybook|staging|\bdev\b|\btest|pages|demo|sandbox|canary|nightly|beta)")
# Side services ran on 0-7% of main-branch commits, continuous deploys on 30-66% (6 public repos, 2026-10-20).
SIDE_SERVICE_SHARE = 0.15
# Semver prerelease tags GitHub does not flag as prereleases (tauri-v3.0.0-alpha.5, v15.0.0-canary.3).
PRE_TAG = re.compile(r"(?i)[-.](alpha|beta|rc|canary|next|dev|pre|preview|nightly|snapshot|insiders)([-.\d]|$)")
# Explicit production deployments are sure; releases are versions users can install; workflow names are a guess.
# Stages of one commit within this many hours of its first, nothing else deployed between, are one rollout.
ROLLOUT_HOURS = 24
CONFIDENCE = {"deployments api": "high", "releases": "medium", "deploy workflows": "low", "release workflows": "low",
              "merges": "low"}
VERSION_REF = re.compile(r"^v?\d+(\.\d+)*([-.+].*)?$")


def deploy_reason(name: str | None, path: str | None, pattern: str) -> tuple[str | None, str]:
    """deploy_kind with the reason, for the deploy dry run."""
    stem = (path or "").rsplit("/", 1)[-1]
    text = f"{name or ''} {stem}"
    # A file named just deploy, release or publish ships whatever its display name says (labelled repos, 2026-10-22).
    plain = re.fullmatch(r"(?i)(deploy|release|publish)\.ya?ml", stem)
    if not re.search(pattern, text):
        return None, "its name doesn't match deploy_workflow"
    if m := DEPLOY_DENY.search(stem if plain else text):
        return None, f'"{m[0]}" in its name marks it as not shipping to users'
    if plain and (m := PLAIN_DENY.search(name or "")):
        return None, f'its display name says it ships to "{m[0]}", not production'
    kind = "deploy" if re.search(r"(?i)deploy|push-image", text) else "release"
    return kind, f"a {kind} workflow"


def deploy_kind(name: str | None, path: str | None, pattern: str) -> str | None:
    """"deploy" for deploy and image-push workflows, "release" for release and publish ones, None for the rest."""
    return deploy_reason(name, path, pattern)[0]


def is_production(env: str | None, prod: set[str]) -> bool:
    # The first word counts, so Vercel's "Production – web" and "production-eu" are production too.
    return (env or "").lower() in prod or re.split(r"[\s\-–_/:]+", (env or "").lower(), maxsplit=1)[0] in prod


# Environments that are not production, for the dry run: shown, never counted.
ENV_STAGING = re.compile(r"(?i)\b(stag(e|ing)|pre-?prod|preview|dev(elop(ment)?)?|test(ing)?|qa|uat|sandbox|review|canary|beta)\b")
ENV_PUBLISH = re.compile(r"(?i)\b(pypi|testpypi|npm|crates?|nuget|maven|rubygems|github-pages|pages|release|publish|docs?|"
                         r"registry|docker)\b")


def _ships(r: dict, pattern: str, default: str | None, any_result: bool = False, prod_branches: list[str] = ()) -> str | None:
    """The kind of deployment a successful run counts as (any finished run with any_result), else None. A deploy on a
    production branch (release/*, production) ships as one on the default branch does."""
    from fnmatch import fnmatch
    kind = deploy_kind(r.get("wfn"), r.get("path"), pattern)
    if kind is None or (r.get("c") != "success" and not any_result):
        return None
    br, ev = r.get("br") or "", r.get("ev")
    if ev in ("release", "workflow_dispatch") or VERSION_REF.match(br):
        return kind
    # A release workflow on every push to the default branch mostly opens a version PR; only a deploy ships then.
    on_prod = not default or br == default or any(fnmatch(br, pat) for pat in prod_branches)
    return kind if kind == "deploy" and ev in ("push", "schedule") and on_prod else None


def _auto_order(found: dict, ci: dict, default: str | None) -> tuple[tuple, str | None]:
    pushed = {r.get("sha") for r in ci.get("runs") or [] if r.get("ev") == "push" and (not default or r.get("br") == default)}
    shipped_shas = {x["sha"] for x in found["deploy workflows"]}
    # A deploy workflow on few of the default branch's commits is a side service (a docs site, a worker): releases first.
    if pushed and len(shipped_shas & pushed) < SIDE_SERVICE_SHARE * len(pushed):
        if not shipped_shas:
            return ("deployments api", "releases", "deploy workflows", "release workflows"), None
        return (("deployments api", "releases", "deploy workflows", "release workflows"),
                f"deploy workflows ran on under {SIDE_SERVICE_SHARE:.0%} of the default branch's commits (a side "
                "service, like a docs site), so releases come first")
    # Every merge as a deployment is chosen, never guessed: it matched real deployments 8% of the time.
    return tuple(k for k in found if k != "merges"), None


def deploy_attempts(repo: dict, ci: dict, cfg: dict, source: str | None, start: datetime, end: datetime) -> dict | None:
    """Every deploy attempt in the window from the chosen source, failed and cancelled ones too: how many succeeded, and
    how long the successful ones took (Deployments API: created to success; deploy workflows: run start to end)."""
    s, e = iso(start), iso(end)
    d = cfg["delivery"]
    rows = []
    if source == "deployments api":
        prod = {x.lower() for x in d["production"]}
        for x in repo.get("deployments") or []:
            state = {"SUCCESS": "success", "INACTIVE": "success", "FAILURE": "failure", "ERROR": "failure"}.get(x.get("state"))
            if state and is_production(x.get("env"), prod) and s <= (x.get("at") or "") <= e:
                rows.append((state, x.get("at"), x.get("done") if x.get("state") == "SUCCESS" else None))
    elif source in ("deploy workflows", "release workflows"):
        for r in ci.get("runs") or []:
            if (r.get("c") in ("success", "failure", "cancelled", "timed_out") and s <= (r.get("cr") or "") <= e
                    and _ships(r, d["deploy_workflow"], repo.get("default_branch"), True, d.get("production_branches") or [])):
                rows.append(({"timed_out": "failure"}.get(r["c"], r["c"]), r.get("st") or r.get("cr"), r.get("up")))
    else:
        return None
    if not rows:
        return None
    took = sorted(_hours(a, b) * 60 for res, a, b in rows if res == "success" and a and b and b >= a)
    done = [r for r in rows if r[0] in ("success", "failure")]
    return {"source": source, "attempts": len(rows), "succeeded": sum(r[0] == "success" for r in rows),
            "failed": sum(r[0] == "failure" for r in rows), "cancelled": sum(r[0] == "cancelled" for r in rows),
            "success_rate": round(sum(r[0] == "success" for r in done) / len(done), 4) if done else None,
            "median_minutes": round(took[len(took) // 2], 1) if took else None}


def _final_runs(runs: list[dict]) -> list[dict]:
    final = {}
    for r in runs:
        if r["id"] not in final or r["att"] > final[r["id"]]["att"]:
            final[r["id"]] = r
    return list(final.values())


def find_deployments(repo: dict, ci: dict, cfg: dict, prs: list[dict] | None = None) -> tuple[list[dict], str | None]:
    """Successful production deployments, from GitHub's Deployments API, else successful runs of a deploy workflow, else
    published releases, else release or publish workflow runs on a version (D12); several commits in one run count once.
    Release workflows come after releases: their names were right only 2 times in 3 on repos we had not tuned on."""
    found = _sources(repo, ci, cfg, prs)
    d = cfg["delivery"]
    order = {"auto": _auto_order(found, ci, repo.get("default_branch"))[0], "deployments": ("deployments api",),
             "releases": ("releases",), "workflows": ("deploy workflows", "release workflows"), "merges": ("merges",)}[d["source"]]
    for key in order:
        deps = sorted(({**x, "source": key} for x in found[key] if x["finished"]), key=lambda x: x["finished"])
        if deps:
            return deps, key
    return [], None


def _sources(repo: dict, ci: dict, cfg: dict, prs: list[dict] | None = None) -> dict:
    """Every deployment each source would count, before one source is chosen."""
    d = cfg["delivery"]
    prod = {x.lower() for x in d["production"]}
    api = [{"id": f"deployment:{x.get('sha')}:{x.get('at')}", "sha": x.get("sha"), "source": "deployments api",
            "name": x.get("env"),
            # A superseded (inactive) deployment keeps no time of its success: its creation is the closest known.
            "finished": x.get("done") if x.get("state") == "SUCCESS" and x.get("done") else x.get("at")}
           # Recorded ones (sent from another tool through repository_dispatch) count as GitHub's own.
           for x in (repo.get("deployments") or []) + ((repo.get("recorded") or {}).get("deployments") or [])
           if is_production(x.get("env"), prod) and x.get("state") in ("SUCCESS", "INACTIVE")]
    # One change reaching production is one deployment: the same commit rolled out to more regions or stages (eu, us,
    # canary then full) within a day, nothing else between, counts once at its first; a rollback or redeploy counts again.
    rollouts = []
    for x in sorted((x for x in api if x["finished"]), key=lambda x: x["finished"]):
        last = rollouts[-1] if rollouts else None
        if last and x["sha"] and x["sha"] == last["sha"] and _hours(last["finished"], x["finished"]) <= ROLLOUT_HOURS:
            last["stages"] += 1
        else:
            rollouts.append({**x, "stages": 1})
    api = rollouts
    # The commits each one shipped, when the repo query read them (a PR then goes to the deployment holding its merge).
    ranges = repo.get("ranges") or {}
    for prev, x in zip(api, api[1:]):
        if (r := ranges.get(f"{prev['sha']}..{x['sha']}")) and r.get("complete"):
            x["shipped"] = r["shas"]
    default = repo.get("default_branch")
    runs = defaultdict(list)
    for r in _final_runs(ci.get("runs") or []):
        if kind := _ships(r, d["deploy_workflow"], default, False, d.get("production_branches") or []):
            runs[kind].append({"id": f"run:{r['id']}", "sha": r.get("sha"), "finished": r.get("up"), "name": r.get("wfn")})
    shipped_commits = defaultdict(list)
    for x in repo.get("releases") or []:
        if x.get("at") and not x.get("pre") and not PRE_TAG.search(x.get("tag") or ""):
            shipped_commits[x.get("sha") or x["tag"]].append(x)
    releases = []
    # Several packages released from one commit are one deployment, finished at the last one (as DevLake counts).
    for group in shipped_commits.values():
        main = min(group, key=lambda x: (len(x["tag"]), x["at"]))
        releases.append({"id": f"release:{main['tag']}", "sha": main.get("sha"), "finished": max(x["at"] for x in group),
                         "source": "releases", "name": main["tag"] + (f" +{len(group) - 1}" if len(group) > 1 else "")})
    # Teams that ship on merge (source = "merges"): each PR merged into the default branch is one deployment.
    merges = [{"id": f"merge:{p['n']}", "sha": p.get("mc"), "finished": p["mg"], "source": "merges", "name": f"#{p['n']}"}
              for p in prs or [] if p.get("mg") and (not default or not p.get("base") or p.get("base") == default)]
    return {"deployments api": api, "deploy workflows": runs["deploy"], "releases": releases,
            "release workflows": runs["release"], "merges": merges}


def explain_deployments(repo: dict, ci: dict, cfg: dict) -> dict:
    """The deploy dry run: which source counts and why the others don't, each workflow counted or skipped with the
    reason, each environment counted or hidden, and the settings that decide it."""
    d = cfg["delivery"]
    default = repo.get("default_branch")
    found = _sources(repo, ci, cfg)
    deps, source = find_deployments(repo, ci, cfg)
    order, why = _auto_order(found, ci, default)
    order = {"auto": order, "deployments": ("deployments api",), "releases": ("releases",),
             "workflows": ("deploy workflows", "release workflows"), "merges": ("merges",)}[d["source"]]
    flows = {}
    for r in _final_runs(ci.get("runs") or []):
        if not (r.get("path") or "").startswith(".github/workflows/"):
            continue
        f = flows.setdefault(r["path"], {"name": r.get("wfn"), "path": r["path"], "counted": 0, "skipped": 0})
        f["kind"], f["why"] = deploy_reason(r.get("wfn"), r.get("path"), d["deploy_workflow"])
        # Its runs count only when workflows of its kind are the source chosen; otherwise it is passed over.
        f["used"] = {"deploy": "deploy workflows", "release": "release workflows"}.get(f["kind"]) == source
        if f["kind"]:
            f["counted" if _ships(r, d["deploy_workflow"], default, False, d.get("production_branches") or []) else "skipped"] += 1
    prod = {x.lower() for x in d["production"]}
    envs = Counter(x.get("env") for x in repo.get("deployments") or [] if x.get("env"))
    kind = lambda e: ("production" if is_production(e, prod) else "staging" if ENV_STAGING.search(e)  # noqa: E731
                      else "publishing" if ENV_PUBLISH.search(e) else "other")
    rel = repo.get("releases") or []
    pre = sum(1 for x in rel if x.get("pre") or PRE_TAG.search(x.get("tag") or ""))
    return {"source": source, "deployments": len(deps), "settings": {k: d[k] for k in ("source", "deploy_workflow", "production")},
            "considered": [{"source": k, "found": len(found[k]), "used": k == source} for k in order],
            "order_reason": why if d["source"] == "auto" else f'source = "{d["source"]}" in [delivery]',
            "workflows": sorted(flows.values(), key=lambda f: (f["kind"] is None, f["path"])),
            "environments": [{"name": e, "deployments": n, "as": kind(e), "counted": kind(e) == "production"}
                             for e, n in envs.most_common()],
            "releases": {"published": len(rel) - pre, "prereleases_skipped": pre}}


def deployment_of(p: dict, deps: list[dict]) -> dict | None:
    """The deployment that shipped a merged PR: the one of its merge commit, else the one whose shipped commits hold it,
    else the first one finished after its merge, but only inside the known history: before the oldest known
    deployment, nothing says which one shipped it."""
    if p.get("mc"):
        for d in deps:
            if d.get("sha") == p["mc"]:
                return d
        holding = [d for d in deps if p["mc"] in (d.get("shipped") or ())]
        if holding:
            return min(holding, key=lambda d: d["finished"])
    if not any(d["finished"] < p["mg"] for d in deps):
        return None
    after = [d for d in deps if d["finished"] >= p["mg"]]
    return min(after, key=lambda d: d["finished"]) if after else None


def _ignored_revert(target: int | None, by_number: dict, ignore: list[str]) -> bool:
    """A revert of a PR that touched only ignored paths, or by an ignored author, is not an incident."""
    if target is None or target not in by_number or not ignore:
        return False
    from fnmatch import fnmatch
    undone = by_number[target]
    if (undone.get("au") or "").lower() in {x.lower() for x in ignore}:
        return True
    paths = undone.get("paths") or []
    return bool(paths) and all(any(fnmatch(path, pat) for pat in ignore if "/" in pat or "*" in pat) for path in paths)


def find_incidents(prs: list[dict], issues: list[dict], deps: list[dict], cfg: dict, extra=()) -> list[dict]:
    """Incidents without a paid tracker: issues with an incident label, merged revert PRs and merged hotfix PRs, plus a
    connected tracker's (`extra`, with their own links); each linked to the last production deployment finished before
    it began (DevLake's rule), or to none. A revert also names the deployment that shipped the PR it undoes (its fix
    chain), or says the change never shipped when it was reverted before any deployment ran it."""
    d = cfg["delivery"]
    incident_labels = {x.lower() for x in d["incident_labels"]}
    hotfix_labels = {x.lower() for x in d["hotfix_labels"]}
    # An empty incident_sources list counts every GitHub source; a list counts only those named.
    wanted = set(d.get("incident_sources") or ("issues", "reverts", "hotfixes", "fixes"))
    fix_res = [re.compile(x) for x in d.get("fix_patterns") or []]
    by_number = {p["n"]: p for p in prs if p.get("mg")}
    out = [{"source": "issue", "number": i["n"], "created": i["cr"], "resolved": i.get("cl")}
           for i in issues or [] if "issues" in wanted and any(str(x).lower() in incident_labels for x in i.get("lb") or [])]
    for p in prs:
        if not p.get("mg"):
            continue
        if is_revert(p):
            if "reverts" in wanted and not _ignored_revert(revert_target(p, by_number), by_number, d.get("ignore_reverts_of") or []):
                out.append({"source": "revert", "number": p["n"], "created": p["cr"], "resolved": p["mg"]})
        elif any(str(x).lower() in hotfix_labels for x in p.get("lb") or []):
            if "hotfixes" in wanted:
                out.append({"source": "hotfix", "number": p["n"], "created": p["cr"], "resolved": p["mg"]})
        elif "fixes" in wanted and (m := next((m for r in fix_res for s in (p.get("ti") or "", p.get("head") or "")
                                               if (m := r.search(s))), None)):
            # A fix that names the PR it fixes: that PR's deployment is blamed, as a revert's is.
            fixes = int(m.group(1)) if m.group(1) and m.group(1).isdigit() else None
            out.append({"source": "fix", "number": p["n"], "created": p["cr"], "resolved": p["mg"], "fixes": fixes})
    out += [dict(x) for x in extra]
    for inc in out:
        target = revert_target(by_number[inc["number"]], by_number) if inc["source"] == "revert" else \
            inc.get("fixes") if inc["source"] == "fix" and inc.get("fixes") in by_number else None
        shipped = deployment_of(by_number[target], deps) if target is not None else None
        # Only a deployment that ran the change before the revert merged failed; one shipping both shipped no failure.
        live = bool(shipped) and shipped["finished"] < (inc["resolved"] or "~")
        # No deployment yet after a change merged inside the known history: it never shipped either.
        unshipped = (target is not None and not shipped and inc["resolved"] is not None
                     and any(d["finished"] < by_number[target]["mg"] for d in deps))
        inc["fix_chain_deployment"] = shipped["id"] if live else None
        inc["never_shipped"] = (bool(shipped) and not live) or unshipped
        before = [x for x in deps if x["finished"] <= inc["created"]]
        dep = max(before, key=lambda x: x["finished"]) if before else None
        inc["deployment"] = dep["id"] if dep else None
        inc["deployment_finished"] = dep["finished"] if dep else None
        inc["hours_to_restore"] = _hours(dep["finished"], inc["resolved"]) if dep and inc["resolved"] else None
    return sorted(out, key=lambda x: x["created"])


PAGERS = {"pagerduty": "PagerDuty", "incident_io": "incident.io", "recorded": "recorded incidents"}
TRACKER_NAMES = {"jira": "Jira", "linear": "Linear"}
BUILT_IN_INCIDENTS = "GitHub issues, reverts and hotfixes"


def incidents_for(prs: list[dict], issues: list[dict], deps: list[dict], cfg: dict, tracker: dict | None,
                  recorded: dict | None = None) -> tuple[list[dict], str]:
    """The incidents DORA counts and where they came from: a connected pager tool's (or ones recorded from another tool)
    alone when there are any (labels, reverts and hotfixes would count the same outage twice), else GitHub's plus a
    tracker's incident issues."""
    from stackvitals.core import recorded as recorded_mod
    extra = tracked.incidents(tracker["issues"]) if tracker else []
    pager = [i for i in extra if i["source"] in PAGERS] + recorded_mod.incidents(recorded)
    chosen = set(cfg["delivery"].get("incident_sources") or ())
    if chosen:
        # The settings name the sources: exactly those, combined (GitHub's are filtered inside find_incidents).
        picked = [i for i in pager if ("recorded" if i["source"] == "recorded" else "pager") in chosen]
        picked += [i for i in extra if i["source"] not in PAGERS and "tracker" in chosen]
        github = chosen & {"issues", "reverts", "hotfixes", "fixes"}
        said = sorted(github) + sorted({PAGERS.get(i["source"]) or TRACKER_NAMES.get(i["source"], i["source"]) for i in picked})
        return (find_incidents(prs if github else [], issues if github else [], deps, cfg, extra=picked),
                ", ".join(said) or "none chosen")
    if pager:
        return find_incidents([], [], deps, cfg, extra=pager), " and ".join(sorted({PAGERS[i["source"]] for i in pager}))
    names = sorted({TRACKER_NAMES.get(i["source"], i["source"]) for i in extra})
    return find_incidents(prs, issues, deps, cfg, extra=extra), BUILT_IN_INCIDENTS + (f", and {' and '.join(names)}" if names else "")


def _ranks(v: list) -> list[float]:
    # SQL's percent_rank over sorted values: ties share the lowest rank, and a single row ranks 0.
    return [bisect_left(v, x) / (len(v) - 1) if len(v) > 1 else 0.0 for x in v]


def devlake_median(values: list[float]) -> float | None:
    """DevLake's median: the largest value whose percent rank is at most 0.5 (the lower middle value)."""
    v = sorted(x for x in values if x is not None)
    return max((x for x, r in zip(v, _ranks(v)) if r <= 0.5), default=None)


def devlake_upper_median(values: list[float]) -> float | None:
    """The smallest value whose percent rank is at least 0.5, DevLake's rule for six-month windows (None for one row)."""
    v = sorted(x for x in values if x is not None)
    return min((x for x, r in zip(v, _ranks(v)) if r >= 0.5), default=None)


def _span(rng, cuts, inclusive=False) -> list[str] | None:
    # The tiers a range reaches across, when its two ends fall in different ones; None when settled or unknown.
    if not rng:
        return None
    ends = [_tier(rng[0], cuts, inclusive), _tier(rng[1], cuts, inclusive)]
    return ends if ends[0] != ends[1] else None


def _tier(value, cuts, inclusive=False) -> str | None:
    if value is None:
        return None
    for limit, name in zip(cuts, ("elite", "high", "medium")):
        if (value <= limit) if inclusive else (value < limit):
            return name
    return "low"


def _per_six_months(months: dict) -> float | None:
    """DevLake's six-month count: rolling six-month sums, every sixth month from the newest, upper median. It is None
    under seven months of data, and DevLake then shows N/A for a low or (2021) medium frequency."""
    ms = sorted(months)
    rolling = [sum(months[m] for m in ms[max(0, i - 5):i + 1]) for i in range(len(ms))]
    rn, count = {}, defaultdict(int)
    for i in sorted(range(len(ms)), key=lambda i: ms[i], reverse=True):
        count[ms[i].year // 6] += 1  # MySQL reads DATE_FORMAT(month, '%Y-%m') DIV 6 as the year DIV 6
        rn[i] = count[ms[i].year // 6]
    return devlake_upper_median([rolling[i] for i in range(len(ms)) if rn[i] % 6 == 1])


def dora(deps: list[dict], deployed: list[dict], incidents: list[dict], start: datetime, end: datetime, report: str = "2023") -> dict:
    """DORA's first four metrics exactly as DevLake's DORA dashboard SQL counts them: deployment days per week and month over the
    calendar days after the start up to the end's day (weeks with none count as zero), the median DevLake PR cycle time
    in whole minutes of PRs deployed in the range, deployments with an incident over deployments, and the median whole
    minutes from a failed deployment to its incident's resolution (2021: incident opened to resolved)."""
    s, e = iso(start), iso(end)
    in_win = [x for x in deps if s <= x["finished"] <= e]
    ids = {x["id"] for x in in_win}
    finished = {x["id"]: x["finished"] for x in deps}
    dep_days = {x["finished"][:10] for x in deps}
    calendar, k = [], 0
    while end - timedelta(days=k) > start:
        calendar.append((end - timedelta(days=k)).date())
        k += 1
    weeks, months = defaultdict(int), defaultdict(int)
    for day in calendar:
        weeks[day - timedelta(days=day.weekday())] += day.isoformat() in dep_days
        months[day.replace(day=1)] += day.isoformat() in dep_days
    per_week, per_month = devlake_median(list(weeks.values())), devlake_median(list(months.values()))
    per_six = _per_six_months(months)
    if not deps or per_week is None:
        freq = None
    elif report == "2021":
        freq = "elite" if per_week >= 5 else "high" if per_month >= 1 else None if per_six is None else \
            "medium" if per_six >= 1 else "low"
    else:
        freq = "elite" if per_week >= 5 else "high" if per_week >= 1 else "medium" if per_month >= 1 else \
            "low" if per_six is not None else None
    lead_minutes = [x["cycle_min"] for x in deployed if x["deployment"] in ids and x["cycle_min"] is not None]
    lead = devlake_median(lead_minutes)
    lead_cuts = (60, 7 * 24 * 60, 180 * 24 * 60) if report == "2021" else (24 * 60, 7 * 24 * 60, 30 * 24 * 60)
    failed = {i["deployment"] for i in incidents if i.get("deployment") in ids}
    # DevLake shows N/A instead of a rate when no incident was found at all.
    cfr = round(len(failed) / len(in_win), 4) if in_win and incidents else None
    cfr_cuts = (0.15, 0.20, 0.30) if report == "2021" else (0.05, 0.10, 0.15)
    # The same rate with each revert tied to the deployment that shipped what it undoes (time order for the rest).
    chained = {i.get("fix_chain_deployment") or i.get("deployment") for i in incidents if not i.get("never_shipped")} & ids
    cfr_chain = round(len(chained) / len(in_win), 4) if in_win and incidents else None
    reverts = [i for i in incidents if i.get("source") == "revert" and s <= i["created"] <= e]
    linkage = {"reverts": len(reverts), "fix_chain_found": sum(1 for i in reverts if i.get("fix_chain_deployment")),
               "disagree": sum(1 for i in reverts if i.get("fix_chain_deployment")
                               and i["fix_chain_deployment"] != i.get("deployment")),
               "never_shipped": sum(1 for i in reverts if i.get("never_shipped"))}
    resolved = [i for i in incidents if i.get("resolved") and s <= i["resolved"] <= e]
    restore = [m for i in resolved if i.get("deployment") in ids
               if (m := _minutes_down(finished[i["deployment"]], i["resolved"])) is not None]
    recovery = devlake_median(restore)
    mttr = devlake_median([m for i in resolved if (m := _minutes_down(i["created"], i["resolved"])) is not None])
    rec_value = mttr if report == "2021" else recovery
    by_month = Counter(x["finished"][2:7].replace("-", "/") for x in in_win)
    month, monthly = start.date().replace(day=1), []
    while month <= end.date().replace(day=1):
        label = month.strftime("%y/%m")
        monthly.append({"month": label, "deployments": by_month.get(label, 0)})
        month = (month + timedelta(days=32)).replace(day=1)

    def hours(minutes):
        return None if minutes is None else round(minutes / 60, 2)

    # What each number was computed from, so the app can open a number into its pull requests and deployments.
    short = {x["id"]: (x.get("sha") or "")[:12] for x in deps}
    lead_rows = sorted(([x.get("pr"), short.get(x["deployment"]), x["cycle_min"]] for x in deployed
                        if x["deployment"] in ids and x["cycle_min"] is not None), key=lambda r: -r[2])
    failed_rows = sorted([short.get(i["deployment"]), i.get("source"), i.get("number")] for i in incidents
                         if i.get("deployment") in ids)
    restore_rows = [[short.get(i["deployment"]), i.get("source"), i.get("number"), m] for i in resolved if i.get("deployment") in ids
                    if (m := _minutes_down(finished[i["deployment"]], i["resolved"])) is not None]
    evidence = {"deployments": [[short[x["id"]], x["finished"]] for x in sorted(in_win, key=lambda x: x["finished"])][:EVIDENCE_MAX],
                "lead_time": lead_rows[:EVIDENCE_MAX], "lead_time_total": len(lead_rows),
                "failed": failed_rows[:EVIDENCE_MAX], "recovery": restore_rows[:EVIDENCE_MAX]}

    # Each number's likely range, so a tier is claimed only as far as the sample supports it.
    lead_rng, restore_rng = quantile_range(lead_minutes, 0.5), quantile_range(restore, 0.5)
    cfr_rng = [round(x, 4) for x in wilson(len(failed), len(in_win))] if cfr is not None else None
    rec_cuts = (60, 24 * 60, 7 * 24 * 60)
    return {"report": report, "deployments": len(in_win), "deployment_days": sum(weeks.values()),
            "deployment_days_per_week": per_week, "deployment_days_per_month": per_month,
            "deployment_days_per_six_months": per_six, "frequency_tier": freq, "monthly": monthly,
            "lead_time_minutes": lead, "lead_time_hours": hours(lead), "lead_time_n": len(lead_minutes),
            "lead_time_tier": _tier(lead, lead_cuts),
            "lead_time_range_hours": [hours(x) for x in lead_rng] if lead_rng else None,
            "lead_time_tier_span": _span(lead_rng, lead_cuts),
            "change_failure_rate": cfr, "failed_deployments": len(failed),
            "cfr_tier": _tier(cfr, cfr_cuts, inclusive=True), "cfr_range": cfr_rng,
            "cfr_tier_span": _span(cfr_rng, cfr_cuts, inclusive=True), "cfr_fix_chain": cfr_chain, "linkage": linkage,
            "recovery_minutes": recovery, "recovery_hours": hours(recovery), "recovery_n": len(restore),
            "mttr_minutes": mttr, "mttr_hours": hours(mttr),
            "recovery_range_hours": [hours(x) for x in restore_rng] if restore_rng and report != "2021" else None,
            "recovery_tier": _tier(rec_value, rec_cuts),
            "recovery_tier_span": _span(restore_rng, rec_cuts) if report != "2021" else None, "evidence": evidence}


def devlake_pr_cycle(rows: list[tuple], start: datetime, end: datetime) -> list[dict]:
    """DevLake's "PR Cycle Time [Merged PRs]" panel: mean cycle hours by month merged, for PRs merged in the range and
    opened from the first day of the month after the range starts."""
    s, e = iso(start), iso(end)
    first = (start.date().replace(day=1) + timedelta(days=32)).replace(day=1).isoformat()
    months = defaultdict(list)
    for p, ph, _dep in rows:
        if s <= p["mg"] <= e and p["cr"] >= first:
            months[p["mg"][:7]].append((ph["devlake_cycle_min"] or 0) / 60)
    return [{"month": f"{m}-01", "avg_hours": sum(v) / len(v), "n": len(v)} for m, v in sorted(months.items())]


def _band(name: str, p75: float | None) -> str | None:
    cuts = LINEARB_BANDS.get(name)
    if not cuts or p75 is None:
        return None
    return "elite" if p75 < cuts[0] else "good" if p75 <= cuts[1] else "fair" if p75 <= cuts[2] else "needs improvement"


def _summary(name: str, values: list[float], prs: list | None = None) -> dict:
    # With the PR numbers, the phase also names its pull requests, longest first, so a P75 can be opened up.
    proof = {"evidence": sorted(([n, round(v, 2)] for n, v in zip(prs, values)), key=lambda r: -r[1])[:PHASE_EVIDENCE_MAX]} if prs else {}
    if len(values) < MIN_PRS:
        return {"n": len(values), "enough": False, "p50_h": None, "p75_h": None, "low_h": None, "high_h": None, "linearb_band": None, **proof}
    rng = quantile_range(values, 0.5)
    p50, p75 = median(values), percentile(values, 0.75)
    return {"n": len(values), "enough": True, "p50_h": round(p50, 2), "p75_h": round(p75, 2),
            "low_h": round(rng[0], 2) if rng else None, "high_h": round(rng[1], 2) if rng else None,
            "linearb_band": _band(name, p75), **proof}


def _stuck(open_prs: list[dict], now: datetime) -> dict:
    """LinearB's saved filters for open PRs with published cut-offs, plus one of ours: red checks nobody acted on."""
    from stackvitals.flow.analyze import ready_at, who_acts_next
    out = {"hanging_review": [], "long_lived": [], "high_interaction": [], "red_and_idle": []}
    end = iso(now)
    for p in open_prs:
        if p.get("draft") or kind_of(p.get("au"), p.get("at")) != "person":
            continue
        au, ready = p.get("au"), ready_at(p) or p["cr"]
        reviews = [e for e in p.get("ev") or [] if e[0] == "review" and len(e) > 5 and _person(e[2], e[5], au)]
        asked = [e[1] for e in p.get("ev") or [] if e[0] == "req" and len(e) > 2 and e[2] in (p.get("rq") or [])]
        if asked:
            last = max(asked)
            waited = _hours(last, end) or 0
            if waited > HANGING_HOURS and not any(e[1] >= last for e in reviews):
                out["hanging_review"].append({"pr": p["n"], "since": last, "hours": round(waited, 1)})
        open_h = _hours(ready, end) or 0
        if open_h > LONG_LIVED_HOURS:
            out["long_lived"].append({"pr": p["n"], "since": ready, "hours": round(open_h, 1)})
        if (p.get("cmn") or 0) >= BUSY_COMMENTS or len(reviews) >= BUSY_COMMENTS:
            out["high_interaction"].append({"pr": p["n"], "comments": p.get("cmn") or 0, "reviews": len(reviews)})
        w = who_acts_next(p, now)
        if w.get("actor") == "author" and w.get("step") == "checks" and (_hours(w.get("since"), end) or 0) > 24:
            out["red_and_idle"].append({"pr": p["n"], "since": w["since"], "why": w["why"]})
    for key in out:
        out[key].sort(key=lambda x: x["pr"])
    return out


def apply_identity(flow: dict, ident: dict | None) -> dict:
    """The PRs with old logins renamed to current ones and account types set by the repo's identity settings."""
    ident = ident or {}
    aliases = {k.lower(): v for k, v in (ident.get("aliases") or {}).items()}
    bots, people = ({x.lower() for x in ident.get(k) or []} for k in ("bots", "people"))
    if not (aliases or bots or people):
        return flow

    def who(login):
        return aliases.get((login or "").lower(), login)

    def typ(original, login, given):
        names = {(original or "").lower(), (login or "").lower()}
        return "Bot" if names & bots else "Person" if names & people else given

    def fix(p):
        q = {**p, "au": who(p.get("au")), "rq": [who(x) for x in p.get("rq") or []]}
        q["at"] = typ(p.get("au"), q["au"], p.get("at"))
        q["ev"] = [[*e[:2], who(e[2]), e[3], e[4], typ(e[2], who(e[2]), e[5]), *e[6:]] if e[0] == "review" and len(e) > 5
                   else [*e[:2], who(e[2]), *e[3:]] if len(e) > 2 else list(e) for e in p.get("ev") or []]
        q["cm"] = [[c[0], who(c[1]), c[2], typ(c[1], who(c[1]), c[3]), *c[4:]] if len(c) > 3 else list(c)
                   for c in p.get("cm") or []]
        return q
    return {**flow, **{k: [fix(p) for p in flow.get(k) or []] for k in ("closed", "open")}}


def _group(rows: list[tuple]) -> dict:
    return {"n": len(rows), **{name: _summary(name, [r[1][name] for r in rows if r[1][name] is not None])
                               for name in ("cycle_to_merge", "pickup", "review")}}


def by_team(rows: list[tuple], ident: dict | None, shipped_rows: list[tuple] | None = None, incidents: list[dict] | None = None,
            start: datetime | None = None, end: datetime | None = None, report: str = "2023") -> dict:
    """Cycle time for each team in the identity settings, by its members' merged PRs; with the shipped rows, DORA too,
    from the deployments that shipped the team's PRs (DevLake's DORA by team)."""
    teams = (ident or {}).get("teams") or {}
    aliases = {k.lower(): v for k, v in ((ident or {}).get("aliases") or {}).items()}
    members = {team: {aliases.get(x.lower(), x).lower() for x in logins} for team, logins in teams.items()}
    out = {}
    for team, logins in members.items():
        entry = _group([r for r in rows if (r[0].get("au") or "").lower() in logins])
        if shipped_rows is not None and start and end:
            mine = [r for r in shipped_rows if (r[0].get("au") or "").lower() in logins and r[2]]
            own = list({r[2]["id"]: r[2] for r in mine}.values())
            ids = {d["id"] for d in own}
            if own:
                deployed = [{"deployment": dep["id"], "cycle_min": ph["devlake_cycle_min"], "pr": p.get("n")} for p, ph, dep in mine]
                entry["dora"] = {k: v for k, v in dora(own, deployed, [i for i in incidents or [] if i.get("deployment") in ids],
                                                       start, end, report).items() if k != "evidence"}
        out[team] = entry
    return out


def by_service(rows: list[tuple], deps: list[dict], incidents: list[dict], cfg: dict, start: datetime, end: datetime,
               report: str = "2023", kept: list[tuple] | None = None) -> dict:
    """Each [services] entry: its merged PRs (any changed path matching its patterns; one touching two services counts in
    both) and their review phases, plus DORA from its own deployments when a deploy pattern tells them apart."""
    from stackvitals.codeowners import matches
    out = {}
    for name, svc in (cfg.get("services") or {}).items():
        def ours(rs):
            return [r for r in rs if any(matches(pat, path) for path in r[0].get("paths") or [] for pat in svc["paths"])]
        mine = ours(rows)
        # Review phases from the same PRs as the repo's (outliers left out); DORA from every merged one, as the repo's.
        phased = ours(kept) if kept is not None else mine
        entry = {"prs": len(phased), **_group(phased)}
        if svc.get("deploy"):
            pattern = re.compile(svc["deploy"])
            own = [d for d in deps if pattern.search(d.get("name") or "")]
            ids = {d["id"] for d in own}
            shipped_by = [(p, ph, deployment_of(p, own)) for p, ph, _dep in mine] if own else []
            deployed = [{"deployment": dep["id"], "cycle_min": ph["devlake_cycle_min"], "pr": p.get("n")}
                        for p, ph, dep in shipped_by if dep]
            s, e = iso(start), iso(end)
            entry["deployments"] = sum(1 for d in own if s <= d["finished"] <= e)
            entry["dora"] = {k: v for k, v in dora(own, deployed, [i for i in incidents if i.get("deployment") in ids],
                                                   start, end, report).items() if k != "evidence"}
        out[name] = entry
    return out


def by_owner(rows: list[tuple], codeowners: str | None) -> dict:
    """Cycle time for each owning team in CODEOWNERS, by the merged PRs touching its paths; single people are left out."""
    if not codeowners:
        return {}
    from stackvitals.flow.knowledge import codeowners_for
    groups = defaultdict(list)
    for r in rows:
        owners = {o for path in r[0].get("paths") or [] for o in codeowners_for(path, codeowners) if "/" in o}
        for owner in owners:
            groups[f"@{owner}"].append(r)
    return {owner: _group(rs) for owner, rs in sorted(groups.items())}


def _on_production(p: dict, prod_branches: list[str], in_ranges: set) -> bool:
    from fnmatch import fnmatch
    return any(fnmatch(p.get("base") or "", pat) for pat in prod_branches) or (p.get("mc") in in_ranges)


def shipped(flow: dict, repo: dict, ci: dict, cfg: dict, kinds=("person",)) -> tuple[list[dict], str | None, list[tuple]]:
    """Deployments, where they came from, and (PR, phases, deployment) for each PR by `kinds` merged into the default branch,
    a production branch, or any branch whose merge commit a deployment shipped (develop merged into main later)."""
    deps, source = find_deployments(repo, ci or {}, cfg, flow.get("closed") or [])
    default = repo.get("default_branch")
    prod_branches = cfg["delivery"].get("production_branches") or []
    in_ranges = {sha for d in deps for sha in d.get("shipped") or ()}
    rows = []
    for p in flow.get("closed") or []:
        if not p.get("mg"):
            continue
        if default and p.get("base") and p.get("base") != default and not _on_production(p, prod_branches, in_ranges):
            continue
        if kind_of(p.get("au"), p.get("at")) not in kinds:
            continue
        dep = deployment_of(p, deps) if deps else None
        rows.append((p, phases(p, dep["finished"] if dep else None, cfg.get("calendar")), dep))
    return deps, source, rows


def _logins(kept: list, ident: dict | None) -> set[str]:
    """The people an assignee could be: authors of the merged PRs and everyone named in the identity settings."""
    return ({r[0].get("au") for r in kept if r[0].get("au")} | {x for xs in ((ident or {}).get("teams") or {}).values() for x in xs}
            | set((ident or {}).get("people") or []))


def _tracker(tracker: dict | None, kept: list, now: datetime, window_days: int, ident: dict | None = None) -> dict | None:
    """Issues from the connected trackers: merged PRs linked to them, lead and cycle time by type, and the last sprints."""
    # Jira or Linear only: a pager tool's incidents count in DORA, not as issues and sprints.
    if not tracker or not set(tracker["sources"]) & set(TRACKER_NAMES):
        return None
    issues = [i for i in tracker["issues"] if i.get("src") not in PAGERS]
    moves = tracker["changes"]
    since = iso(now - timedelta(days=window_days))
    linked = {n for n, _key in tracked.pr_links([r[0] for r in kept], issues)}
    return {"sources": tracker["sources"], "issues": len(issues), "linked_prs": len(linked), "merged_prs": len(kept),
            "lead_time": tracked.lead_times(issues, moves, now - timedelta(days=window_days), now),
            "planning": tracked.planning(issues, moves, tracker["sprints"], now, since=now - timedelta(days=BACKFILL_DAYS)),
            "incidents": sum(1 for i in issues if i.get("incident") and (i.get("created") or "") >= since),
            # Issues done per team, through [identity] aliases of each assignee; private repos only keep assignees.
            "by_team": identity.issues_by_team(issues, ident, since, _logins(kept, ident)) if any(i.get("assignee") for i in issues) else None,
            # Done issues by the tracker's own team field ([connectors.jira] team_field), when one is mapped.
            "by_field_team": dict(Counter(i["team"] for i in issues if i.get("team") and i.get("cat") == "DONE"
                                          and (i.get("resolved") or "") >= since).most_common(20)) or None}


def _changes(rows: list, deps: list[dict], incidents: list[dict], now: datetime) -> list[dict]:
    """This week's review phases, deployments and change failure rate against the four weeks before, plus the review
    phases over the last 14 days (a slowdown that lasts), each judged against how much this repo's weeks usually swing."""
    return changes.calibrate(lambda t: _week_checks(rows, deps, incidents, t), now)


def _week_checks(rows: list, deps: list[dict], incidents: list[dict], now: datetime) -> list[dict]:
    (ws, we), (bs, be) = changes.windows(now)
    kept = [r for r in rows if r[0].get("mg") and (r[1]["cycle_to_merge"] or 0) <= OUTLIER_HOURS]
    phase = lambda name, a, b: [r[1][name] for r in kept if a <= r[0]["mg"] < b]  # noqa: E731
    names = (("pickup", "pickup"), ("cycle_to_merge", "opened to merged"))
    out = [changes.times(f"delivery.{name}", label, phase(name, ws, we), phase(name, bs, be), better=-1, unit="h")
           # Review alone is left out: it is near zero for most PRs (approval, then merge) and inside opened to merged.
           for name, label in names]
    shipped = lambda a, b: [d["id"] for d in deps if a <= d["finished"] < b]  # noqa: E731
    now_ids, base_ids = shipped(ws, we), shipped(bs, be)
    failed = {i.get("deployment") for i in incidents}
    out.append(changes.count("delivery.deployments", "deployments", len(now_ids), len(base_ids), better=1))
    out.append(changes.share("delivery.change_failure", "deployments that failed", sum(d in failed for d in now_ids),
                             len(now_ids), sum(d in failed for d in base_ids), len(base_ids), better=-1))
    # A slowdown that lasts: the last 14 days against the four weeks before them (2x the catches in its second week).
    (ts, te), (tbs, tbe) = changes.windows(now, 2)
    out += [changes.times(f"delivery.{name}_14d", f"{label} over the last 14 days", phase(name, ts, te),
                          phase(name, tbs, tbe), better=-1, unit="h", span=2) for name, label in names]
    return out


def dora_rows(deps: list[dict], deployed: list[dict], incidents: list[dict], now: datetime, days: int = 365,
              most: int = 2500) -> dict:
    """Compact rows for DORA over any date range, computed in the app: each deployment [finished, failed, recovery
    hours] and each shipped PR [its deployment's finish, lead time in hours], for the last `days`."""
    since = iso(now - timedelta(days=days))
    failed = defaultdict(list)
    for i in incidents:
        if i.get("deployment"):
            failed[i["deployment"]].append(i.get("hours_to_restore"))
    finished = {d["id"]: d["finished"] for d in deps}
    rows = [[d["finished"], d["id"] in failed, min((h for h in failed[d["id"]] if h is not None), default=None)]
            for d in deps if d["finished"] >= since]
    prs = [[finished[x["deployment"]], round(x["cycle_min"] / 60, 2)] for x in deployed
           if x.get("cycle_min") is not None and finished.get(x["deployment"], "") >= since]
    return {"deployments": sorted(rows)[-most:], "prs": sorted(prs)[-most:]}


def dora_weeks(deps: list[dict], deployed: list[dict], incidents: list[dict], now: datetime, weeks: int = 13,
               report: str = "2023") -> list[dict]:
    """All four DORA numbers week by week (Monday to Monday), oldest first, counted as the window's are."""
    monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    out = []
    for k in range(weeks - 1, -1, -1):
        start, end = monday - timedelta(weeks=k), min(monday - timedelta(weeks=k - 1), now)
        got = dora(deps, deployed, incidents, start, end, report)
        out.append({"week": start.date().isoformat(), "deployments": got["deployments"], "lead_time_hours": got["lead_time_hours"],
                    "change_failure_rate": got["change_failure_rate"], "recovery_hours": got["recovery_hours"]})
    return out


def deployment_list(merged: list[tuple], deps: list[dict], incidents: list[dict], since: str, most: int = 30) -> list[dict]:
    """The window's deployments, newest first, each with what it shipped (people's and agents' PRs, their authors, the
    median lead time) and the incidents blamed on it (Middleware's deployment drill-down)."""
    shipped_by = defaultdict(list)
    for p, ph, dep in merged:
        if dep:
            shipped_by[dep["id"]].append((p, ph))
    blamed = defaultdict(list)
    for i in incidents:
        if i.get("deployment"):
            blamed[i["deployment"]].append(i.get("number"))
    out = []
    for d in sorted((d for d in deps if d["finished"] >= since), key=lambda d: d["finished"], reverse=True)[:most]:
        prs = shipped_by.get(d["id"], [])
        leads = sorted(ph["devlake_cycle_min"] for _p, ph in prs if ph.get("devlake_cycle_min") is not None)
        out.append({"id": d["id"], "name": d.get("name"), "sha": d.get("sha"), "finished": d["finished"],
                    "prs": sorted(p["n"] for p, _ph in prs), "authors": len({p.get("au") for p, _ph in prs if p.get("au")}),
                    "lead_hours": round(leads[len(leads) // 2] / 60, 2) if leads else None, "incidents": blamed.get(d["id"], [])})
    return out


def build(flow: dict, repo: dict, ci: dict, issues: list[dict], now: datetime, window_days: int, cfg: dict,
          tracker: dict | None = None) -> dict:
    """Everything the Delivery page shows, for the last `window_days`; `tracker` is what the connectors pulled (Jira,
    Linear), or None."""
    since = iso(now - timedelta(days=window_days))
    ident = cfg.get("identity")
    flow = apply_identity(flow, ident)
    deps, source, merged = shipped(flow, repo, ci, cfg, ("person", "agent"))
    # Cycle time and DORA are about people's PRs; coding agents' PRs join only the AI-assisted outcomes and rework.
    rows = [r for r in merged if kind_of(r[0].get("au"), r[0].get("at")) == "person"]
    closed = flow.get("closed") or []
    deployed = [{"deployment": dep["id"], "cycle_min": ph["devlake_cycle_min"], "pr": p.get("n")} for p, ph, dep in rows if dep]
    window = [r for r in rows if r[0]["mg"] >= since]
    over60 = [r for r in window if (r[1]["cycle_to_merge"] or 0) > OUTLIER_HOURS]
    kept = [r for r in window if r not in over60]
    over98 = []
    if len(kept) >= OUTLIER_MIN_PRS:
        cut = percentile([r[1]["cycle_to_merge"] for r in kept if r[1]["cycle_to_merge"] is not None], 0.98)
        over98 = [r for r in kept if (r[1]["cycle_to_merge"] or 0) > cut]
        kept = [r for r in kept if r not in over98]
    out_phases = {name: _summary(name, [r[1][name] for r in kept if r[1][name] is not None],
                                 [r[0].get("n") for r in kept if r[1][name] is not None]) for name in PHASES}
    incidents, incident_source = incidents_for(closed + (flow.get("open") or []), issues, deps, cfg, tracker, repo.get("recorded"))
    report = cfg["delivery"]["dora_report"]
    sizes = [(r[0].get("add") or 0) + (r[0].get("del") or 0) for r in kept]
    authors = {r[0].get("au") for r in kept}
    weeks = max(window_days / 7, 1)
    talk = [sum(1 for c in r[0].get("cm") or [] if len(c) > 3 and _person(c[1], c[3], r[0].get("au")))
            + sum(1 for e in r[0].get("ev") or [] if e[0] == "review" and len(e) > 5 and _person(e[2], e[5], r[0].get("au")))
            for r in kept]
    unreviewed = [r[0]["n"] for r in kept if not r[1]["reviewed"]]
    lightning = [r for r in kept if r[1]["reviewed"] and r[1]["review"] is not None and r[1]["review"] < LIGHTNING_HOURS]
    agents = [p for p in closed if kind_of(p.get("au"), p.get("at")) == "agent" and (p.get("cl") or "") >= since]
    assisted = [r for r in kept if assisted_by(r[0])]
    others = [r for r in kept if not assisted_by(r[0])]

    def p75(values):
        v = percentile([x for x in values if x is not None], 0.75)
        return None if v is None else round(v, 2)

    def ai_reviewed(p):
        return any(e[0] == "review" and len(e) > 2 and (e[2] or "").lower().removesuffix("[bot]") in AI_REVIEWERS
                   for e in p.get("ev") or [])
    from stackvitals.core import agreements
    agreed = agreements.check(rows, flow.get("open") or [], cfg.get("agreements") or {}, now)
    keys = dora(deps, deployed, incidents, now - timedelta(days=window_days), now, report)
    from stackvitals.core.calendar import is_set
    if is_set(cfg.get("calendar")):
        # Beside DevLake's calendar-time lead time: the same deployed PRs in working time (weekends and holidays out).
        work = [r[1]["cycle"] for r in rows if r[2] and r[1].get("cycle") is not None
                and iso(now - timedelta(days=window_days)) <= r[2]["finished"] <= iso(now)]
        keys["lead_time_working_hours"] = round(median(work), 2) if work else None
    # DORA's fifth metric (instability): deployments that shipped an unplanned fix, over all deployments in the window. The fixes are
    # GitHub's (reverts, hotfixes, PRs naming an incident issue) even when a pager tool's incidents count for failures.
    fixes = find_incidents(closed + (flow.get("open") or []), issues, deps, cfg)
    keys.update(rework_rate(deps, merged, fixes, now - timedelta(days=window_days), now))
    half_year = [r for r in merged if (r[0].get("mg") or "") >= iso(now - timedelta(days=183))]
    return {"generated": iso(now), "window_days": window_days, "since": since, "prs": len(kept), "agreements": agreed,
            "deploy_source": source, "deploy_confidence": CONFIDENCE.get(source), "incident_source": incident_source,
            # Every deploy attempt, failed and cancelled ones too: success rate and how long deploys take.
            "deploy_attempts": deploy_attempts(repo, ci or {}, cfg, source, now - timedelta(days=window_days), now),
            # Which deployments count and why the rest don't, so a team can check the number before trusting it.
            "deploy_check": explain_deployments(repo, ci or {}, cfg),
            "deployments_unreadable": bool(repo.get("no_deployments")),
            "deploy_names": [{"name": n, "n": k} for n, k in Counter(
                x.get("name") for x in deps if x["finished"] >= since).most_common(5)] if source != "releases" else [],
            "deployments": [{k: x[k] for k in ("id", "sha", "finished", "name")} for x in deps[-20:]],
            "phases": out_phases, "outliers": {"over_60_days": len(over60), "over_p98": len(over98)},
            "dora": keys, "changes": changes.annotate(_changes(rows, deps, incidents, now)),
            "devlake_pr_cycle": devlake_pr_cycle(rows, now - timedelta(days=window_days), now),
            "incidents": [i for i in incidents if i["created"] >= since][-20:],
            # The four DORA numbers week by week, to see a trend rather than one window.
            "dora_weeks": dora_weeks(deps, deployed, incidents, now, report=report),
            # The rows the app computes DORA from for any date range in the last year.
            "dora_rows": dora_rows(deps, deployed, incidents, now),
            # Each recent deployment with what it shipped and the incidents blamed on it.
            "deployment_list": deployment_list(merged, deps, incidents, since),
            # For each recent incident: the deployments and pull requests before it began, likeliest cause first.
            "what_changed": what_changed.recent(incidents, rows, deps, now),
            "sizes": {"n": len(sizes), "p50": median(sizes), "p75": percentile(sizes, 0.75),
                      "under_100": sum(1 for x in sizes if x < SIZE_EDGES[0]),
                      "100_155": sum(1 for x in sizes if SIZE_EDGES[0] <= x <= SIZE_EDGES[1]),
                      "156_228": sum(1 for x in sizes if SIZE_EDGES[1] < x <= SIZE_EDGES[2]),
                      "over_228": sum(1 for x in sizes if x > SIZE_EDGES[2])},
            "merge_frequency": round(len(kept) / max(len(authors), 1) / weeks, 2) if kept else None,
            "review_depth": round(sum(talk) / len(talk), 2) if talk else None,
            "merged_without_review": {"n": len(unreviewed), "share": round(len(unreviewed) / len(kept), 4) if kept else None},
            "merged_flags": {"lightning": [{"pr": r[0]["n"], "review_minutes": round(r[1]["review"] * 60)} for r in lightning],
                             "without_review": [{"pr": n} for n in unreviewed[:20]]},
            "stuck": _stuck(flow.get("open") or [], now),
            # Which open PRs look risky by this repo's own history, shown only where its backtest says it works.
            "change_risk": change_risk.assess(closed, change_risk.troubled(rows, incidents) | change_risk.follow_up_fixes(closed),
                                              [p for p in flow.get("open") or [] if not p.get("draft")]),
            "by_team": by_team(kept, ident, rows, incidents, now - timedelta(days=window_days), now, report), "by_owner": by_owner(kept, repo.get("codeowners")),
            "by_service": by_service(rows, deps, incidents, cfg, now - timedelta(days=window_days), now, report, kept) or None,
            "tracker": _tracker(tracker, kept, now, window_days, ident),
            # What each recent release shipped and what followed it (reverts of its PRs, incidents in two weeks).
            "releases": releases.quality(closed, repo.get("releases") or [], incidents, now),
            # Bugs opened and closed each week, and how old the open ones are (GitHub bug labels, Jira and Linear bugs).
            "bugs": bugs.backlog(issues, [i for i in (tracker or {}).get("issues") or [] if i.get("src") not in PAGERS], now),
            # Where the work goes, from labels, linked issue types, titles and paths (people's and agents' PRs).
            "investment": investment.mix(closed, now, (cfg.get("investment") or {}).get("labels"),
                                         investment.tracker_types(closed, tracker["issues"]) if tracker else None,
                                         base=repo.get("default_branch")),
            # With Jira or Linear connected: the same work by epic or project, and the feature share teams capitalise.
            "epics": investment.by_epic(closed, tracker["issues"], now, base=repo.get("default_branch")) if tracker else None,
            "ai": {"agent_prs": {"n": len(agents), "merged": sum(1 for p in agents if p.get("mg")),
                                 "merged_share": round(sum(1 for p in agents if p.get("mg")) / len(agents), 4) if agents else None},
                   "assisted_prs": {"n": len(assisted), "share": round(len(assisted) / len(kept), 4) if kept else None,
                                    "tools": dict(Counter(t for r in assisted for t in assisted_by(r[0]))),
                                    "pickup_p75_h": p75(r[1]["pickup"] for r in assisted),
                                    "others_pickup_p75_h": p75(r[1]["pickup"] for r in others),
                                    "size_p75": p75((r[0].get("add") or 0) + (r[0].get("del") or 0) for r in assisted),
                                    "others_size_p75": p75((r[0].get("add") or 0) + (r[0].get("del") or 0) for r in others)},
                   "ai_reviewed_prs": {"n": sum(1 for r in kept if ai_reviewed(r[0]))},
                   # The last six months: what happened after AI-assisted and other PRs merged.
                   "outcomes": outcomes(half_year, ci, incidents, now, decided=[
                       p for p in closed if kind_of(p.get("au"), p.get("at")) in ("person", "agent")]),
                   # Each coding agent on its own, the review load agents add, and what an open PR can expect.
                   "by_agent": agent_ledger.by_agent(half_year, ci, incidents, now, decided=[
                       p for p in closed if kind_of(p.get("au"), p.get("at")) in ("person", "agent")]),
                   "review_load": agent_ledger.review_load(flow, now),
                   "expected_review": agent_ledger.expected_review(
                       [p for p in flow.get("open") or [] if not p.get("draft")][:300], kept)}}
