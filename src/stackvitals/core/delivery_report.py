"""The Delivery page, the job summary section and the Action step that writes them from the job's checkout."""
import html
import json
from datetime import timedelta

from stackvitals import shell
from stackvitals.ci.bench import PEERS_ARE
from stackvitals.core.time import iso

NAMES = {"coding": "Coding", "pickup": "Pickup", "review": "Review", "approve": "Approve", "merge": "Merge",
         "deploy": "Deploy", "cycle": "Cycle time", "cycle_to_merge": "Cycle time to merge"}
HELP = {"coding": "first commit to opened", "pickup": "ready for review to the first other person's comment or review",
        "review": "first comment or review to merge", "approve": "first comment or review to first approval",
        "merge": "first approval to merge", "deploy": "merge to the deployment that shipped it",
        "cycle": "coding + pickup + review + deploy", "cycle_to_merge": "coding + pickup + review"}
STUCK = {"hanging_review": "Hanging review (asked more than 3 days ago, no review yet)",
         "long_lived": "Long-lived (ready for more than 30 days)", "high_interaction": "High interaction (10+ comments or reviews)",
         "red_and_idle": "Red and idle (failing checks nobody acted on for a day)"}
DORA_TEXT = {"elite": "elite", "high": "high", "medium": "medium", "low": "low", None: "not enough data"}


def _h(hours) -> str:
    if hours is None:
        return "-"
    if hours >= 48:
        return f"{hours / 24:.1f} days"
    return f"{hours:.1f} h" if hours >= 1 else f"{hours * 60:.0f} min"


def _pct(x) -> str:
    return "-" if x is None else f"{x:.0%}"


SURE = {"high": "sure: GitHub deployments to production", "medium": "fairly sure: published versions",
        "low": "a guess from workflow names"}


TRACKERS = {"jira": "Jira", "linear": "Linear"}
ISSUE_TYPES = {"REQUIREMENT": "Stories and features", "BUG": "Bugs", "TASK": "Tasks", "INCIDENT": "Incidents"}


def _copilot_line(c: dict) -> str:
    e = html.escape
    return (f"<li>Copilot in {e(str(c['org']))}, last {c['window_days']} days (GitHub's own reports, {c['days_kept']} days kept "
            f"since {e(c['first_day'])}): {c['monthly_active_users'] or 0} monthly active users, {_pct(c['acceptance'])} of "
            f"suggestions accepted, {c['org_prs_by_copilot']} pull requests by Copilot across the org "
            f"({c['org_prs_merged_by_copilot']} merged), {c['repo_prs_by_copilot']} in this repo.</li>")


def _points(x: dict) -> str:
    return "-" if x["points_scope"] is None else f"{x['points_done']:g} of {x['points_scope']:g}"


def _incident_link(i: dict, repo: str) -> str:
    e = html.escape
    if str(i.get("url") or "").startswith("https://"):
        return f"<a href='{e(i['url'])}'>{e(str(i['number']))}</a>"
    kind = "issues" if i["source"] == "issue" else "pull"
    return f"<a href='https://github.com/{e(repo)}/{kind}/{int(i['number'])}'>#{int(i['number'])}</a>"


def render_html(r: dict, repo: str, pages=()) -> str:
    e = html.escape
    d = r["dora"]
    sub = (f"Last {r['window_days']} days, updated {e(r['generated'])}. Deployments from: {e(r['deploy_source'] or 'none found')}"
           f"{' (' + SURE[r.get('deploy_confidence')] + ')' if r.get('deploy_confidence') else ''}. "
           f"DORA tiers: DevLake's {e(d['report'])} tables, counted as its DORA dashboard counts them.")
    if r.get("deployments_unreadable"):
        sub += " GitHub deployments could not be read: add `deployments: read` to the workflow's permissions to count them."
    if r.get("deploy_confidence") == "low":
        counted = ", ".join(f"{e(str(x['name']))} ({x['n']})" for x in r.get("deploy_names") or [])
        sub += (f" Guessed from workflow names: {counted}. If these do not put code in front of users, set source = \"releases\" "
                "or name the right workflow in deploy_workflow under [delivery] in .github/stackvitals.toml.")
    body = [f"<h2>Cycle time</h2><p class=mut>{r['prs']} merged pull requests by people (bots and coding agents left out); "
            f"{r['outliers']['over_60_days']} over 60 days and {r['outliers']['over_p98']} above the 98th percentile left out "
            "(LinearB's outlier rule)"
            + (f", and {r['excluded']} the team excluded" if r.get("excluded") else "")
            + ". P75 is the number LinearB's bands use.</p><div class=tbl><table class=find><tr>"
            "<th>Phase</th><th>What it measures</th><th>P50</th><th>P75</th><th>PRs</th><th>LinearB band</th></tr>"]
    for name, label in NAMES.items():
        s = r["phases"][name]
        rng = f" <span class=mut>({_h(s['low_h'])}-{_h(s['high_h'])})</span>" if s["low_h"] is not None else ""
        if not s.get("enough", True):
            body.append(f"<tr><td>{label}</td><td class=mut>{HELP[name]}</td><td colspan=2>not enough data (under 10 PRs)</td>"
                        f"<td>n={s['n']}</td><td>-</td></tr>")
            continue
        body.append(f"<tr><td>{label}</td><td class=mut>{HELP[name]}</td><td>{_h(s['p50_h'])}{rng}</td><td>{_h(s['p75_h'])}</td>"
                    f"<td>n={s['n']}</td><td>{e(s['linearb_band'] or '-')}</td></tr>")
    body.append("</table></div>")
    for key, title, note in (("by_team", "By team", "Teams from [identity.teams] in .github/stackvitals.toml, by their members' PRs."),
                             ("by_owner", "By owning team", "Teams in CODEOWNERS, by the PRs touching their paths; single people are left out.")):
        groups = r.get(key) or {}
        if groups:
            body.append(f"<h3>{title}</h3><p class=mut>{note}</p><div class=tbl><table class=find><tr><th>Team</th>"
                        "<th>Cycle time to merge P50</th><th>P75</th><th>Pickup P75</th><th>Review P75</th><th>PRs</th></tr>")
            for team, g in groups.items():
                c = g["cycle_to_merge"]
                cells = (f"<td>{_h(c['p50_h'])}</td><td>{_h(c['p75_h'])}</td><td>{_h(g['pickup']['p75_h'])}</td>"
                         f"<td>{_h(g['review']['p75_h'])}</td>") if c.get("enough", True) else "<td colspan=4>not enough data</td>"
                body.append(f"<tr><td>{e(team)}</td>{cells}<td>n={g['n']}</td></tr>")
            body.append("</table></div>")
    body.append("<h2>DORA</h2><div class=tbl><table><tr><th>Key</th><th>Value</th><th>Tier</th></tr>"
                f"<tr><td>Deployment frequency</td><td>{d['deployment_days_per_week'] if d['deployment_days_per_week'] is not None else '-'} "
                f"deployment days a week (median), {d['deployments']} deployments</td><td>{DORA_TEXT[d['frequency_tier']]}</td></tr>"
                f"<tr><td>Lead time for changes</td><td>{_h(d['lead_time_hours'])} (median of {d['lead_time_n']} deployed PRs)</td>"
                f"<td>{DORA_TEXT[d['lead_time_tier']]}</td></tr>"
                f"<tr><td>Change failure rate</td><td>{_pct(d['change_failure_rate'])} ({d['failed_deployments']} of {d['deployments']} "
                f"deployments had an incident)</td><td>{DORA_TEXT[d['cfr_tier']]}</td></tr>"
                f"<tr><td>Failed deployment recovery</td><td>{_h(d['recovery_hours'])} (median of {d['recovery_n']})</td>"
                f"<td>{DORA_TEXT[d['recovery_tier']]}</td></tr>"
                f"<tr><td>Deployment rework rate</td><td>{_pct(d.get('rework_rate'))} ({d.get('rework_deployments', 0)} of "
                f"{d.get('deployments_n', 0)} deployments shipped a revert or hotfix)</td><td>-</td></tr></table></div>"
                f"<p class=mut>Incidents from {e(r.get('incident_source') or 'GitHub issues, reverts and hotfixes')}, each linked "
                "to the last deployment before it. Change the labels, the deploy workflow pattern or the source in "
                ".github/stackvitals.toml; a connected PagerDuty or incident.io is used instead of labels, reverts and hotfixes.</p>")
    peers = r.get("peers")
    if peers:
        body.append(f"<h2>Compared with similar public repos</h2><p class=mut>{e(peers['group'])} ({peers['repos']} repos in "
                    f"the daily crawl{', ' + e(peers['fit']) if peers.get('fit') else ''}; {PEERS_ARE}, so they may not resemble a private "
                    "team's work). Measured the crawl's way for both: people's PRs opened in the last 90 days, pickup "
                    "from opening.</p><div class=tbl><table><tr><th>Measure</th><th>This repo</th><th>Typical (range)</th>"
                    "<th>Middle half</th><th>Place</th><th>Inside LinearB's good band</th></tr>")
        for m in peers["metrics"]:
            rng = f" ({_h(m['low'])}-{_h(m['high'])})" if m.get("low") is not None else ""
            good = f"{m['linearb']['good']:.0%} of them" if m.get("linearb") else "-"
            body.append(f"<tr><td>{e(m['name'])}</td><td>{_h(m['you'])}</td><td>{_h(m['typical'])}{rng}</td>"
                        f"<td>{_h(m['p25'])}-{_h(m['p75'])}</td><td>{e(m['place'])} (n={m['repos']})</td><td>{good}</td></tr>")
        body.append("</table></div>")
        if peers.get("population") or peers.get("gaps"):
            body.append(f"<p class=mut>Who is compared: {e(peers.get('population') or '-')}. Not covered: "
                        f"{e(peers.get('gaps') or '-')}.</p>")
    agreed = r.get("agreements")
    if agreed:
        body.append(f"<h2>Working agreements</h2><p class=mut>The team's own rules (under [agreements] in .github/stackvitals.toml), "
                    f"over the last {agreed['window_days']} days: {agreed['merged']} merged pull requests, plus open ones already "
                    "past a time limit.</p><div class=tbl><table class=find><tr><th data-filter>Agreement</th><th>Broken by</th></tr>")
        for rule, label in agreed["labels"].items():
            prs = [x for x in agreed["exceptions"] if x["rule"] == rule]
            links = ", ".join(f"<a href='https://github.com/{e(repo)}/pull/{int(x['pr'])}'>#{int(x['pr'])}</a>"
                              + (" (open)" if x["open"] else "") for x in prs[:20]) or "none"
            body.append(f"<tr><td>{e(label)}</td><td>{agreed['counts'][rule]}: {links}</td></tr>")
        body.append("</table></div>")
    body.append("<h2>Stuck pull requests</h2>")
    any_stuck = False
    for key, label in STUCK.items():
        items = r["stuck"].get(key) or []
        if items:
            any_stuck = True
            body.append(f"<h3>{e(label)}: {len(items)}</h3><ul>" + "".join(
                f"<li><a href='https://github.com/{e(repo)}/pull/{int(x['pr'])}'>#{int(x['pr'])}</a>"
                + (f" for {_h(x['hours'])}" if x.get("hours") is not None else "") + "</li>" for x in items[:30]) + "</ul>")
    if not any_stuck:
        body.append("<p>None.</p>")
    sz = r["sizes"]
    body.append(f"<h2>Pull request size</h2><p>Lines added plus removed, merged PRs (n={sz['n']}): under 100: {sz['under_100']}; "
                f"100-155: {sz['100_155']}; 156-228: {sz['156_228']}; over 228: {sz['over_228']} (LinearB's bands). "
                f"Median {sz['p50'] if sz['p50'] is not None else '-'} lines.</p>"
                f"<p>Merged without any review or comment from someone else: {r['merged_without_review']['n']} "
                f"({_pct(r['merged_without_review']['share'])}). Reviewed in under 20 minutes: {len(r['merged_flags']['lightning'])}. "
                f"Review depth: {r['review_depth'] if r['review_depth'] is not None else '-'} comments and reviews per merged PR. "
                f"Merge frequency: {r['merge_frequency'] if r['merge_frequency'] is not None else '-'} merged PRs per author per week.</p>")
    if r["incidents"]:
        body.append("<h2>Incidents</h2><div class=tbl><table class=find><tr><th data-filter>Source</th><th>Item</th><th>Opened</th>"
                    "<th>After deployment</th><th>Restored in</th></tr>" + "".join(
                        f"<tr><td>{e(i['source'])}</td><td>{_incident_link(i, repo)}</td>"
                        f"<td>{e(i['created'][:10])}</td><td>{e(i['deployment'] or 'none before it')}</td>"
                        f"<td>{_h(i['hours_to_restore'])}</td></tr>" for i in r["incidents"]) + "</table></div>")
    q = r.get("merge_queue")
    if q:
        removed = ", ".join(f"{e(str(k))} {v}" for k, v in q["removals"].items()) or "none"
        body.append(f"<h2>Merge queue</h2><p>{q['prs']} pull requests went through the merge queue in the last {q['window_days']} "
                    f"days; {q['merged']} merged, {_h(q['p50_h'])} from entering the queue to merge at the median and "
                    f"{_h(q['p90_h'])} for 9 in 10. Taken out of the queue: {removed}. Merge-group runs: {q['runs']}, "
                    f"{q['failed_runs']} failed.</p>")
        if q["removed_by_flakes"]:
            body.append("<p class=mut>Taken out after a merge-group run that failed only on jobs known to be flaky:</p><ul>" + "".join(
                f"<li><a href='https://github.com/{e(repo)}/pull/{int(x['pr'])}'>#{int(x['pr'])}</a> on {e(x['at'][:10])} "
                f"({e(', '.join(x['jobs']))})</li>" for x in q["removed_by_flakes"][:20]) + "</ul>")
    inv = r.get("investment")
    if inv:
        cats = list(inv["counts"])
        body.append(f"<h2>Where the work went</h2><p>{_mix(inv)}.</p><p class=mut>Merged PRs by people and coding agents since "
                    f"{e(inv['since'])}, sorted by the repo's own label rules, then a security label, the linked issue's type, "
                    "common labels, a changelog fragment, the title's prefix, the files changed (only docs, tests or CI) and "
                    f"the title's first verb; {inv['bots']} update-bot PRs counted apart. Decided by "
                    + ", ".join(f"{e(k)} {v}" for k, v in inv["decided_by"].items()) + ".</p>"
                    "<div class=tbl><table><tr><th>Month</th>" + "".join(f"<th>{e(c)}</th>" for c in cats) + "<th>All</th></tr>"
                    + "".join(f"<tr><td>{e(m['month'])}</td>" + "".join(f"<td>{m['counts'][c]}</td>" for c in cats)
                              + f"<td>{m['n']}</td></tr>" for m in inv["months"]) + "</table></div>")
    t = r.get("tracker")
    if t:
        names = " and ".join(TRACKERS.get(x, x) for x in t["sources"])
        body.append(f"<h2>Issues from {e(names)}</h2><p class=mut>{t['issues']} issues read; {t['linked_prs']} of "
                    f"{t['merged_prs']} merged pull requests name one in their title or branch. Lead time runs from created to "
                    "done, cycle time from the first move to an in-progress status; canceled issues are left out.</p>"
                    "<div class=tbl><table><tr><th>Type</th><th>Done</th><th>Lead time P50</th><th>P75</th>"
                    "<th>Cycle time P50</th><th>P75</th></tr>" + "".join(
                        f"<tr><td>{ISSUE_TYPES.get(k, e(k))}</td><td>{v['n']}</td><td>{_h(v['lead_p50_h'])}</td>"
                        f"<td>{_h(v['lead_p75_h'])}</td><td>{_h(v['cycle_p50_h'])}</td><td>{_h(v['cycle_p75_h'])}</td></tr>"
                        for k, v in t["lead_time"].items()) + "</table></div>")
        if t["planning"]:
            body.append("<h3>Sprints and cycles</h3><p class=mut>Done means finished by the sprint's end; carried over means "
                        "still open when it closed; added after start means moved in once it had begun.</p><div class=tbl>"
                        "<table><tr><th>Sprint</th><th>State</th><th>Scope</th><th>Done</th><th>Carried over</th>"
                        "<th>Added after start</th><th>Points done</th></tr>" + "".join(
                            f"<tr><td>{e(str(x['name']))}</td><td>{e(x['state'].lower())}</td><td>{x['scope']}</td>"
                            f"<td>{x['done']}</td><td>{x['carried_over']}</td><td>{x['added_after_start']}</td>"
                            f"<td>{_points(x)}</td></tr>"
                            for x in reversed(t["planning"])) + "</table></div>")
    ai = r["ai"]
    a, s = ai["agent_prs"], ai["assisted_prs"]
    tools = ", ".join(f"{e(k)} {v}" for k, v in sorted(s["tools"].items())) or "none"
    body.append("<h2>AI and coding agents</h2><p class=mut>Totals only, never a person (an association, not a cause). AI help is "
                "read from co-author trailers in a PR's last five commits and from labels coding tools add.</p><ul>"
                f"<li>Pull requests by coding agents: {a['n']}, merged {_pct(a['merged_share'])}.</li>"
                f"<li>People's merged PRs with AI help: {s['n']} ({_pct(s['share'])}; {tools}); pickup P75 "
                f"{_h(s['pickup_p75_h'])} against {_h(s['others_pickup_p75_h'])} for the rest; size P75 {s['size_p75'] or '-'} lines "
                f"against {s['others_size_p75'] or '-'}.</li>"
                f"<li>Merged PRs reviewed by an AI review bot: {ai['ai_reviewed_prs']['n']}.</li>"
                + (f"<li>In {e(ai['baseline']['group'])} ({ai['baseline']['repos']} repos in the daily crawl, last 6 months), the "
                   f"typical repo merges {_pct(ai['baseline']['agent_merged'])} of coding agents' PRs and "
                   f"{_pct(ai['baseline']['outsider_merged'])} of outside contributors' PRs.</li>" if ai.get("baseline") else "")
                + (_copilot_line(ai["copilot"]) if ai.get("copilot") else "") + "</ul>")
    out = ai.get("outcomes") or {}
    w, matched = out.get("window"), out.get("matched") or {}
    if w and (w.get("assisted", {}).get("n") or w.get("agent", {}).get("n")):
        said = [f"<li>{e(label)}: {e(text)}</li>" for label, text in _matched_lines(matched)]
        peers = ((ai.get("baseline") or {}).get("matched") or {}).get("merged_by_others")
        if peers:
            pts = lambda x: f"{x * 100:+.0f}"  # noqa: E731
            said.append(f"<li>Similar public repos ({ai['baseline']['matched']['repos']} {e(ai['baseline']['group'])}): coding "
                        f"agents' PRs merged by someone else {pts(peers['gap'])} points (likely {pts(peers['low'])} to "
                        f"{pts(peers['high'])}) against people's PRs of the same repo, month and size</li>")
        if said:
            body.append("<h3>Like with like</h3><p class=mut>A person's AI-marked PRs against the same person's other PRs of "
                        "a similar size; coding agents' PRs against people's PRs of the same month and size. Each says the "
                        "gap it could detect when it finds none.</p><ul>" + "".join(said) + "</ul>")
        rows = (("Merged PRs", "n", str), ("Merge rate (merged of merged and closed)", "merge_rate", _pct),
                ("Pickup P75", "pickup_p75_h", _h), ("Review P75", "review_p75_h", _h),
                ("Size P75 (lines)", "size_p75", lambda x: "-" if x is None else f"{x:g}"),
                ("Merged since the CI history began", "ci_n", lambda x: "-" if x is None else str(x)),
                ("A CI run on the PR failed", "ci_failed_share", _pct),
                ("A failed run passed on re-run (flaky)", "flaky_share", _pct), ("Reverted later", "reverted_share", _pct),
                ("Shipped in a deployment with an incident", "failed_deploy_share", _pct))
        side = lambda k: w.get(k) or {}  # noqa: E731
        body.append("<h3>After merge: raw shares, not matched</h3><p class=mut>The last 6 months of merged PRs. CI shares "
                    "count PRs merged since the CI history began; failed deployments count PRs in deployments of up to 5 PRs, "
                    "where an incident can be pinned near a PR.</p>"
                    "<div class=tbl><table><tr><th>Measure</th><th>Coding agents</th><th>AI-marked</th><th>Others</th></tr>"
                    + "".join(f"<tr><td>{label}</td><td>{fmt(side('agent').get(k))}</td><td>{fmt(side('assisted').get(k))}</td>"
                              f"<td>{fmt(side('others').get(k))}</td></tr>" for label, k, fmt in rows) + "</table></div>")
    return shell.page("Delivery", repo, "delivery.html", sub, "".join(body), pages)


OUTCOME_WORDS = {"reverted": "reverted", "ci_failed": "a CI run failed", "failed_deploy": "shipped in a failed deployment",
                 "merged": "merged", "merged_by_others": "merged by someone else"}


def _matched_lines(matched: dict) -> list[tuple[str, str]]:
    # (who, what) for each like-for-like comparison with enough matched PRs.
    out = []
    for side, who in (("assisted", "AI-marked PRs against the same authors' other PRs"),
                      ("agent", "Coding agents' PRs against people's of the same month and size")):
        for key, words in OUTCOME_WORDS.items():
            c = (matched.get(side) or {}).get(key) or {}
            if c.get("gap") is None:
                continue
            if c["verdict"] == "no measurable difference":
                text = f"{words}: no measurable difference (could detect {round(c['detectable'] * 100)} points or more)"
            else:
                pts = lambda x: f"{x * 100:+.0f}"  # noqa: E731
                text = (f"{words}: {'more' if c['verdict'] == 'higher' else 'less'} often, {pts(c['gap'])} points (likely "
                        f"{pts(c['low'])} to {pts(c['high'])}), {c['matched']} of {c['of']} PRs matched")
            out.append((who, text))
    return out


def render_markdown(r: dict, repo: str) -> str:
    d, ph = r["dora"], r["phases"]
    stuck = ", ".join(f"{STUCK[k].split(' (')[0].lower()} {len(v)}" for k, v in r["stuck"].items() if v) or "none"
    return "\n".join([
        f"### StackVitals Delivery: {repo.replace('@', '')}",
        f"{r['prs']} merged PRs in {r['window_days']} days. Cycle time to merge P75 {_h(ph['cycle_to_merge']['p75_h'])}; "
        f"pickup P75 {_h(ph['pickup']['p75_h'])}; review P75 {_h(ph['review']['p75_h'])}.",
        f"DORA ({d['report']}, deployments from {r['deploy_source'] or 'none found'}): {d['deployment_days_per_week'] if d['deployment_days_per_week'] is not None else '-'} "
        f"deployment days a week ({DORA_TEXT[d['frequency_tier']]}); lead time {_h(d['lead_time_hours'])} ({DORA_TEXT[d['lead_time_tier']]}); "
        f"change failure rate {_pct(d['change_failure_rate'])} ({DORA_TEXT[d['cfr_tier']]}); recovery {_h(d['recovery_hours'])} "
        f"({DORA_TEXT[d['recovery_tier']]}); rework rate {_pct(d.get('rework_rate'))}.",
        f"Stuck PRs: {stuck}.",
        *([f"Where the work went ({r['investment']['n']} merged PRs since {r['investment']['since']}): {_mix(r['investment'])}."]
          if r.get("investment") else []), ""])


def _mix(inv: dict) -> str:
    return ", ".join(f"{k} {_pct(v)}" for k, v in sorted(inv["shares"].items(), key=lambda kv: -kv[1]) if v)


STUCK_LABEL = "stackvitals: waiting for review"


def label_stuck_prs(api, out: dict, open_prs: list[dict]) -> dict:
    """Opt-in: label the PRs whose asked-for review has not started after 3 days, and take the label off once one has."""
    from urllib.parse import quote
    hanging = {x["pr"] for x in out["stuck"]["hanging_review"]}
    labelled = {p["n"] for p in open_prs if STUCK_LABEL in (p.get("lb") or [])}
    for n in sorted(hanging - labelled):
        api.send("POST", f"/repos/{api.repo}/issues/{n}/labels", {"labels": [STUCK_LABEL]})
    for n in sorted(labelled - hanging):
        api.send("DELETE", f"/repos/{api.repo}/issues/{n}/labels/{quote(STUCK_LABEL)}")
    return {"added": len(hanging - labelled), "removed": len(labelled - hanging)}


def delivery_step(ws, env: dict, now, window_days: int = 90, label_stuck: bool = False, make_api=None) -> dict | None:
    """The Action's Delivery page, from Team Flow's PRs, CI Health's runs and Community's issues in the checkout. Runs when
    Team Flow ran in the same job (the schedule)."""
    from stackvitals.ci.store import DataStore
    from stackvitals.core.config import parse
    from stackvitals.core.delivery import build
    from stackvitals.core.store import published, write_if_changed
    from stackvitals.flow.store import FlowStore
    if ws.results.get("Team Flow") is None:
        return None
    store = FlowStore(ws.path)
    from stackvitals.core.decisions import visible
    flow = visible(ws.path, ws.cache.get("flow") or store.load(), now.date())
    ci = ws.cache.get("ci") or (DataStore(ws.path).load() if (ws.path / "ci" / "days").is_dir() else {"runs": [], "jobs": []})
    issues = []
    if (ws.path / "community" / "issues").is_dir():
        found = FlowStore(ws.path, "community/issues").load()
        issues = found["open"] + found["closed"]
    cfg = ws.cache.get("settings") or parse("")[0]
    info = store.repo()
    from stackvitals.connectors import active, public
    from stackvitals.connectors import load as load_tracker
    # What the connectors with a key pulled (this job or earlier ones); a public repo's never carry titles.
    tracker = ws.cache.get("tracker") or load_tracker(ws.path, redact=public(ws), names=active(env, cfg))
    out = build(flow, info, ci, issues, now, window_days, cfg, tracker=tracker)
    from stackvitals.core.agent_ledger import agent_of
    from stackvitals.flow import survival
    try:
        lasted = json.loads((store.dir / survival.FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        lasted = {}
    # Lines of people's and agents' PRs still in the default branch 30 and 90 days later.
    out["code_survival"] = survival.summary(lasted, flow["closed"], lambda p: "agent" if agent_of(p) else "person")
    from stackvitals.core.merge_queue import health as queue_health
    try:
        jobs = json.loads((ws.path / "docs" / "data.json").read_text(encoding="utf-8")).get("jobs") or []
    except (OSError, ValueError):
        jobs = []
    # How long the merge queue holds pull requests, and which removals a known flaky job caused (CI Health's states).
    out["merge_queue"] = queue_health(flow["open"] + flow["closed"], ci, {(j.get("workflow"), j.get("job")): j.get("state")
                                                                          for j in jobs}, now, window_days)
    from stackvitals.connectors import copilot_summary
    out["ai"]["copilot"] = copilot_summary(ws.path, now)  # the org's Copilot reports, kept day by day, when connected
    from stackvitals.connectors.ai_spend import summary as spend_summary
    from stackvitals.core.ai_outcomes import mode
    # What the AI tools cost in the last 30 days, beside the agents' and AI-marked PRs merged in the same days.
    month = iso(now - timedelta(days=30))
    out["ai"]["spend"] = spend_summary(ws.path, now, sum(1 for p in flow["closed"] if (p.get("mg") or "") >= month
                                                         and mode(p) in ("agent", "assisted")))
    from stackvitals.connectors.sonar import summary as sonar_summary
    # The Sonar quality gate and measures over time, when [connectors.sonar] names a project.
    out["code_quality"] = sonar_summary(ws.path, now)
    out["excluded"] = flow.get("excluded", 0)
    from stackvitals.core import delivery_peers
    # Where it stands among similar public repos (the crawl's file; absent before launch or offline: no section).
    out["peers"] = delivery_peers.compare(delivery_peers.own_metrics(flow["open"] + flow["closed"], now),
                                          delivery_peers.load(None, ws.work / "bench"),  # public source only, like Team Flow
                                          info.get("language"), info.get("stars"))
    from stackvitals.core.ai_outcomes import baseline
    from stackvitals.flow import peers as flow_peers
    # Coding agents' merge share in similar public repos (Team Flow loaded the crawl's file earlier in this job).
    from stackvitals.core import agent_ledger
    flow_bench = flow_peers.load(None, ws.work / "bench")
    out["ai"]["baseline"] = baseline(flow_bench, info.get("language"), info.get("stars"))
    # Each coding agent across the crawl's public repos, for this repo's own agents to be read against.
    out["ai"]["leaderboard"] = agent_ledger.leaderboard((flow_bench or {}).get("agent_leaderboard"))
    from stackvitals.core import capex
    from stackvitals.core.investment import tracker_types
    # For finance: every merged PR of the last year with its kind of work and epic (docs/capex.csv), and a summary.
    epics = {}
    if tracker:
        from stackvitals.connectors.tracker import pr_links
        by_key = {i.get("key"): i for i in tracker["issues"]}
        epics = {n: (by_key.get(k) or {}).get("epic") or "" for n, k in pr_links(flow["closed"], tracker["issues"])}
    cap_rows = capex.rows(flow["closed"], ws.repo, now, private=not public(ws), base=info.get("default_branch"),
                          rules=(cfg.get("investment") or {}).get("labels"),
                          tracker_types=tracker_types(flow["closed"], tracker["issues"]) if tracker else None, epics=epics)
    out["capex"] = {"months": capex.summary(cap_rows)[-6:], "rows": len(cap_rows), "file": "capex.csv"}
    (ws.path / "docs").mkdir(parents=True, exist_ok=True)
    (ws.path / "docs" / "capex.csv").write_text(capex.to_csv(cap_rows), encoding="utf-8", newline="\n")
    ws.cache["delivery"] = out  # the Insights step after this one reads it
    # Working-agreement nudges: each open pull request breaking one is announced once, decided before the commit.
    from stackvitals.core.agreements import nudge_lines, nudges
    fresh, keep = nudges(out.get("agreements"), store.state().get("nudged") or [])
    if keep != (store.state().get("nudged") or []):
        store.save_state({**store.state(), "nudged": keep})
    from stackvitals.core.export import devlake_tables
    from stackvitals.core.summary import write_devlake_summary
    # CI runs of the last 90 days go into the data branch's DevLake tables, so the summary stays small on busy repos.
    write_devlake_summary(ws.path, devlake_tables(ws.repo, flow, store.repo(), ci, issues, cfg, tracker=tracker,
                                                  ci_since=iso(now - timedelta(days=90))), now)
    docs = ws.path / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    write_if_changed(docs / "delivery.json", published(out),
                     also=lambda: (docs / "delivery.html").write_text(
                         render_html(out, ws.repo, shell.present(docs) | {"delivery.html"}), encoding="utf-8"))

    def after_commit():
        summary = env.get("GITHUB_STEP_SUMMARY")
        failed = None
        if fresh and env.get("STACKVITALS_WEBHOOK"):
            from stackvitals.core import chat
            lines = nudge_lines(fresh, out["agreements"]["labels"], ws.repo)
            failed = chat.post(env["STACKVITALS_WEBHOOK"], chat.message(
                f"Working agreements in {ws.repo}: {len(fresh)} pull request{'' if len(fresh) == 1 else 's'} to look at", lines,
                [], {"repo": ws.repo, "nudges": [{"pr": e["pr"], "rule": e["rule"]} for e in fresh]}), what="the agreements webhook")
        if summary:
            with open(summary, "a", encoding="utf-8") as f:
                f.write(render_markdown(out, ws.repo) + (f"\n{failed}" if failed else "") + "\n")
    ws.after_commit(after_commit, "Delivery")
    result = {"prs": out["prs"], "deployments": out["dora"]["deployments"], "generated": iso(now)}
    if label_stuck:
        if make_api is None:
            from stackvitals.ci.api import ActionsAPI as make_api
        result["labelled"] = label_stuck_prs(make_api(env.get("STACKVITALS_TOKEN"), ws.repo, max_requests=60), out,
                                             flow.get("open") or [])
    return result
