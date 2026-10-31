"""What to fix first, across modules: each finding is one plain sentence with its number, n, links to the evidence and
the action, ranked by the hours of waiting or outage at stake. Built from the public outputs only (never a reviewer's
name, D5), so the same list can sit on a public page."""
import html
from collections import defaultdict
from datetime import datetime, timedelta

from stackvitals.core.time import iso

MIN_PRS = 10  # the red-CI share needs this many merged PRs
FIX_MIN_HOURS = 1.0
FIX_MIN_PRS = 2
GAP_MIN_HOURS = 4.0
GAP_MIN_GROUP = 10
STALE_HOURS = 30 * 24  # a review request older than this is backlog to triage, not today's queue
# The crawl's upgrade ledger as evidence: enough PRs and repos, and how far above these repos' usual failure rate counts.
CRAWL_MIN_PRS, CRAWL_MIN_REPOS, CRAWL_EXCESS = 20, 10, 0.15


def _h(hours: float) -> str:
    return f"{hours / 24:.1f} days" if hours >= 48 else f"{hours:.1f} h"


def _run_links(repo: str, runs) -> list[dict]:
    return [{"label": f"run {r[0]} attempt {r[1]}", "url": f"https://github.com/{repo}/actions/runs/{int(r[0])}/attempts/{int(r[1])}"}
            for r in (runs or [])[:5]]


def _pr_link(repo: str, n: int, kind: str = "pull") -> dict:
    return {"label": f"#{int(n)}", "url": f"https://github.com/{repo}/{kind}/{int(n)}"}


def _deployment_link(repo: str, dep: str | None) -> dict | None:
    if not dep:
        return None
    if dep.startswith("release:"):
        tag = dep.split(":", 1)[1]
        return {"label": f"release {tag}", "url": f"https://github.com/{repo}/releases/tag/{tag}"}
    if dep.startswith("run:"):
        return {"label": f"deploy run {dep[4:]}", "url": f"https://github.com/{repo}/actions/runs/{dep[4:]}"}
    return {"label": "production deployment", "url": f"https://github.com/{repo}/deployments"}


def _red_ci(repo: str, r: dict | None) -> list[dict]:
    if not r or r.get("prs", 0) < MIN_PRS or not r.get("red_prs"):
        return []
    share = r["measures"].get("insight.red_ci_share") or {}
    rng = f" (likely {share['low']:.0%}-{share['high']:.0%})" if share.get("low") is not None else ""
    return [{"kind": "red_ci", "hours": r["red_hours_total"], "n": r["prs"],
             "title": f"{r['red_prs']} of {r['prs']} merged pull requests{rng} sat ready with failing checks: "
                      f"{_h(r['red_hours_total'])} in all, {_h(r.get('rerun_hours_total') or 0)} of it cleared only by re-runs.",
             "action": "Start with the flaky jobs and tests below; the PRs that waited longest are linked.",
             "evidence": [_pr_link(repo, t["pr"]) for t in r.get("top") or []][:5] or [{"label": "Insights page", "url": "insights.html"}]}]


def began_after(ci_doc: dict | None, prs: list[dict]) -> dict:
    """For each flaky job or test whose start is clear (no flakes in the runs before, Fisher's test), the pull requests
    whose merge commits reached the default branch the day before it first flaked: where to look first."""
    by_commit = {p.get("mc"): p["n"] for p in prs if p.get("mc") and p.get("mg")}
    out = {}
    for kind, rows, name in (("job", (ci_doc or {}).get("jobs") or [], "job"), ("test", (ci_doc or {}).get("tests") or [], "id")):
        # Findings name a job without its workflow file, so a job name two workflows share gets no note.
        seen = [row.get(name) for row in rows]
        for row in rows:
            if seen.count(row.get(name)) > 1:
                continue
            b = row.get("began") or {}
            merged = [by_commit[s] for s in b.get("landed") or [] if s in by_commit]
            if b.get("clear") and merged and row.get(name):
                out[f"{kind}:{row[name]}"] = {"day": b["first"][:10], "prs": merged[-3:]}
    return out


def _began_note(repo: str, info: dict | None) -> tuple[str, list[dict]]:
    if not info:
        return "", []
    prs = ", ".join(f"#{n}" for n in info["prs"])
    return (f" It began flaking around {info['day']}, right after {prs} merged: look there first.",
            [_pr_link(repo, n) for n in info["prs"]])


def _fixes(repo: str, r: dict | None, began: dict | None = None) -> list[dict]:
    out = []
    for j in (r or {}).get("rerun_jobs") or []:
        if j["hours"] >= FIX_MIN_HOURS and j["prs"] >= FIX_MIN_PRS:
            note, links = _began_note(repo, (began or {}).get(f"job:{j['job']}"))
            out.append({"kind": "fix_job", "key": f"fix_job:{j['workflow']} / {j['job']}", "hours": j["hours"], "n": j["prs"],
                        "title": f"{j['workflow']} / {j['job']} failed and then passed on the same code, keeping {j['prs']} "
                                 f"pull requests red for {_h(j['hours'])}.{note}",
                        "action": "Fix it, or quarantine its flaky tests in .github/stackvitals.toml so PRs stop waiting on it.",
                        "evidence": links + (_run_links(repo, j.get("runs")) or [{"label": "CI Health page", "url": "ci.html"}])})
    for t in (r or {}).get("rerun_tests") or []:
        if t["hours"] >= FIX_MIN_HOURS and t["prs"] >= FIX_MIN_PRS:
            note, links = _began_note(repo, (began or {}).get(f"test:{t['test']}"))
            out.append({"kind": "fix_test", "key": f"fix_test:{t['test']}", "hours": t["hours"], "n": t["prs"],
                        "title": f"Test {t['test']} failed in runs that a re-run then passed, keeping {t['prs']} pull requests "
                                 f"red for {_h(t['hours'])}.{note}",
                        "action": "Fix the test or quarantine it (`stackvitals ci quarantine`); its failure group is on the CI page.",
                        "evidence": links + (_run_links(repo, t.get("runs")) or [{"label": "CI Health page", "url": "ci.html"}])})
    return out


def _review_waits(repo: str, d: dict | None) -> list[dict]:
    items = ((d or {}).get("stuck") or {}).get("hanging_review") or []
    cap = ((d or {}).get("window_days") or 90) * 24  # a request older than the window counts the window's hours
    now_waiting = sorted((x for x in items if (x.get("hours") or 0) <= STALE_HOURS), key=lambda x: -(x.get("hours") or 0))
    stale = sorted((x for x in items if (x.get("hours") or 0) > STALE_HOURS), key=lambda x: x["since"])
    out = []
    if now_waiting:
        out.append({"kind": "review_wait", "hours": sum(x.get("hours") or 0 for x in now_waiting), "n": len(now_waiting),
                    "title": f"{len(now_waiting)} pull requests have waited 3 to 30 days for a review someone was asked for "
                             f"(the longest {_h(now_waiting[0].get('hours') or 0)}).",
                    "action": "Pick them up or ask someone else; open review requests per reviewer are on the Team Flow page.",
                    "evidence": [_pr_link(repo, x["pr"]) for x in now_waiting[:10]]})
    if stale:
        out.append({"kind": "stale_review", "hours": sum(min(x.get("hours") or 0, cap) for x in stale), "n": len(stale),
                    "title": f"{len(stale)} review requests have gone unanswered for over 30 days, the oldest since "
                             f"{stale[0]['since'][:10]}.",
                    "action": "Review them, or close the pull requests nobody will take, so contributors are not left waiting.",
                    "evidence": [_pr_link(repo, x["pr"]) for x in stale[:10]]})
    return out


def _incidents(repo: str, d: dict | None) -> list[dict]:
    out = []
    for i in (d or {}).get("incidents") or []:
        if not i.get("deployment") or i.get("hours_to_restore") is None:
            continue
        after = (datetime.fromisoformat(i["created"].replace("Z", "+00:00"))
                 - datetime.fromisoformat(i["deployment_finished"].replace("Z", "+00:00"))).total_seconds() / 3600
        what = {"revert": "A revert", "hotfix": "A hotfix", "issue": "An incident"}.get(i["source"], "An incident")
        dep = _deployment_link(repo, i["deployment"])
        out.append({"kind": "incident", "key": f"incident:{int(i['number'])}", "hours": i["hours_to_restore"], "n": 1,
                    "title": f"{what} (#{int(i['number'])}) began {_h(after)} after {dep['label']}; it was fixed "
                             f"{_h(i['hours_to_restore'])} after that deployment.",
                    "action": "Look at what that deployment shipped; it counts in the change failure rate.",
                    "evidence": [_pr_link(repo, i["number"], "issues" if i["source"] == "issue" else "pull"), dep]})
    return out


def _outsider_gap(repo: str, f: dict | None) -> list[dict]:
    groups = (f or {}).get("groups") or {}
    ins, out = (groups.get(k, {}).get("pickup") or {} for k in ("insider", "outsider"))
    if (ins.get("n") or 0) < GAP_MIN_GROUP or (out.get("n") or 0) < GAP_MIN_GROUP:
        return []
    a, b = (ins.get("median_s") or 0) / 3600, (out.get("median_s") or 0) / 3600
    if b - a < GAP_MIN_HOURS or b < 2 * a:
        return []
    return [{"kind": "outsider_wait", "hours": round((b - a) * out["n"], 1), "n": out["n"],
             "title": f"Outside contributors wait {_h(b)} for a first review (median of {out['n']} PRs); "
                      f"insiders wait {_h(a)} (n={ins['n']}).",
             "action": "Say who answers new contributors; Team Flow's queue shows the outside PRs waiting now.",
             "evidence": [{"label": "Team Flow page", "url": "flow.html"}]}]


def _crawl(b: dict, ledger: dict | None) -> tuple[str, bool] | None:
    """How the same update went across the crawled repos: (sentence, likely the update's fault), when there is enough."""
    cells = (ledger or {}).get(f"{b.get('ecosystem')}:{b.get('package')}") or []
    c = next((c for c in cells if c.get("bump") == b.get("bump")), None)
    if not c or (c.get("ci_known") or 0) < CRAWL_MIN_PRS or (c.get("repos") or 0) < CRAWL_MIN_REPOS:
        return None
    fail, usual = c["ci_failed"] / c["ci_known"], (c.get("expected_failed") or 0) / c["ci_known"]
    return (f"across {c['repos']} crawled repos, {b['package']} {b['to']} failed CI in {fail:.0%} of {c['ci_known']} "
            f"checked pull requests (their other updates fail {usual:.0%})"), fail - usual >= CRAWL_EXCESS


def _bumps(repo: str, bumps: list[dict] | None, ledger: dict | None = None) -> list[dict]:
    red = [b for b in bumps or [] if b.get("hours")]
    if not red:
        return []
    hours = sum(b["hours"] for b in red)
    names = ", ".join(f"{b['package']} {b['to']}" + (" (still open)" if b.get("state") == "open" else "") for b in red[:5])
    seen = [(b, found) for b in red[:5] if (found := _crawl(b, ledger))]
    title = f"{len(red)} dependency updates sat with failing checks for {_h(hours)}: {names}."
    if seen:
        title += " " + "; ".join(text for _b, (text, _bad) in seen) + "."
    guilty = [b["package"] for b, (_text, bad) in seen if bad]
    if guilty:
        action = (f"For {', '.join(guilty)} it is likely the update itself (it fails far more often than these repos' other "
                  "updates): pin it or wait for a fix; for the rest, look at this repo's own checks first.")
    elif seen:
        action = ("Across the crawl these updates fail no more often than other updates, so look at this repo's own checks "
                  "first (a flaky test, or a check the update exposed).")
    else:
        action = "Check whether the update or a flaky test failed; fix or pin the package."
    return [{"kind": "bump_red", "hours": round(hours, 1), "n": len(red), "title": title, "action": action,
             "evidence": [_pr_link(repo, b["pr"]) for b in red[:10]]}]


def build(repo: str, red_ci: dict | None, delivery: dict | None, flow: dict | None, bumps: list[dict] | None,
          now: datetime, ledger: dict | None = None, began: dict | None = None) -> list[dict]:
    """Every finding with enough evidence, most hours first."""
    out = (_review_waits(repo, delivery) + _red_ci(repo, red_ci) + _fixes(repo, red_ci, began) + _incidents(repo, delivery)
           + _outsider_gap(repo, flow) + _bumps(repo, bumps, ledger))
    red = any(f["kind"] == "red_ci" for f in out)
    for f in out:
        f["hours"] = round(f["hours"], 1)
        f["as_of"] = iso(now)
        f.setdefault("key", f["kind"])  # one finding of its kind per repo; per-item kinds carry their subject
        if red and f["kind"] in ("fix_job", "fix_test"):
            # Waits that only a re-run cleared are inside the red-CI hours: counted there, not added again.
            f["part_of"] = "red_ci"
    return sorted(out, key=lambda f: -f["hours"])


def opportunity(found: list[dict]) -> dict:
    """The estimated hours at stake across open findings, each hour counted once (findings inside another are left out
    of the sum). An estimate of what fixing could win back, not hours proven lost."""
    open_ = [f for f in found if not f.get("decision")]
    fixes = [f for f in open_ if f["kind"] in ("fix_job", "fix_test")]
    rest = sum(f["hours"] for f in open_ if f not in fixes)
    if any(f["kind"] == "red_ci" for f in open_):
        inside = len(fixes)  # re-run waits sit inside the open red-CI hours
    else:
        # Jobs and tests split the same re-run waits, so only the larger of the two counts.
        inside = 0
        rest += max(sum(f["hours"] for f in fixes if f["kind"] == k) for k in ("fix_job", "fix_test"))
    return {"hours": round(rest, 1), "findings": len(open_), "inside_another": inside}


LEDGER_DAYS = 90
SET_ASIDE = ("acknowledge", "snooze")


def update_ledger(ledger: dict, found: list[dict], now: datetime, set_aside: set | None = None) -> dict:
    """Each finding's first day and the days it was active in the last 90 (today counted once, so a second run on the same
    day changes nothing); a finding quiet for 90 days is forgotten."""
    today = now.date()
    floor = (today - timedelta(days=LEDGER_DAYS - 1)).isoformat()
    active, out = {f["key"]: f for f in found}, {}
    # found is ranked, most hours first; the top is the first nobody acknowledged or snoozed.
    top = next((f["key"] for f in found if f["key"] not in (set_aside or set())), None)
    for key in sorted(set(ledger) | set(active)):
        entry = ledger.get(key) or {}
        kept = {d for d in entry.get("days") or [] if d >= floor}
        days = sorted(kept | ({today.isoformat()} if key in active else set()))
        if days:
            # Still seen within the window: the same finding since its first day; otherwise it starts again today.
            again = bool(kept and entry.get("first"))
            hours = active[key]["hours"] if key in active else entry.get("hours_last")
            tops = {d for d in (entry.get("top_days") or []) if d >= floor and again} | ({today.isoformat()} if key == top else set())
            out[key] = {"first": entry["first"] if again else days[0], "last": days[-1], "days": days,
                        "hours_first": entry.get("hours_first") if again else hours, "hours_last": hours,
                        **({"top_days": sorted(tops)} if tops else {})}
    return out


CLEARED_DAYS = 7  # a top finding not seen for this long counts as cleared


def track_record(ledger: dict, now: datetime) -> dict:
    """Whether the finding ranked first was acted on: of the findings that ever topped the list in the last 90 days, how
    many later shrank to half their hours or less, and how many cleared (not seen for a week)."""
    tops = {k: e for k, e in ledger.items() if e.get("top_days")}
    cutoff = (now.date() - timedelta(days=CLEARED_DAYS)).isoformat()
    shrank = sum(1 for e in tops.values() if e.get("hours_first") and (e.get("hours_last") or 0) <= e["hours_first"] / 2)
    return {"top_findings": len(tops), "shrank_by_half": shrank,
            "cleared": sum(1 for e in tops.values() if e["last"] < cutoff),
            "since": min((e["top_days"][0] for e in tops.values()), default=None)}


def annotate(found: list[dict], ledger: dict, decisions: dict, now: datetime) -> list[dict]:
    """Open since, the share of the last 90 days it was active (over half: structural, Swarmia's rule), and the decision
    someone made on it (acknowledged or snoozed findings leave the top of the list until the decision ends)."""
    out = []
    for f in found:
        g = {k: v for k, v in f.items() if k != "decision"}
        entry = ledger.get(f["key"])
        if entry:
            share = round(len(entry["days"]) / LEDGER_DAYS, 2)
            g.update(open_since=entry["first"], active_share_90d=share, structural=share > 0.5)
        decided = decisions.get(f"finding:{f['key']}")
        if decided and decided.get("verb") in SET_ASIDE:
            g["decision"] = {k: decided.get(k) for k in ("verb", "by", "at", "until", "reason")}
        out.append(g)
    return out


def bump_reds(prs: list[dict], ci: dict, now: datetime, meta: dict | None = None, since: str | None = None) -> list[dict]:
    """Dependency-update PRs (Dependabot, Renovate) with the hours their newest commit sat with failing checks."""
    from mergescout.signals.bumps import parse_bump
    from stackvitals.core.insights import red_intervals
    from stackvitals.core.joins import runs_by_pr
    by_pr = runs_by_pr(ci.get("runs") or [], prs)
    jobs_by_run = defaultdict(list)
    for j in ci.get("jobs") or []:
        jobs_by_run[j["run"]].append(j)
    out = []
    for p in prs:
        info = parse_bump(p.get("ti"), p.get("head"), p.get("au"))
        runs = by_pr.get(p["n"]) or []
        if not info or not runs or (since and p["cr"] < since):
            continue
        mine = [j for rid in {r["id"] for r in runs} for j in jobs_by_run.get(rid, [])]
        # A bot's PR is never a draft and nobody marks it ready, so every red hour counts.
        waits = red_intervals({**p, "draft": False, "ev": []}, runs, mine, meta or {}, iso(now))
        hours = sum(w["hours"] for w in waits)
        if hours:
            out.append({"pr": p["n"], "package": info.get("package") or "?", "to": info.get("to_version") or "?",
                        "ecosystem": info.get("ecosystem"), "bump": info.get("bump"),
                        "hours": round(hours, 1), "state": "merged" if p.get("mg") else "closed" if p.get("cl") else "open"})
    return sorted(out, key=lambda b: -b["hours"])


def _safe_md(text: str) -> str:
    # No pings or links from PR titles or package names in the job summary.
    return text.replace("@", "@​").replace("](", "]​(").replace("www.", "www​.")


def render_markdown(found: list[dict], repo: str, top: int = 3) -> str:
    open_ = [f for f in found if not f.get("decision")]
    if not found:
        return ""
    lines = ["### StackVitals: what to fix first"]
    for k, f in enumerate(open_[:top], 1):
        links = ", ".join(f"[{_safe_md(e['label'])}]({e['url']})" for e in f["evidence"][:3] if e["url"].startswith("https://"))
        lines.append(f"{k}. {_safe_md(f['title'])} {_safe_md(f['action'] or '')}" + (f" ({links})" if links else ""))
    if len(open_) > top:
        lines.append(f"\n{len(open_) - top} more on the Insights page.")
    if len(open_) < len(found):
        lines.append(f"\n{len(found) - len(open_)} acknowledged or snoozed by the team (on the Insights page).")
    return "\n".join(lines) + "\n"


def render_html(found: list[dict], repo: str, now: datetime, pages=(), red_ci_html: str = "") -> str:
    from stackvitals import shell
    e = html.escape
    total = opportunity(found)
    body = ["<h2>What to fix first</h2><p class=mut>Ranked by the estimated hours of waiting or outage at stake; each with its "
            "sample size and the evidence. Built from the public pages only: no one is named.</p>",
            f"<p>Estimated opportunity: {e(_h(total['hours']))} across {total['findings']} findings, each hour counted once"
            + (f" ({total['inside_another']} flaky-CI findings are inside the red-CI hours, not added)" if total["inside_another"] else "")
            + ". An estimate of what fixing could win back, not hours proven lost.</p>" if total["findings"] else ""]
    open_, aside = [f for f in found if not f.get("decision")], [f for f in found if f.get("decision")]
    if not open_:
        body.append("<p>Nothing stands out yet.</p>")

    def card(f):
        links = " ".join(f"<a href='{e(x['url'])}'>{e(x['label'])}</a>" for x in f["evidence"][:10])
        since = (f"; open since {e(f['open_since'])}, active {f['active_share_90d']:.0%} of the last 90 days"
                 + (" (structural)" if f.get("structural") else "")) if f.get("open_since") else ""
        d = f.get("decision")
        said = (f"<p class=mut>{e(d['verb'])} by {e(d.get('by') or '?')}" + (f" until {e(d['until'])}" if d.get("until") else "")
                + (f": {e(d['reason'])}" if d.get("reason") else "") + "</p>") if d else ""
        return (f"<div class=card><p><b>{e(f['title'])}</b></p><p>{e(f['action'] or '')}</p>"
                f"<p class=mut>n={f['n']}; {f['hours']} h at stake{since}; evidence: {links}</p>{said}</div>")
    body += [card(f) for f in open_]
    if aside:
        body.append("<h2>Acknowledged or snoozed</h2>" + "".join(card(f) for f in aside))
    return shell.page("Insights", repo, "insights.html", f"Updated {e(iso(now))}.", "".join(body) + red_ci_html, pages)
