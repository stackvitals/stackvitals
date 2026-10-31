import html

from stackvitals import shell
from stackvitals.ci.bench import PEERS_ARE
from stackvitals.ci.report import _md as _md_ci

QUEUE_ROWS = 15
STAGE_NAMES = [("pickup", "Waiting for first review"), ("review", "First to final review"),
               ("merge", "Approved to merged"), ("cycle", "Ready to merged")]


def _span(secs) -> str:
    if secs is None:
        return "-"
    secs = int(secs)
    if secs >= 86400:
        return f"{secs // 86400}d {secs % 86400 // 3600}h"
    if secs >= 3600:
        return f"{secs // 3600}h {secs % 3600 // 60}m"
    return f"{secs // 60}m"


def _md(text) -> str:
    # PR titles and logins come from anyone who opens a PR: HTML and Markdown are both neutralised.
    return _md_ci(html.escape(str(text), quote=False))


def _pct(x) -> str:
    return "-" if x is None else f"{x:.0%}"


def _waiting_on(q: dict) -> str:
    if q["actor"] == "reviewers":
        return ", ".join(q["who"])
    if q["actor"] == "author":
        return f"the author ({q['author']})"
    return "maintainers"


def _suggested(q: dict) -> str:
    return "; ".join(f"{x['login']} ({x['why']})" for x in q.get("suggested") or [])


def _knowledge_lines(r: dict) -> list[str]:
    k = r.get("knowledge")
    if not k:
        return []
    one = [a for a in k["areas"] if a["single_owner"]]
    quiet = [a for a in k["areas"] if (a.get("owner_quiet_days") or 0) > 90]
    out = []
    if one:
        out.append("Known mostly by one person: " + ", ".join(
            f"{a['area']} ({a['owner'] + ', ' if a.get('owner') else ''}{a['share']:.0%} of merged PRs)" for a in one[:8]))
    if quiet:
        out.append("Main author gone quiet: " + ", ".join(
            f"{a['area']} ({a['owner'] + ', ' if a.get('owner') else ''}no merged PR for {a['owner_quiet_days']} days)" for a in quiet[:8]))
    if k["hotspots"]:
        out.append("Busiest areas, last 90 days: " + ", ".join(
            f"{h['area']} ({h['prs_90d']} merged PRs)" for h in k["hotspots"][:5]))
    return out


def stage_note(pages) -> str:
    """How first review here differs from Delivery's pickup, which also counts a first comment (LinearB's definition)."""
    where = "<a href='delivery.html'>Delivery's pickup</a>" if "delivery.html" in pages else "Delivery's pickup"
    return (f"<p class=mut>First review counts reviews only. {where} also counts a first comment by someone else "
            "(LinearB's definition), so it is usually shorter.</p>")


def _delivery_lines(r: dict) -> list[str]:
    d = r.get("delivery")
    if not d:
        return []
    if d["source"] == "merges":
        return [f"No releases in the last {r['window_days']} days; {d['per_week']} merged PRs a week."]
    cf = d["change_fail"]
    later = f"; the next release came {_span(d['recovery_median_s'])} later (median)" if d["recovery_median_s"] else ""
    return [f"{d['releases']} releases in {r['window_days']} days ({d['per_week']} a week); merge to release takes "
            f"{_span(d['lead_time_median_s'])} (median).",
            f"{cf['failed']} of {cf['of']} releases were followed by a revert or hotfix within 7 days "
            f"(a proxy; the Delivery page counts change failure the way DevLake does, from incidents){later}."]


def _gaps(q: dict) -> str:
    return "; ".join(g["why"] for g in q.get("gaps") or [])


def _habit_lines(r: dict) -> list[str]:
    h = r.get("habits")
    if not h or not h["merged_prs"]:
        return []
    inc, size = h["include"], h["size"]
    out = [f"Merged PRs ({h['scope']}, n={h['merged_prs']}) include tests {inc['tests']:.0%}, a changelog entry "
           f"{inc['changelog']:.0%}, docs {inc['docs']:.0%}; size {size['median_lines']} lines median, "
           f"90% at most {size['p90_lines']} lines."]
    if h.get("asks"):
        out.append("Maintainers most often ask for: " + ", ".join(f"{a['ask']} ({a['share']:.0%} of reviewed PRs)" for a in h["asks"][:5]))
    return out


def _peer_lines(r: dict) -> tuple[str, list[str]] | None:
    c = r.get("peers")
    if not c:
        return None
    fmt = {"hours": lambda v: _span(v * 3600), "share": lambda v: f"{v:.0%}", "lines": lambda v: f"{v:.0f} lines"}
    lines = [f"{m['name']}: {fmt[m['kind']](m['you'])} (typical {fmt[m['kind']](m['typical'])}), {m['place']}"
             for m in c["metrics"]]
    loose = f", {c['fit']}" if c.get("fit") else ""
    return (f"Compared with {int(c['repos'])} {c['group']} (PRs opened in the last 90 days{loose}); the group is "
            f"{PEERS_ARE}, so it may not resemble a private team's work:"), lines


def _head(r: dict, repo: str) -> str:
    return (f"{repo}: review flow over the last {r['window_days']} days ({r['merged']} merged, {r['closed_unmerged']} closed "
            f"without merging, {r['open']} open of which {r['drafts']} drafts; bot PRs left out: {r['bots']['open']} open, "
            f"{r['bots']['closed']} closed)")


def _groups(r: dict) -> list[str]:
    out = []
    for name, label in (("insider", "Insiders"), ("outsider", "Outside contributors")):
        g = r["groups"][name]
        out.append(f"{label}: {_pct(g['merge_rate'])} merged, first review after {_span(g['pickup']['median_s'])} "
                   f"(median, n={g['pickup']['n']})")
    return out


def render_text(r: dict, repo: str) -> str:
    out = [_head(r, repo), ""]
    if peers := _peer_lines(r):
        out += [peers[0], *[f"  {line}" for line in peers[1]], ""]
    out += ["Median time (90th percentile), GitHub's review stages:"]
    out += [f"  {label}: {_span(r['stages'][k]['median_s'])} ({_span(r['stages'][k]['p90_s'])}), n={r['stages'][k]['n']}"
            for k, label in STAGE_NAMES]
    out += [f"  Merged without any human review: {r['merged_without_review']}", "", *_groups(r), "",
            "Who acts next (overdue first; overdue = longer than usual for this repo, and over a day):"]
    live = [q for q in r["queue"] if not q["stale"]]
    for q in live[:QUEUE_ROWS]:
        flag = "  [overdue]" if q["slow"] else ""
        out.append(f"  #{q['n']} \"{q['title']}\" by {q['author']}{' (outsider)' if q['outsider'] else ''}: waiting on "
                   f"{_waiting_on(q)} for about {_span(q['waiting_s'])} (usual {_span(q['usual_s'])}) - {q['why']}{flag}")
        if q.get("suggested"):
            out.append(f"      suggested reviewers: {_suggested(q)}")
        if q.get("gaps"):
            out.append(f"      unlike merged PRs here: {_gaps(q)}")
    if not live:
        out.append("  nothing waiting")
    if r["stale"]:
        out.append(f"  ... and {r['stale']} stale PRs waiting over 30 days")
    if r["load"]:
        out += ["", "Open review requests: " + ", ".join(f"{x['reviewer']} {x['open_requests']}" for x in r["load"][:10])]
    if habits := _habit_lines(r):
        out += ["", "What merged PRs here usually include:", *[f"  {line}" for line in habits]]
    if knowledge := _knowledge_lines(r):
        out += ["", "Knowledge map:", *[f"  {line}" for line in knowledge]]
    if ship := _delivery_lines(r):
        out += ["", "Delivery:", *[f"  {line}" for line in ship]]
    if r.get("responders"):
        out += ["", "Answer times (private: shown only in this local view, never on the dashboard):"]
        out += [f"  {x['reviewer']}: {_span(x['median_s'])} median (n={x['n']})" for x in r["responders"][:10]]
    return "\n".join(out)


def render_markdown(r: dict, repo: str) -> str:
    out = [f"### StackVitals Team Flow: {_md(repo)}", _md(_head(r, repo).split(": ", 1)[1]), ""]
    if peers := _peer_lines(r):
        out += [_md(peers[0]), *[f"- {_md(line)}" for line in peers[1]], ""]
    out += ["| Stage | Median | 90th percentile | PRs |", "|---|---|---|---|"]
    out += [f"| {label} | {_span(r['stages'][k]['median_s'])} | {_span(r['stages'][k]['p90_s'])} | {r['stages'][k]['n']} |"
            for k, label in STAGE_NAMES]
    out += ["", *[_md(line) for line in _groups(r)], "", "| PR | Waiting on | For | Why |", "|---|---|---|---|"]
    live = [q for q in r["queue"] if not q["stale"]]
    out += [f"| #{q['n']} {_md(q['title'])} | {_md(_waiting_on(q))} | about {_span(q['waiting_s'])}{' (overdue)' if q['slow'] else ''} "
            f"| {_md(q['why'])}{(' - suggested: ' + _md(', '.join(x['login'] for x in q['suggested']))) if q.get('suggested') else ''}"
            f"{(' - ' + _md(_gaps(q))) if q.get('gaps') else ''} |"
            for q in live[:QUEUE_ROWS]] or ["| - | nothing waiting | | |"]
    if r["stale"]:
        out.append(f"\n{r['stale']} stale PRs are waiting over 30 days.")
    for title, lines in (("What merged PRs here usually include", _habit_lines(r)), ("Knowledge map", _knowledge_lines(r)),
                         ("Delivery", _delivery_lines(r))):
        if lines:
            out += ["", f"**{title}**", *[f"- {_md(line)}" for line in lines]]
    return "\n".join(out)


def _hours(secs) -> float | None:
    return None if secs is None else round(secs / 3600, 1)


def _trends(r: dict) -> str:
    months = r.get("monthly") or []
    if len(months) < 2:
        return ""
    labels = [m["month"] for m in months]
    counts = shell.chart("PRs opened and merged per month", "Month", labels,
                         [("Opened", [m["opened"] for m in months]), ("Merged", [m["merged"] for m in months])], y="PRs", kind="bar")
    times = shell.chart("Review times per month (median)", "Month", labels,
                        [("First review", [_hours(m.get("pickup_median_s")) for m in months]),
                         ("Ready to merged", [_hours(m.get("cycle_median_s")) for m in months])], y="hours", fmt=lambda v: f"{v:g} h")
    return ("<h2>Trends</h2><p class=mut>The last 12 months; review times are for PRs merged that month, bots left out.</p>"
            + shell.charts([counts, times]))


def render_html(r: dict, repo: str, pages=()) -> str:
    e = html.escape
    link = lambda n: f"<a href='https://github.com/{e(repo)}/pull/{int(n)}'>#{int(n)}</a>"  # noqa: E731
    body = []
    cards = [("Open PRs", r["open"]), ("Merged", r["merged"]), ("First review (median)", _span(r["stages"]["pickup"]["median_s"])),
             ("Ready to merged (median)", _span(r["stages"]["cycle"]["median_s"])), ("Stale backlog", f"{r['stale']} stale"),
             ("Merged without review", r["merged_without_review"])]
    body.append("<div class=cards>" + "".join(f"<div class=card><span class=mut>{e(k)}</span><b>{e(str(v))}</b></div>"
                                              for k, v in cards) + "</div>")
    if peers := _peer_lines(r):
        body.append(f"<h2>Compared with similar repos</h2><p class=mut>{e(peers[0])}</p><ul>"
                    + "".join(f"<li>{e(line)}</li>" for line in peers[1]) + "</ul>")
    body.append("<h2>Who acts next</h2><p class=mut>Overdue = waiting longer than usual for this repo, and over a day.</p>")
    live = [q for q in r["queue"] if not q["stale"]]
    if live:
        body.append("<div class=tbl><table class=find><tr><th>PR</th><th>Waiting on</th><th>For</th><th>Usual</th><th>Why</th></tr>")
        for q in live[:QUEUE_ROWS * 2]:
            tag = " <span class='tag flaky'>overdue</span>" if q["slow"] else ""
            body.append(f"<tr><td>{link(q['n'])} {e(q['title'] or '')}<br><span class=mut>by {e(q['author'] or '?')}"
                        f"{' (outsider)' if q['outsider'] else ''}</span></td><td>{e(_waiting_on(q))}</td>"
                        f"<td>about {_span(q['waiting_s'])}{tag}</td><td>{_span(q['usual_s'])}</td><td>{e(q['why'])}"
                        + (f"<br><span class=mut>Suggested: {e(_suggested(q))}</span>" if q.get("suggested") else "")
                        + (f"<br><span class=mut>Unlike merged PRs here: {e(_gaps(q))}</span>" if q.get("gaps") else "")
                        + "</td></tr>")
        body.append("</table></div>")
    else:
        body.append("<p>Nothing waiting.</p>")
    if r["stale"]:
        body.append(f"<p class=mut>{r['stale']} stale PRs are waiting over 30 days.</p>")
    if r.get("excluded"):
        n = r["excluded"]
        body.append(f"<p class=mut>{n} pull request{'' if n == 1 else 's'} left out by the team (the "
                    "<code>stackvitals: exclude</code> label or <code>/stackvitals exclude</code>).</p>")
    body.append(_trends(r))
    body.append("<h2>Review stages</h2><div class=tbl><table><tr><th>Stage</th><th>Median</th><th>90th percentile</th><th>PRs</th></tr>"
                + "".join(f"<tr><td>{e(label)}</td><td>{_span(r['stages'][k]['median_s'])}</td><td>{_span(r['stages'][k]['p90_s'])}</td>"
                          f"<td>{r['stages'][k]['n']}</td></tr>" for k, label in STAGE_NAMES) + "</table></div>")
    body.append(stage_note(pages))
    body.append("<h2>Insiders and outside contributors</h2><ul>" + "".join(f"<li>{e(line)}</li>" for line in _groups(r)) + "</ul>")
    for title, lines in (("What merged PRs here usually include", _habit_lines(r)), ("Knowledge map", _knowledge_lines(r)),
                         ("Delivery", _delivery_lines(r))):
        if lines:
            body.append(f"<h2>{title}</h2><ul>" + "".join(f"<li>{e(line)}</li>" for line in lines) + "</ul>")
    if r["load"]:
        body.append("<h2>Open review requests</h2><ul>" + "".join(
            f"<li>{e(x['reviewer'])}: {x['open_requests']} open</li>" for x in r["load"][:20]) + "</ul>")
    body.append("<footer class=mut>Stages follow GitHub's own boundaries; bots, authors and Copilot reviews are left out. "
                "History is kept in this repo's <code>stackvitals-data</code> branch. Made by StackVitals.</footer>")
    return shell.page("Team Flow", repo, "flow.html", f"Last {r['window_days']} days, updated {e(r['generated'])}",
                      "".join(body), pages)
