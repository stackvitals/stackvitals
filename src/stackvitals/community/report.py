import html

from stackvitals import shell
from stackvitals.flow.report import _md

TRAFFIC_HELP = ("Traffic is off: GitHub keeps views and clones for 14 days only, and the built-in token can't read them. "
                "To keep them, give the Action a token from your own GitHub App (see docs/modules.md).")



def _when(stamp: str) -> str:
    # ISO time as people read it; older files already hold "YYYY-MM-DD HH:MM UTC".
    return stamp if stamp.endswith("UTC") else stamp[:16].replace("T", " ") + " UTC"

def _h(hours) -> str:
    if hours is None:
        return "-"
    if hours < 1:
        return "under 1 h"
    return f"{round(hours)} h" if hours < 48 else f"{hours / 24:.1f} d"


def _days(n: int) -> str:
    return f"{n} day" if n == 1 else f"{n} days"


def _pct(x, digits: int = 0) -> str:
    return "-" if x is None else f"{x:.{digits}%}"


def _value(f: dict) -> str:
    return _h(f["you"]) if f["kind"] == "hours" else _pct(f["you"])


def _typical(f: dict) -> str:
    return _h(f["typical"]) if f["kind"] == "hours" else _pct(f["typical"])


def _sections(r: dict) -> list[tuple[str, list[str]]]:
    """Titled groups of plain-text lines, shared by the terminal, the job summary and the page (the waiting list apart)."""
    out = []
    s = r.get("score")
    if s:
        lines = [f"Community score {s['score']}/100: on average better than {s['score']}% of {s['group']} "
                 f"({s['repos']} repos) on {len(s['facts'])} facts."]
        lines += [f"{f['name']}: {_value(f)} (typical {_typical(f)}), better than about {f['better_than']}%." for f in s["facts"]]
        if s["left_out"]:
            lines.append("Not scored yet (too little data here): " + ", ".join(k.replace("_", " ") for k in s["left_out"]) + ".")
        out.append(("Score", lines))
    elif not r.get("has_bench"):
        out.append(("Score", ["No score yet: the public benchmarks aren't available to this run yet."]))
    else:
        out.append(("Score", ["No score yet: it needs two of these facts, and there is too little history here: 10+ outside PRs "
                              "in 90 days, 10+ newcomers two weeks old, 10+ newcomers four months old."]))
    f = r["funnel"]
    out.append(("Newcomers, last 12 months", [
        f"{f['newcomers']} first-time contributors (a first PR or issue here).",
        (f"Of the {f['judged']} whose first contribution was 90+ days ago, {f['returned']} came back within 90 days "
         f"({_pct(f['return_rate'])})." if f["judged"] else "None is old enough yet to tell whether they came back."),
        f"Regulars (active in 3 of the last 4 quarters): {f['regulars']}. Maintainers active: {f['maintainers']}."]))
    a = r["answers"]
    lines = []
    for key, label in (("prs", "Outside PRs"), ("issues", "Outside issues")):
        x = a[key]
        if not x["items"] and x.get("earlier"):
            lines.append(f"No {label.lower()} in the last {a['days']} days ({x['earlier']} in the 9 months before).")
        elif x["items"] and x["median_hours"] is None:
            lines.append(f"{label}: {x['items']}, none answered yet.")
        elif x["items"]:
            km = x.get("km")
            if km and km.get("waiting") and not km.get("too_few"):
                # The median of answered items alone hides the ones still waiting: say both.
                honest = (f"over {_h(km['at_least'])} (more than half have no answer yet)" if km["median"] is None
                          else f"{_h(km['median'])} (likely {_h(km['low'])} "
                               + (f"to {_h(km['high'])})" if km["high"] is not None else "or more)"))
                lines.append(f"{label}: {x['items']}, answered {_pct(x['answered'])}, first answer after "
                             f"{_h(x['median_hours'])} among those answered, within a day {_pct(x['within_1d'])}; counting "
                             f"the {km['waiting']} still waiting, {honest}.")
            else:
                lines.append(f"{label}: {x['items']}, answered {_pct(x['answered'])}, first answer after {_h(x['median_hours'])} "
                             f"(median), within a day {_pct(x['within_1d'])}.")
    if a.get("left_out"):
        n = a["left_out"]["accounts"]
        lines.append(f"Left out: {a['left_out']['items']} items from {n} account{'' if n == 1 else 's'} that opened 20 or more "
                     "in one day (likely automated).")
    for key, label in (("newcomers", "Newcomers (their first contribution here)"), ("regulars", "Regulars")):
        x = (r.get("tenure") or {}).get(key)
        if x and x["n"]:
            lines.append(f"{label}: {x['n']}, " + (f"first answer after {_h(x['median_h'])} (median), within a day "
                                                   f"{_pct(x['answered_1d_share'])}." if x["median_h"] is not None
                                                   else "too few to say (10 needed)."))
    n = (a.get("issues") or {}).get("responders")
    if lines and n:
        lines.append(f"Issues count a reply from a maintainer or one of {n} regular responder{'' if n == 1 else 's'} (people who "
                     "answered 10 or more others' issues or first-reviewed 2 or more others' PRs in the last year); PRs count "
                     "a maintainer's.")
    out.append((f"First answers by the project, last {a['days']} days", lines or ["No outside PRs or issues in this window."]))
    d = r.get("dependency")
    if d:
        lines = [f"{d['merged']} merged pull requests by {d['people']} people in the last {d['days']} days; the most active "
                 f"person made {_pct(d['top_share'])} of them. Bus factor {d['bus_factor']}: the fewest people behind half of "
                 "the merged work."]
        bus, top = (d.get("peers") or {}).get("bus_factor"), (d.get("peers") or {}).get("top_share")
        if bus:
            lines.append(f"{bus['group'][0].upper()}{bus['group'][1:]} ({bus['repos']}): bus factor typically {bus['typical']} "
                         f"(middle half {bus['low']} to {bus['high']})"
                         + (f"; the most active person's share typically {_pct(top['typical'])}." if top else "."))
    else:
        lines = ["Fewer than 20 merged pull requests by people in the last 180 days: not enough to say who carries the work."]
    o = r.get("orgs")
    if o:
        top = ", ".join(f"{x['org']} {_pct(x['share'])}" for x in o["orgs"][:3])
        lines.append((f"Elephant factor {o['factor']}: the fewest organisations behind half the work with a known one"
                      if o["factor"] else "No elephant factor: most of the work is by people with no known organisation")
                     + f"; {_pct(o['unknown_share'])} has none known" + (f"; {top}." if top else "."))
    said = (r.get("context") or {}).get("response_policy")
    if said:
        lines.append(f"The contributing guide promises an answer {said['said']}.")
    stated = (r.get("context") or {}).get("stated") or {}
    if stated.get("capacity"):
        lines.append(f"In the project's own words, who maintains it: {stated['capacity']}")
    if stated.get("norms"):
        lines.append(f"In the project's own words, how it works: {stated['norms']}")
    out.append(("Who carries the work", lines))
    lever = r.get("lever")
    if lever:
        rows = "; ".join(f"{b['bucket']} {_pct(b['returned'], 1)}" for b in lever["by_answer"])
        lines = [f"Across {lever['newcomers']:,} newcomers in {lever['repos']} public repos, the share who came back with new work "
                 f"within 90 days, by how long their first PR waited for an answer: {rows}."]
        if lever["by_outcome"]:
            lines.append("By outcome: " + "; ".join(f"{b['outcome']} {_pct(b['returned'], 1)}" for b in lever["by_outcome"])
                         + ". Newcomers left without an answer came back least often; this is an association across repos, "
                           "not proof that answering brings a given newcomer back.")
        out.append(("Newcomers who came back, by first answer (public repos)", lines))
    st = r.get("stars")
    if st and st.get("gained_12w") is not None:
        # Percentages of a few stars mislead; the benchmarks start at 100 stars too.
        big = (st.get("stars") or 0) >= 100
        line = f"+{st['gained_12w']:,} stars in the last 12 complete weeks" + (f" ({_pct(st['growth_12w'], 1)} growth)" if big else "")
        if st.get("peers"):
            line += f", {st['peers']['place']} of {st['peers']['group']} ({st['peers']['repos']} repos)"
        out.append(("Stars", [line + "."]))
    t = r.get("traffic")
    if t:
        lines = [f"Last {t['days']} days: {t['views_total']:,} views ({t['visitors_total']:,} unique visitors, summed per day) "
                 f"and {t['clones_total']:,} clones; kept since {t['since']}."]
        if t["referrers"]:
            lines.append("Top referrers (" + str(t["referrers_day"]) + "): "
                         + ", ".join(f"{x[0]} {x[1]}" for x in t["referrers"][:5]) + ".")
        out.append(("Traffic", lines))
    else:
        out.append(("Traffic", [TRAFFIC_HELP]))
    return out


def _waiting_lines(r: dict, repo: str = "") -> list[str]:
    def link(w):
        return f" https://github.com/{repo}/{'pull' if w['kind'] == 'pr' else 'issues'}/{int(w['n'])}" if repo else ""
    rows = [f"{'PR' if w['kind'] == 'pr' else 'Issue'} #{w['n']}: waiting {_days(w['days'])}{link(w)}" for w in r["waiting"][:20]]
    if r["waiting_total"] > len(rows):
        rows.append(f"... and {r['waiting_total'] - len(rows)} more")
    return rows or ["Nobody's first contribution is waiting for an answer."]


def render_text(r: dict, repo: str) -> str:
    out = [f"{repo}: community, updated {_when(r['generated'])}", ""]
    sections = _sections(r)
    for title, lines in sections[:1] + [("Newcomers waiting for a first answer", _waiting_lines(r, repo))] + sections[1:]:
        out += [title + ":", *[f"  {line}" for line in lines], ""]
    return "\n".join(out).rstrip()


def render_markdown(r: dict, repo: str) -> str:
    out = [f"### StackVitals Community: {_md(repo)}", ""]
    sections = _sections(r)
    for title, lines in sections[:1] + [("Newcomers waiting for a first answer", _waiting_lines(r))] + sections[1:]:
        out += [f"**{_md(title)}**", *[f"- {_md(line)}" for line in lines], ""]
    return "\n".join(out).rstrip()


def _some(*series) -> bool:
    # A chart of only gaps and zeros says nothing; the text sections already say so.
    return any(v for values in series for v in values)


def _trends(r: dict) -> str:
    figs, qs = [], r.get("quarters") or []
    labels = [q["quarter"] for q in qs]
    hours = [None if q["median_hours"] is None else round(q["median_hours"], 1) for q in qs]
    if _some(hours):
        figs.append(shell.chart("First answers per quarter", "Quarter", labels,
                                [("Median hours to the project's first answer", hours)], y="hours", fmt=lambda v: f"{v:g} h",
                                kind="bar"))
    new, items = [q["newcomers"] for q in qs], [q["items"] for q in qs]
    if _some(new, items):
        figs.append(shell.chart("New contributors per quarter", "Quarter", labels,
                                [("First-time contributors", new), ("Outside PRs and issues", items)], y="count", kind="bar"))
    weeks = (r.get("stars") or {}).get("weeks") or []
    if len(weeks) >= 2 and _some([w[1] for w in weeks]):
        figs.append(shell.chart("Stars per week", "Week", [w[0] for w in weeks], [("Stars", [w[1] for w in weeks])], y="stars"))
    if not figs:
        return ""
    return ("<h2>Trends</h2><p class=mut>Calendar quarters, this one so far. A quarter before the history can tell newcomers "
            "apart shows no newcomer count.</p>" + shell.charts(figs))


def render_html(r: dict, repo: str, pages=()) -> str:
    e = html.escape
    kind = {"pr": "pull", "issue": "issues"}
    body = []
    sections = _sections(r)
    for title, lines in sections[:1]:
        body.append(f"<h2>{e(title)}</h2><ul>" + "".join(f"<li>{e(x)}</li>" for x in lines) + "</ul>")
    body.append("<h2>Newcomers waiting for a first answer</h2>")
    if r["waiting"]:
        body.append("<div class=tbl><table class=find><tr><th>Item</th><th>Waiting</th></tr>" + "".join(
            f"<tr><td><a href='https://github.com/{e(repo)}/{kind.get(w['kind'], 'issues')}/{int(w['n'])}'>"
            f"{'PR' if w['kind'] == 'pr' else 'Issue'} #{int(w['n'])}</a></td><td>{_days(int(w['days']))}</td></tr>"
            for w in r["waiting"]) + "</table></div>")
        if r["waiting_total"] > len(r["waiting"]):
            body.append(f"<p class=mut>... and {r['waiting_total'] - len(r['waiting'])} more.</p>")
    else:
        body.append("<p>Nobody's first contribution is waiting for an answer.</p>")
    body.append(_trends(r))
    for title, lines in sections[1:]:
        body.append(f"<h2>{e(title)}</h2><ul>" + "".join(f"<li>{e(x)}</li>" for x in lines) + "</ul>")
    body.append("<footer class=mut>Outside contributors are people who are not owners, members, collaborators or bots. "
                "Nobody is ranked and nobody is listed as having left. History is kept in this repo's "
                "<code>stackvitals-data</code> branch. Made by StackVitals.</footer>")
    return shell.page("Community", repo, "community.html", f"Updated {e(_when(r['generated']))}", "".join(body), pages)


def badges(r: dict) -> dict[str, dict]:
    """Two shields.io endpoint badges: measured facts, and the score (users pick one or both)."""
    f, s = r.get("facts") or {}, r.get("score")
    parts = []
    if f.get("first_answer_hours") is not None:
        parts.append(f"first answer {_h(f['first_answer_hours'])}")
    if f.get("newcomer_return_rate") is not None:
        parts.append(f"newcomers back {_pct(f['newcomer_return_rate'])}")
    elif f.get("newcomer_answered_share") is not None:
        parts.append(f"newcomers answered {_pct(f['newcomer_answered_share'])}")
    facts = {"schemaVersion": 1, "label": "community", "message": " · ".join(parts) or "not enough data yet",
             "color": "blue" if parts else "lightgrey"}
    if s:
        color = "brightgreen" if s["score"] >= 67 else "yellow" if s["score"] >= 40 else "orange"
        scored = {"schemaVersion": 1, "label": "community score", "message": f"{s['score']}/100", "color": color}
    else:
        scored = {"schemaVersion": 1, "label": "community score", "message": "not enough data yet", "color": "lightgrey"}
    return {"community-badge.json": facts, "community-score.json": scored}
