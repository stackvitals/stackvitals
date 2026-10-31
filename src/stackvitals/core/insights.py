"""Insights that need two modules' history at once. The first: how long ready pull requests sat with failing checks on
their newest commit before they merged, each wait traced to the run that turned the PR red and the one that cleared it."""
from collections import defaultdict
from datetime import datetime, timedelta

from stackvitals.ci.analyze import _job_reads_pr
from stackvitals.core import metrics
from stackvitals.core.actors import kind_of
from stackvitals.core.joins import coverage_start, runs_by_pr
from stackvitals.core.stats import median
from stackvitals.core.time import iso, secs

FAIL = {"failure", "timed_out", "startup_failure"}
# No verdict on the code: stopped by a newer push, waiting for a maintainer's approval, or never ran.
NO_VERDICT = {"cancelled", "action_required", "stale", "skipped", None, ""}
DEFINITION = ("Time a ready pull request spent with a failing check on its newest commit: from the first failing job "
              "until a new commit, a passing re-run on the same code, or the merge. GitHub Actions runs of the PR's own code only "
              "(pull_request_target runs use the base branch's workflow and are left out, as are checks that read the PR's "
              "title, description or labels); time spent as a draft never counts.")
TOP = 5


def _blamed(failed: list[dict]) -> list[dict]:
    """The failed jobs that did the failing: a job that started only after every other failed job ended is a summary job
    (it waits on them and fails when any did), so it is left out when others failed too."""
    if len(failed) < 2:
        return failed
    real = [j for j in failed if not (j.get("st") and all(o.get("en") and j["st"] >= o["en"] for o in failed if o is not j))]
    return real or failed


def _attempts(runs: list[dict], jobs: list[dict], meta: dict) -> list[dict]:
    """Each finished run attempt with a verdict: when it ended and which of its jobs failed."""
    by_attempt = defaultdict(list)
    for j in jobs:
        by_attempt[(j["run"], j.get("att", 1))].append(j)
    out = []
    for r in runs:
        mine = by_attempt.get((r["id"], r["att"]), [])
        reads_pr = meta.get(r.get("path") or "", ())
        judged = [j for j in mine if not _job_reads_pr(j.get("n") or "", reads_pr)]
        if mine and not judged:
            continue  # only checks of the PR's own text ran
        if judged:
            bad = [j for j in judged if j.get("c") in FAIL]
            failed = sorted({j.get("n") or "?" for j in _blamed(bad)})
            no_verdict = {j.get("c") for j in judged} <= NO_VERDICT
            done = max((j["en"] for j in judged if j.get("en")), default=r.get("up"))
            # GitHub shows the PR red as soon as one job fails, long before the whole run ends.
            done = min((j["en"] for j in bad if j.get("en")), default=done) if bad else done
        else:
            failed = ["(run)"] if r.get("c") in FAIL else []
            no_verdict = False
            done = r.get("up")
        if not done or (not failed and (no_verdict or r.get("c") in NO_VERDICT)):
            continue
        out.append({"run": r["id"], "attempt": r["att"], "sha": r.get("sha"), "wf": r.get("wf") or r.get("path"),
                    "workflow": r.get("wfn") or r.get("path"), "done": done, "failed": failed})
    return out


def draft_spans(pr: dict) -> list[tuple[str, str]]:
    """When the PR was a draft, from its ready/draft toggles: it starts as a draft when its first toggle is "ready"
    (or it has none and is a draft now)."""
    toggles = sorted((e for e in pr.get("ev") or [] if e[0] in ("ready", "draft") and len(e) > 1 and e[1]), key=lambda e: e[1])
    draft = toggles[0][0] == "ready" if toggles else bool(pr.get("draft"))
    spans, since = [], pr["cr"] if draft else None
    for kind, when, *_ in toggles:
        if kind == "draft" and since is None:
            since = when
        elif kind == "ready" and since is not None:
            spans.append((since, when))
            since = None
    if since is not None:
        spans.append((since, "9999"))
    return spans


def _ready_parts(start: str, end: str, drafts: list[tuple[str, str]]) -> list[tuple[str, str]]:
    # The parts of [start, end] when the PR was not a draft.
    parts, cur = [], start
    for a, b in drafts:
        if b <= cur or a >= end:
            continue
        if a > cur:
            parts.append((cur, a))
        cur = max(cur, b)
    if cur < end:
        parts.append((cur, end))
    return parts


def red_intervals(pr: dict, runs: list[dict], jobs: list[dict], meta: dict, end: str) -> list[dict]:
    """The waits of one PR with failing checks on its newest commit, each with the run that started it and what ended it."""
    first_run = {}
    for r in runs:
        if r.get("sha") and r.get("cr"):
            seen = first_run.get(r["sha"])
            if seen is None or (r["cr"], r["id"]) < seen:
                first_run[r["sha"]] = (r["cr"], r["id"])
    # A commit becomes the PR's newest when its first run is created (the push), not when it was authored.
    events = [(cr, 0, ("head", sha, rid)) for sha, (cr, rid) in first_run.items()]
    events += [(a["done"], 1, ("done", a)) for a in _attempts(runs, jobs, meta)]
    events.sort(key=lambda e: (e[0], e[1]))
    stop = pr.get("mg") or pr.get("cl") or end
    latest, head, waits, current = {}, None, [], None
    for when, _, event in events:
        if when > stop:
            break
        if event[0] == "head":
            head = event[1]
        else:
            a = event[1]
            latest[(a["sha"], a["wf"])] = a
        failing = [a for (sha, _wf), a in latest.items() if sha == head and a["failed"]]
        if failing and current is None:
            cause = event[1] if event[0] == "done" and event[1]["failed"] else min(failing, key=lambda a: a["done"])
            current = {"from": when, "failed": {"run": cause["run"], "attempt": cause["attempt"], "workflow": cause["workflow"],
                                                "jobs": cause["failed"]}}
        elif not failing and current is not None:
            if event[0] == "head":
                current.update(to=when, ended_by="push", cleared={"sha": event[1], "run": event[2]})
            else:
                current.update(to=when, ended_by="rerun", cleared={"run": event[1]["run"], "attempt": event[1]["attempt"]})
            waits.append(current)
            current = None
    if current is not None:
        current.update(to=stop, ended_by="merged" if pr.get("mg") else "closed" if pr.get("cl") else "open", cleared=None)
        waits.append(current)
    out, drafts = [], draft_spans(pr)
    for w in waits:
        # A draft's failing checks are its author's work in progress: only the time it was ready counts.
        parts = _ready_parts(w["from"], w["to"], drafts)
        hours = sum(secs(a, b) for a, b in parts) / 3600
        if parts and hours > 0:
            out.append({**w, "from": parts[0][0], "hours": round(hours, 2)})
    return out


def red_ci(prs: list[dict], ci: dict, now: datetime, window_days: int = 90, since: str | None = None, meta: dict | None = None,
           state: dict | None = None) -> dict:
    """How long people's merged PRs sat with failing checks, over the part of the CI history with no gaps."""
    end = iso(now)
    window = iso(now - timedelta(days=window_days))
    start = since or coverage_start(state or {}, ci.get("runs") or [])
    start = max(start, window) if start else window
    if meta is None:
        meta = {path: set(v.get("jobs") or []) for path, v in ((state or {}).get("triggers") or {}).items()}
    by_pr = runs_by_pr(ci.get("runs") or [], prs)
    jobs_by_run = defaultdict(list)
    for j in ci.get("jobs") or []:
        jobs_by_run[j["run"]].append(j)
    rows, no_checks, open_red = [], 0, []
    for p in prs:
        if kind_of(p.get("au"), p.get("at")) != "person" or p["cr"] < start:
            continue
        runs = by_pr.get(p["n"], [])
        mine = [j for rid in {r["id"] for r in runs} for j in jobs_by_run.get(rid, [])]
        if p.get("mg"):
            if p["mg"] > end:
                continue
            if not runs:
                no_checks += 1
                continue
            waits = red_intervals(p, runs, mine, meta, end)
            rows.append({"pr": p["n"], "red_h": round(sum(w["hours"] for w in waits), 2),
                         "rerun_h": round(sum(w["hours"] for w in waits if w["ended_by"] == "rerun"), 2),
                         "cycle_h": (secs(p.get("cr"), p["mg"]) or 0) / 3600, "waits": waits})
        elif not p.get("cl") and runs:
            waits = red_intervals(p, runs, mine, meta, end)
            if waits and waits[-1]["ended_by"] == "open":
                open_red.append({"pr": p["n"], "since": waits[-1]["from"], "hours": waits[-1]["hours"]})
    red = [r for r in rows if r["red_h"] > 0]
    jobs = defaultdict(lambda: {"hours": 0.0, "prs": set(), "runs": []})
    tests = defaultdict(lambda: {"hours": 0.0, "prs": set(), "runs": []})
    failed_tests = defaultdict(set)
    for rep in ci.get("tests") or []:
        failed_tests[(rep["run"], rep["att"])] |= {f[0] for f in rep["failed"]}
    for r in rows:
        for w in r["waits"]:
            if w["ended_by"] == "rerun":
                # A re-run that passed on the same code: the hours are shared by the jobs that had failed.
                for name in w["failed"]["jobs"]:
                    entry = jobs[(w["failed"]["workflow"], name)]
                    entry["hours"] += w["hours"] / len(w["failed"]["jobs"])
                    entry["prs"].add(r["pr"])
                    entry["runs"].append([w["failed"]["run"], w["failed"]["attempt"]])
                # And by the tests those jobs reported failing, when the run kept its test reports.
                names = failed_tests.get((w["failed"]["run"], w["failed"]["attempt"])) or set()
                for name in names:
                    entry = tests[name]
                    entry["hours"] += w["hours"] / len(names)
                    entry["prs"].add(r["pr"])
                    entry["runs"].append([w["failed"]["run"], w["failed"]["attempt"]])
    measures = [metrics.measure("insight.red_ci_share", hits=len(red), n=len(rows), as_of=now, window_days=window_days),
                metrics.measure("insight.red_ci_hours", values=[r["red_h"] for r in red], as_of=now, window_days=window_days)]
    return {"definition": DEFINITION, "since": start, "until": end, "prs": len(rows), "without_checks": no_checks,
            "red_prs": len(red), "red_hours_total": round(sum(r["red_h"] for r in rows), 2),
            "rerun_hours_total": round(sum(r["rerun_h"] for r in rows), 2),
            "rerun_waits": sum(1 for r in rows for w in r["waits"] if w["ended_by"] == "rerun"),
            "measures": {m.metric: m.to_dict() for m in measures},
            "cycle_hours": {"red": {"median": _round(median([r["cycle_h"] for r in red])), "n": len(red)},
                            "clear": {"median": _round(median([r["cycle_h"] for r in rows if not r["red_h"]])),
                                      "n": len(rows) - len(red)}},
            "rerun_jobs": sorted(({"workflow": wf, "job": job, "hours": round(v["hours"], 2), "prs": len(v["prs"]),
                                   "runs": v["runs"][-5:]}
                                  for (wf, job), v in jobs.items()), key=lambda x: -x["hours"]),
            "rerun_tests": sorted(({"test": name, "hours": round(v["hours"], 2), "prs": len(v["prs"]),
                                    "pr_list": sorted(v["prs"])[-10:], "runs": v["runs"][-5:]}
                                   for name, v in tests.items()), key=lambda x: (-x["hours"], x["test"]))[:20],
            "top": [{"pr": r["pr"], "hours": r["red_h"], "waits": r["waits"]}
                    for r in sorted(red, key=lambda r: -r["red_h"])[:TOP]],
            "open_red": sorted(open_red, key=lambda x: x["since"])}


def evidence_chains(red: dict | None, ci: dict | None, decisions: dict, top: int = 10) -> list[dict]:
    """Each test whose failures held merged PRs red until a re-run passed, traced end to end: the hours and PRs it held,
    CI Health's verdict and flake count, the owners CODEOWNERS names for its file, and the decision recorded on it."""
    tests = {t["id"]: t for t in (ci or {}).get("tests") or []}
    out = []
    for r in ((red or {}).get("rerun_tests") or [])[:top]:
        t = tests.get(r["test"]) or {}
        d = decisions.get(f"test:{r['test']}")
        out.append({"test": r["test"], "hours": r["hours"], "prs": r["prs"], "pr_list": r.get("pr_list") or [],
                    "state": t.get("state"), "flake_events": t.get("flake_events"), "runs": t.get("runs"),
                    "owners": t.get("owners") or [], "owners_from": t.get("owners_from"),
                    "decision": {k: d.get(k) for k in ("verb", "by", "at", "until", "reason")} if d else None})
    return out


def _round(x):
    return None if x is None else round(x, 1)


ENDED = {"push": "a new commit", "rerun": "a passing re-run on the same code", "merged": "the merge (still red)",
         "closed": "closing", "open": "nothing yet"}


def _plain(text, markdown: bool) -> str:
    # Job and workflow names come from workflow files a fork's PR can change: no links, mentions or markup in summaries.
    if not markdown:
        return str(text)
    from stackvitals.flow.report import _md
    return _md(text).replace("@", "@​").replace("](", "]​(").replace("www.", "www​.")


def _span(hours: float) -> str:
    return f"{hours / 24:.1f} days" if hours >= 48 else f"{hours:g} h"


def render(out: dict, repo: str, markdown: bool = False) -> str:
    """The red-CI insight in a few lines: counts, ranges, the longest waits with links to the runs, open PRs red now."""
    share, hours = out["measures"]["insight.red_ci_share"], out["measures"]["insight.red_ci_hours"]
    head = (f"Red CI in {repo}: people's merged pull requests opened since {out['since'][:10]} that ran checks: "
            f"{out['prs']}" + (f" ({out['without_checks']} more ran none)." if out.get("without_checks") else "."))
    if not out["prs"]:
        return head + " Nothing to measure yet."
    pct = lambda x: f"{x * 100:.0f}%"  # noqa: E731
    line = f"- {out['red_prs']} of {out['prs']} spent time ready for review with a failing check on their newest commit"
    if share["value"] is not None:
        line += f" ({pct(share['value'])}, range {share['low'] * 100:.0f}-{pct(share['high'])})"
    lines = [head, line + "."]
    if out["red_prs"]:
        line = f"- {out['red_hours_total']:g} h in all"
        if hours["value"] is not None:
            span = f" (range {hours['low']:.1f}-{hours['high']:.1f} h)" if hours["low"] is not None else ""
            line += f"; a median {hours['value']:.1f} h per PR{span}"
        lines.append(line + ".")
    if out["rerun_waits"]:
        jobs = "; ".join(f"{_plain(j['job'], markdown)} ({_plain(j['workflow'], markdown)}) {j['hours']:g} h on {j['prs']} "
                         f"PR{'' if j['prs'] == 1 else 's'}" for j in out["rerun_jobs"][:5])
        lines.append(f"- {out['rerun_waits']} of those waits ended with a re-run that passed on the same code: "
                     f"{out['rerun_hours_total']:g} h. {jobs}.")
        if out.get("rerun_tests"):
            named = "; ".join(f"{_plain(t['test'], markdown)} {t['hours']:g} h on {t['prs']} PR{'' if t['prs'] == 1 else 's'}"
                              for t in out["rerun_tests"][:5])
            lines.append(f"- Flaky tests behind those re-runs: {named}.")
    cycle = out["cycle_hours"]
    if cycle["red"]["median"] is not None and cycle["clear"]["median"] is not None:
        lines.append(f"- PRs that went red took a median {cycle['red']['median']:g} h from opening to merge "
                     f"(n={cycle['red']['n']}), the others {cycle['clear']['median']:g} h (n={cycle['clear']['n']}): "
                     f"an association, not a cause.")
    for t in out["top"]:
        w = max(t["waits"], key=lambda x: x["hours"])
        f = w["failed"]
        jobs = ", ".join(_plain(j, markdown) for j in f["jobs"][:3]) + (", ..." if len(f["jobs"]) > 3 else "")
        lines.append(f"- #{t['pr']}: {t['hours']:g} h red; the longest wait, {w['hours']:g} h, began when "
                     f"{_plain(f['workflow'], markdown)} failed ({jobs}) in https://github.com/{repo}/actions/runs/{f['run']}/"
                     f"attempts/{f['attempt']} and ended with {ENDED[w['ended_by']]}.")
    if out["open_red"]:
        lines.append("Open PRs red right now: " + ", ".join(f"#{o['pr']} for {_span(o['hours'])}" for o in out["open_red"][:10]) + ".")
    lines.append(f"Definition: {out['definition']}")
    return "\n".join(lines)


def insights_step(ws, env: dict, now: datetime) -> dict | None:
    """The Action's insights from what the job's checkout holds: what to fix first across modules (Team Flow is enough),
    and the red-CI insight when CI Health's runs are there too."""
    import html
    import json

    from stackvitals import shell
    from stackvitals.ci.store import DataStore
    from stackvitals.core import findings
    from stackvitals.core.store import accept, published, write_if_changed
    from stackvitals.flow.store import FlowStore
    if not (ws.path / "flow" / "closed").is_dir():
        return None
    from stackvitals.core.decisions import visible
    flow = visible(ws.path, ws.cache.get("flow") or FlowStore(ws.path).load(), now.date())
    prs = flow["open"] + flow["closed"]
    out, bumps = None, []
    if (ws.path / "ci" / "days").is_dir():
        ci_store = DataStore(ws.path)
        ci, state = ws.cache.get("ci") or ci_store.load(), ci_store.state()
        out = red_ci(prs, ci, now, state=state)
        meta = {path: set(v.get("jobs") or []) for path, v in (state.get("triggers") or {}).items()}
        bumps = findings.bump_reds(prs, ci, now, meta, since=out["since"])
    docs = ws.path / "docs"
    docs.mkdir(parents=True, exist_ok=True)

    def read(name):
        try:
            return accept(json.loads((docs / name).read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return None
    ledger = None
    if bumps:
        from stackvitals.deps.evidence import load_ledger
        # How the same updates went across the crawl: only read when an update here sat red.
        ledger = load_ledger(env.get("STACKVITALS_TOKEN"), ws.work / "deps")
    found = findings.build(ws.repo, out, ws.cache.get("delivery") or read("delivery.json"), read("flow.json"), bumps, now, ledger,
                           began=findings.began_after(read("data.json"), prs))
    # How long each finding has been around, and what people decided about it (acknowledged, snoozed).
    from stackvitals.core.decisions import Store as Decisions
    days_file = ws.path / "insights" / "ledger.json"
    try:
        before = json.loads(days_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        before = {}
    decided = Decisions(ws.path).state(now.date())
    aside = {k.split(":", 1)[1] for k, d in decided.items() if k.startswith("finding:") and d.get("verb") in findings.SET_ASIDE}
    days = findings.update_ledger(before, found, now, aside)
    if days != before:
        days_file.parent.mkdir(parents=True, exist_ok=True)
        days_file.write_text(json.dumps(days, indent=1, sort_keys=True), encoding="utf-8")
    found = findings.annotate(found, days, decided, now)
    chains = evidence_chains(out, read("data.json"), decided)
    red_html = ("<h2>Red checks on pull requests</h2>" + "".join(f"<p>{html.escape(line)}</p>" for line in render(out, ws.repo).splitlines())
                if out and out["prs"] else "")
    write_if_changed(docs / "insights.json", published({"generated": iso(now), "red_ci": out, "findings": found,
                                                        "chains": chains, "track_record": findings.track_record(days, now),
                                                        "opportunity": findings.opportunity(found)}),
                     also=lambda: (docs / "insights.html").write_text(findings.render_html(
                         found, ws.repo, now, shell.present(docs) | {"insights.html"}, red_html), encoding="utf-8"))

    def after_commit():
        summary = env.get("GITHUB_STEP_SUMMARY")
        if summary and (found or (out and out["prs"])):
            with open(summary, "a", encoding="utf-8") as f:
                f.write(findings.render_markdown(found, ws.repo))
                if out and out["prs"]:
                    f.write("### StackVitals insights\n" + render(out, ws.repo, markdown=True) + "\n")
    ws.after_commit(after_commit, "Insights", first=True)
    return {"prs": out["prs"] if out else 0, "red_prs": out["red_prs"] if out else 0, "findings": len(found)}
