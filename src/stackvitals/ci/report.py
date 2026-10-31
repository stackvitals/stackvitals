import hashlib
import html
import re
from collections import Counter
from urllib.parse import quote

from stackvitals import shell
from stackvitals.ci.analyze import BEGAN_MIN_RUNS, week_of
from stackvitals.ci.bench import PEERS_ARE

STATE_TEXT = {"flaky": "flaky", "suspect": "one flake seen", "broken": "keeps failing", "fixed": "fixed", "ok": "ok"}


def _dur(secs) -> str:
    if secs is None:
        return "-"
    secs = round(secs)
    return f"{secs // 60}m {secs % 60:02d}s" if secs >= 60 else f"{secs}s"


def _wf(path: str | None) -> str:
    return (path or "?").rsplit("/", 1)[-1]


def _md(text) -> str:
    # Names come from workflow files, which a fork PR can edit: escape HTML and Markdown control characters.
    return re.sub(r"([\\`*_\[\]|<>#])", r"\\\1", str(text))


def _groups(result: dict) -> dict:
    jobs = result["jobs"]
    return {
        "flaky": sorted((j for j in jobs if j["state"] in ("flaky", "suspect")),
                        key=lambda j: (j["state"] != "flaky", -j["flake_events"], -j["retry_minutes"])),
        "broken": [j for j in jobs if j["state"] == "broken"],
        "slower": sorted((j for j in jobs if j["slower"]), key=lambda j: -j["slower"]["pct"]),
        "slowest": sorted((j for j in jobs if j["median_s"]), key=lambda j: -j["median_s"])[:10],
    }


def _shown(flaky: list[dict], suspects: int = 5) -> tuple[list[dict], int]:
    # Every flaky job is listed; one-off flakes beyond the first few become one line, so they don't bury the rest.
    real = [j for j in flaky if j["state"] == "flaky"]
    once = [j for j in flaky if j["state"] != "flaky"]
    return real + once[:suspects], max(0, len(once) - suspects)


NO_REPORTS = ("No test reports found in this repo's artifacts, so only whole jobs are judged. To see single flaky "
              "tests, save your JUnit XML, CTRF, Jest or Vitest JSON, go test -json or TRX file with "
              "actions/upload-artifact under a name containing "
              "\"test-results\" or \"junit\".")


def _ms(ms) -> str:
    return "-" if ms is None else f"{ms / 1000:.1f}s"


def _test_groups(result: dict) -> dict:
    tests = result.get("tests") or []
    return {"flaky": sorted((t for t in tests if t["state"] in ("flaky", "suspect")),
                            key=lambda t: (t["state"] != "flaky", -t["flake_events"])),
            "broken": [t for t in tests if t["state"] == "broken"],
            "slow": result.get("slow_tests") or []}


def began_text(b: dict | None) -> str:
    """When a flake began, as one clause, only as sure as the runs before it allow."""
    if not b:
        return ""
    day = b["first"][:10]
    if b["clear"]:
        landed = ", ".join(s[:7] for s in b["landed"])
        return (f"began around {day}: {b['runs_before']} runs before it never flaked (chance p = {b['p']:g})"
                + (f"; reached the default branch the day before: {landed}" if landed else ""))
    if b["runs_before"] < BEGAN_MIN_RUNS:
        return f"first flaked {day}; only {b['runs_before']} runs before it, too few to say it began then"
    return f"first flaked {day}, but flakes before it would have been rare anyway (p = {b['p']:g})"


def _test_line(t: dict) -> str:
    rate = f"{t['flake_rate']:.0%} (likely {t['rate_low']:.0%}-{t['rate_high']:.0%})"
    msg = f"; fails with \"{t['message']}\"" if t.get("message") else ""
    kind = f"; looks like a {t['flake']} flake" if t.get("flake") else ""
    began = f"; {began_text(t['began'])}" if t.get("began") else ""
    return f"{t['flake_events']} flakes in {t['runs']} runs, {rate}{msg}{kind}; last {(t['last_flake'] or '')[:10]}{began}"


def _flaky_line(j: dict) -> str:
    rate = f"{j['flake_rate']:.0%} (likely {j['rate_low']:.0%}-{j['rate_high']:.0%})"
    step = f"; fails in \"{j['top_step']}\"" if j["top_step"] else ""
    lost = f"; {j['retry_minutes']:.0f} min lost to re-runs" if j["retry_minutes"] else ""
    began = f"; {began_text(j['began'])}" if j.get("began") else ""
    return (f"{j['flake_events']} flakes in {j['runs']} runs, {rate}{step}{lost}; last {(j['last_flake'] or '')[:10]}{began}")


def _bench(result: dict, esc=str) -> tuple[str, list[str]] | None:
    # How this repo's pushes compare with similar public repos, from the crawl's daily sample.
    b = result.get("benchmark")
    if not b:
        return None
    lines = []
    for m in b["metrics"]:
        fmt = _dur if m["kind"] == "time" else (lambda v: f"{v:.0%}")
        line = f"{m['name']}: {fmt(m['you'])} (typical {fmt(m['typical'])}), {m['place']}"
        if m.get("pulled") and m["pulled"]["n"] < 30:
            # Under 30 pushes the share alone is noisy: say what the repo and its peers together suggest.
            p = m["pulled"]
            line += f"; from only {p['n']} pushes, similar repos suggest {fmt(p['value'])} (likely {fmt(p['low'])} to {fmt(p['high'])})"
        lines.append(line)
    loose = f" ({esc(b['fit'])})" if b.get("fit") else ""
    peers = esc(b["peers"]) if b.get("peers") else f"{PEERS_ARE}, so it may not resemble a private team's work"
    return (f"Compared with {int(b['repos'])} {esc(b['group'])}{loose}, each push until all its checks finished. The group is "
            f"{peers}:"), lines


def render_text(result: dict, repo: str) -> str:
    if not result["runs"]:
        return f"{repo}: No completed CI runs in the last {result['window_days']} days."
    g = _groups(result)
    m = result["minutes"]
    out = [f"{repo}: CI health over the last {result['window_days']} days ({result['runs']} runs, "
           f"{result['rerun_share']:.0%} re-run, {result['infra_events']} outage(s); queue median "
           f"{_dur(result['queue']['median_s'])}; minutes linux {m['linux']}, windows {m['windows']}, macos {m['macos']})", ""]
    if bench := _bench(result):
        out += [bench[0]] + [f"  {line}" for line in bench[1]] + [""]
    tg = _test_groups(result)
    if result.get("has_test_reports"):
        out.append("Flaky tests (fail, then pass with no code change):")
        tshown, trest = _shown(tg["flaky"])
        out += [f"  [{STATE_TEXT[t['state']]}] {t['id']}: {_test_line(t)}" for t in tshown] or ["  none found"]
        if trest:
            out.append(f"  ... and {trest} more tests with one flake each")
        if tg["broken"]:
            out += [f"  [keeps failing] {t['id']}: failed {t['failures']} of {t['runs']} runs"
                    + (f"; \"{t['message']}\"" if t.get("message") else "") for t in tg["broken"]]
        out.append("")
    else:
        out += [NO_REPORTS, ""]
    out.append("Flaky jobs (fail, then pass with no code change):")
    shown, rest = _shown(g["flaky"])
    out += [f"  [{STATE_TEXT[j['state']]}] {_wf(j['workflow'])} / {j['job']}: {_flaky_line(j).replace(' lost to re-runs', ' lost')}"
            for j in shown] or ["  none found"]
    if rest:
        out.append(f"  ... and {rest} more jobs with one flake each")
    if g["broken"]:
        out += ["", "Keeps failing (not flaky, really broken):"]
        out += [f"  {_wf(j['workflow'])} / {j['job']}: keeps failing ({j['failures']} of {j['runs']} runs failed)"
                for j in g["broken"]]
    if g["slower"]:
        out += ["", "Getting slower (last 7 days vs before):"]
        out += [f"  {_wf(j['workflow'])} / {j['job']}: {_dur(j['slower']['before_s'])} -> {_dur(j['slower']['after_s'])} "
                f"({j['slower']['after_s'] / j['slower']['before_s']:.1f}x slower)".replace(".0x", "x") for j in g["slower"]]
    out += ["", "Slowest jobs (median, 95th percentile):"]
    out += [f"  {_dur(j['median_s']):>8}  {_dur(j['p95_s']):>8}  {_wf(j['workflow'])} / {j['job']}" for j in g["slowest"]]
    if tg["slow"]:
        out += ["", "Slowest tests (median, 95th percentile):"]
        out += [f"  {_ms(t['median_ms']):>8}  {_ms(t['p95_ms']):>8}  {t['id']}"
                + (f"  (+{t['slower']['pct']}% in the last 7 days)" if t["slower"] else "") for t in tg["slow"][:10]]
    if result.get("new_tests"):
        out += ["", "New tests in the last 14 days (runs since, failed, state):"]
        out += [f"  {t['runs']:>4}  {t['failures']:>4}  {t['state']:<8} {t['id']}" for t in result["new_tests"][:10]]
    if result.get("skipped_tests"):
        out += ["", "Skipped on the default branch (days):"]
        out += [f"  {t['days']:>4}  {t['id']}" + ("  (newly skipped)" if t["new"] else "") for t in result["skipped_tests"][:10]]
    return "\n".join(out)


def render_markdown(result: dict, repo: str) -> str:
    if not result["runs"]:
        return f"### StackVitals CI health: {_md(repo)}\n\nNo completed CI runs in the last {result['window_days']} days."
    g = _groups(result)
    out = [f"### StackVitals CI health: {_md(repo)}",
           f"{result['runs']} runs in {result['window_days']} days, {result['rerun_share']:.0%} re-run, "
           f"queue median {_dur(result['queue']['median_s'])}.", ""]
    if bench := _bench(result, _md):
        out += [bench[0]] + [f"- {line}" for line in bench[1]] + [""]
    tg = _test_groups(result)
    if tg["flaky"]:
        out += ["| State | Test | Flakes | Fails with |", "|---|---|---|---|"]
        out += [f"| {STATE_TEXT[t['state']]} | {_md(t['id'])} | {t['flake_events']} of {t['runs']} runs | {_md(t.get('message') or '-')} |"
                for t in tg["flaky"][:10]] + [""]
    out += ["| State | Job | Flakes | Most failing step | Lost to re-runs |", "|---|---|---|---|---|"]
    out += [f"| {STATE_TEXT[j['state']]} | {_md(_wf(j['workflow']))} / {_md(j['job'])} | {j['flake_events']} of {j['runs']} runs "
            f"| {_md(j['top_step'] or '-')} | {j['retry_minutes']:.0f} min |" for j in g["flaky"][:10]] or ["| - | no flaky jobs | | | |"]
    big = [x for x in result.get("failure_groups") or [] if x["tests"] > 1]
    if big:
        x = big[0]
        out.append(f"Biggest failure group: same failure in {x['tests']} tests ({x['failures']} failures): "
                   f"{_md(x['type'])} at {_md(x['where'] or '-')}.\n")
    for j in g["broken"]:
        out.append(f"\nKeeps failing: **{_md(_wf(j['workflow']))} / {_md(j['job'])}** ({j['failures']} of {j['runs']} runs).")
    for j in g["slower"][:5]:
        out.append(f"\nGetting slower: **{_md(_wf(j['workflow']))} / {_md(j['job'])}** "
                   f"{_dur(j['slower']['before_s'])} -> {_dur(j['slower']['after_s'])}.")
    return "\n".join(out)


CSS = shell.CSS


MONITOR_TEXT = {"pass_on_retry": "pass on retry", "failure_rate": "failure rate", "broken": "keeps failing"}


def _why(t: dict) -> str:
    """Which monitors hold the test in its state, its labels, since when and any mute, in plain words."""
    parts = []
    for m in t.get("monitors") or []:
        text = MONITOR_TEXT.get(m, m)
        if m == "failure_rate" and t.get("failure_rate") is not None:
            text += f" {t['failure_rate']:.0%}"
        parts.append(text)
    parts += [x.replace("_", " ") for x in t.get("labels") or []]
    if t.get("since"):
        parts.append(f"since {t['since'][:10]}")
    if t.get("decision"):
        parts.append(decided_text(t))
    elif t.get("muted_until"):
        parts.append(f"muted until {t['muted_until']}")
    return ", ".join(parts)


DECIDED = {"quarantine": "quarantined", "unquarantine": "kept out of quarantine", "mute": "muted", "unmute": "unmuted",
           "acknowledge": "acknowledged", "reopen": "reopened"}


def decided_text(item: dict) -> str:
    """Who decided what about a test or job, until when and why, in plain words."""
    d = item.get("decision") or {}
    if not d:
        return ""
    return (f"{DECIDED.get(d.get('verb'), d.get('verb'))} by {d.get('by') or '?'}" + (f" until {d['until']}" if d.get("until") else "")
            + (f": {d['reason']}" if d.get("reason") else ""))


def _groups_html(result: dict, repo: str) -> str:
    e = html.escape
    groups = [g for g in result.get("failure_groups") or [] if g["tests"] > 1 or g["failures"] > 1]
    if not groups:
        return ""
    rows = []
    for g in groups[:20]:
        ex = (g.get("examples") or [{}])[0]
        link = (f"<a href='https://github.com/{e(repo)}/actions/runs/{int(ex['run'])}/attempts/{int(ex['att'])}'>latest</a>"
                if ex.get("run") and int(ex["run"]) > 0 else "")
        rows.append(f"<tr><td>{e(g['type'] or '-')}</td><td><code>{e(g['where'] or '-')}</code></td><td>{e(g['message'] or '')}</td>"
                    f"<td>{g['tests']} tests</td><td>{g['failures']} in {g['runs']} runs</td>"
                    f"<td>{e((g['first'] or '')[:10])} to {e((g['last'] or '')[:10])}</td><td>{link}</td></tr>")
    return ("<h2>Failure groups</h2><p class=mut>Failures with one cause: the same exception raised at the same place in your "
            "code, across tests and runs. Fix the cause once instead of each test.</p><div class=tbl><table class=find><tr>"
            "<th data-filter>Error</th><th>Where</th><th>Message</th><th>Tests</th><th>Failures</th><th>Seen</th><th>Run</th></tr>"
            + "".join(rows) + "</table></div>")


def _seen(item: dict, repo: str) -> str:
    # The last-seen date links to the newest run that proves the flake.
    day = html.escape((item.get("last_flake") or "")[:10])
    ev = (item.get("evidence") or [])[-1:]
    if not ev or not day:
        return day
    url = f"https://github.com/{html.escape(repo)}/actions/runs/{int(ev[0]['run'])}/attempts/{int(ev[0]['att'])}"
    return f"<a href='{url}'>{day}</a>"


def detail_name(kind: str, ident: str) -> str:
    """The file name of one test's or job's history page: readable, and unique through a short hash."""
    slug = re.sub(r"[^a-z0-9]+", "-", ident.lower()).strip("-")[-60:].strip("-")
    return f"{kind}-{slug}-{hashlib.sha1(ident.encode('utf-8')).hexdigest()[:8]}.html"


def _name(kind: str, ident: str, label: str, result: dict) -> str:
    # Linked to its history page when one is written (items that are not ok).
    if ident in ((result.get("history") or {}).get(kind + "s") or {}):
        return f"<a href='history/{detail_name(kind, ident)}'>{html.escape(label)}</a>"
    return html.escape(label)


def _owners_cell(item: dict) -> str:
    # Plain text on the page: naming people here notifies nobody.
    where = html.escape(item.get("owners_from") or "")
    who = html.escape(", ".join(item.get("owners") or [])) or "-"
    return f"<td title='CODEOWNERS for {where}'>{who}</td>"


def _owners_note(item: dict) -> str:
    if not item.get("owners"):
        return ""
    return (f"<p>Owners: {html.escape(', '.join(item['owners']))} "
            f"<span class=mut>(CODEOWNERS for {html.escape(item['owners_from'])})</span></p>")


def _trends(result: dict) -> str:
    weeks = result.get("weekly") or []
    if len(weeks) < 2:
        return ""
    labels = [w["week"] for w in weeks]
    flaky = shell.chart("Flaky share per week", "Week", labels, [("Job runs that flaked", [w["flake_share"] for w in weeks])],
                        y="% of job runs", fmt=lambda v: f"{v:g}%")
    waits = shell.chart("Push to all checks done, per week (median)", "Week", labels,
                        [("Minutes", [None if w["push_median_s"] is None else round(w["push_median_s"] / 60, 1) for w in weeks])],
                        y="minutes", fmt=lambda v: f"{v:g} min")
    return ("<h2>Trends</h2><p class=mut>Every week of the kept history. Push waits leave out pushes that needed a re-run, "
            "like the comparison with other repos.</p>" + shell.charts([flaky, waits]))


def render_html(result: dict, repo: str, pages=()) -> str:
    e = html.escape
    sub = f"Last {result['window_days']} days, updated {e(result['generated'])}"
    wrap = lambda body: shell.page("CI health", repo, "ci.html", sub, body, pages)  # noqa: E731
    if not result["runs"]:
        return wrap(f"<p>No completed CI runs in the last {result['window_days']} days.</p>")
    g, m = _groups(result), result["minutes"]
    cards = [("Runs", result["runs"]), ("Re-run share", f"{result['rerun_share']:.0%}"),
             ("Flaky jobs", sum(j["state"] == "flaky" for j in result["jobs"])),
             ("Lost to re-runs", f"{sum(j['retry_minutes'] for j in g['flaky']):.0f} min"),
             ("Queue median", _dur(result["queue"]["median_s"])), ("Minutes (all runners)", sum(m.values()))]
    body = ["<div class=cards>" + "".join(f"<div class=card><span class=mut>{e(k)}</span><b>{e(str(v))}</b></div>"
                                          for k, v in cards) + "</div>",
            ]
    body.append(_trends(result))
    if bench := _bench(result, e):
        body.append(f"<h2>Compared with similar repos</h2><p class=mut>{bench[0]}</p><ul>"
                    + "".join(f"<li>{line}</li>" for line in bench[1]) + "</ul>")
    tg = _test_groups(result)
    if result.get("has_test_reports"):
        body.append("<h2>Flaky tests</h2>")
        if tg["flaky"] or tg["broken"]:
            named = any("owners" in t for t in tg["flaky"] + tg["broken"])
            body.append("<div class=tbl><table class=find><tr><th data-filter>State</th><th>Test</th><th>Flakes</th><th>Flake rate</th>"
                        "<th>Why</th><th>Fails with</th><th>Last seen</th>" + ("<th>Owners</th>" if named else "") + "</tr>")
            for t in tg["flaky"] + tg["broken"]:
                body.append(f"<tr><td><span class='tag {t['state']}'>{e(STATE_TEXT[t['state']])}</span></td><td>{_name('test', t['id'], t['id'], result)}</td>"
                            f"<td>{t['flake_events']} of {t['runs']}</td><td>{t['flake_rate']:.0%} "
                            f"<span class=mut>({t['rate_low']:.0%}-{t['rate_high']:.0%})</span></td>"
                            f"<td>{e(_why(t))}</td><td>{e(t.get('message') or '-')}</td><td>{_seen(t, repo)}</td>"
                            + (_owners_cell(t) if named else "") + "</tr>")
            body.append("</table></div>")
        else:
            body.append("<p>No flaky tests found.</p>")
        body.append(_groups_html(result, repo))
    else:
        body.append(f"<p class=mut>{e(NO_REPORTS)}</p>")
    body.append("<h2>Flaky jobs</h2><p class=mut>Failed, then passed with no code change: on a re-run, or on another run of the same code.</p>")
    if g["flaky"]:
        named = any("owners" in j for j in g["flaky"])
        body.append("<div class=tbl><table class=find><tr><th data-filter>State</th><th>Job</th><th>Flakes</th><th>Flake rate</th>"
                    "<th>Most failing step</th><th>Lost</th><th>Last seen</th>" + ("<th>Owners</th>" if named else "") + "</tr>")
        for j in g["flaky"]:
            body.append(f"<tr><td><span class='tag {j['state']}'>{e(STATE_TEXT[j['state']])}</span></td>"
                        f"<td>{_name('job', j['workflow'] + '|' + j['job'], _wf(j['workflow']) + ' / ' + j['job'], result)}"
                        + (f"<br><span class=mut>{e(decided_text(j))}</span>" if j.get("decision") else "") + "</td>"
                        f"<td>{j['flake_events']} of {j['runs']}</td>"
                        f"<td>{j['flake_rate']:.0%} <span class=mut>({j['rate_low']:.0%}-{j['rate_high']:.0%})</span></td>"
                        f"<td>{e(j['top_step'] or '-')}</td><td>{j['retry_minutes']:.0f} min</td><td>{_seen(j, repo)}</td>"
                        + (_owners_cell(j) if named else "") + "</tr>")
        body.append("</table></div>")
    else:
        body.append("<p>No flaky jobs found.</p>")
    if g["broken"]:
        body.append("<h2>Keeps failing</h2><ul>" + "".join(
            f"<li>{_name('job', j['workflow'] + '|' + j['job'], _wf(j['workflow']) + ' / ' + j['job'], result)}: "
            f"{j['failures']} of {j['runs']} runs failed</li>" for j in g["broken"]) + "</ul>")
    if g["slower"]:
        body.append("<h2>Getting slower</h2><ul>" + "".join(
            f"<li>{e(_wf(j['workflow']))} / {e(j['job'])}: {_dur(j['slower']['before_s'])} &rarr; {_dur(j['slower']['after_s'])} "
            f"(+{j['slower']['pct']}%) in the last 7 days</li>" for j in g["slower"]) + "</ul>")
    body.append("<h2>Slowest jobs</h2><div class=tbl><table class=find><tr><th>Job</th><th>Median</th><th>95th percentile</th><th>Runs</th></tr>"
                + "".join(f"<tr><td>{e(_wf(j['workflow']))} / {e(j['job'])}</td><td>{_dur(j['median_s'])}</td>"
                          f"<td>{_dur(j['p95_s'])}</td><td>{j['runs']}</td></tr>" for j in g["slowest"]) + "</table></div>")
    if tg["slow"]:
        body.append("<h2>Slowest tests</h2><div class=tbl><table class=find><tr><th>Test</th><th>Median</th><th>95th percentile</th><th>Change</th></tr>"
                    + "".join(f"<tr><td>{e(t['id'])}</td><td>{_ms(t['median_ms'])}</td><td>{_ms(t['p95_ms'])}</td>"
                              f"<td>{'+' + str(t['slower']['pct']) + '% last 7 days' if t['slower'] else '-'}</td></tr>"
                              for t in tg["slow"]) + "</table></div>")
    cov = result.get("coverage")
    if cov and cov.get("latest"):
        lt = cov["latest"]
        change = "" if cov.get("change") is None else f", {cov['change'] * 100:+.1f} points over the window"
        body.append(f"<h2>Coverage</h2><p>Line coverage on the default branch: {lt['pct']:.1%} ({lt['covered']} of {lt['lines']} "
                    f"lines, {e(lt['at'][:10])}{change}).</p>")
        if cov.get("prs"):
            body.append("<div class=tbl><table class=find><tr><th>Pull request</th><th>Added lines that ran</th></tr>" + "".join(
                f"<tr><td><a href='https://github.com/{e(repo)}/pull/{int(p['pr'])}'>#{int(p['pr'])}</a></td>"
                f"<td>{'-' if p['pct'] is None else format(p['pct'], '.0%')} ({p['covered']} of {p['lines']})</td></tr>"
                for p in cov["prs"][:30]) + "</table></div>")
    if result.get("new_tests"):
        body.append("<h2>New tests, last 14 days</h2><div class=tbl><table class=find><tr><th>Test</th><th>First seen</th>"
                    "<th>Runs since</th><th>Failed</th><th>State</th></tr>" + "".join(
                        f"<tr><td>{e(t['id'])}</td><td>{e(t['first'][:10])}</td><td>{t['runs']}</td><td>{t['failures']}</td>"
                        f"<td>{e(t['state'])}</td></tr>" for t in result["new_tests"]) + "</table></div>")
    if result.get("skipped_tests"):
        body.append("<h2>Skipped on the default branch</h2><div class=tbl><table class=find><tr><th>Test</th><th>Since</th>"
                    "<th>For</th><th>Jobs</th></tr>" + "".join(
                        f"<tr><td>{e(t['id'])}{' (newly skipped)' if t['new'] else ''}</td><td>{e(t['since'][:10])}</td>"
                        f"<td>{t['days']} days</td><td>{t.get('suites', 1)}</td></tr>" for t in result["skipped_tests"])
                    + "</table></div>")
    body.append(f"<footer class=mut>Minutes: linux {m['linux']}, windows {m['windows']}, macOS {m['macos']}, other {m['other']}. "
                "History is kept in this repo's <code>stackvitals-data</code> branch. Made by StackVitals.</footer>")
    return wrap("".join(body))


FLAKE_TEXT = {"retry": "passed on a re-run", "flip": "the same code passed in another run",
              "in_job": "passed on a retry inside the job"}
MAX_ROWS = 300


def render_detail(kind: str, ident: str, item: dict, rows: list, result: dict, repo: str, pages=()) -> str:
    """One test's or job's page: its runs over the kept history, newest first, flakes marked and every run linked."""
    e = html.escape
    label = ident if kind == "test" else f"{_wf(item.get('workflow'))} / {item.get('job')}"
    sub = (f"<span class='tag {e(item['state'])}'>{e(STATE_TEXT[item['state']])}</span> {item['flake_events']} flakes in "
           f"{item['runs']} runs over the last {result['window_days']} days &middot; <a href='../ci.html'>back to CI health</a>")
    body = [_owners_note(item), f"<p class=mut>Fails with: {e(item['message'])}</p>" if item.get("message") else ""]
    runs, flakes = Counter(week_of(r[0]) for r in rows), Counter(week_of(r[0]) for r in rows if r[4])
    first = min(runs, default=None)
    weeks = [w["week"] for w in result.get("weekly") or [] if first and w["week"] >= first]
    if len(weeks) >= 2:
        body.append(shell.charts([shell.chart("Runs and flakes per week", "Week", weeks,
                                              [("Runs", [runs[w] for w in weeks]), ("Flakes", [flakes[w] for w in weeks])],
                                              y="runs", kind="bar")]))
    newest = sorted(rows, key=lambda r: r[0], reverse=True)
    # The newest runs, then older flakes, so a page stays small even for a job that flakes all the time.
    keep = newest[:MAX_ROWS] + [r for r in newest[MAX_ROWS:] if r[4]][:MAX_ROWS]
    body.append("<h2>Runs</h2><div class=tbl><table class=find><tr><th>When</th><th data-filter>Result</th><th>Run</th>"
                "<th>Branch</th><th>Event</th></tr>")
    for when, run, att, passed, flake, branch, event in keep:
        cell = (f"<span class='tag flaky'>flaky</span> <span class=mut>{e(FLAKE_TEXT.get(flake, flake))}</span>" if flake
                else "passed" if passed else "<span class='tag broken'>failed</span>")
        url = f"https://github.com/{e(repo)}/actions/runs/{int(run)}/attempts/{int(att)}"
        body.append(f"<tr><td class=nw>{e(when[:16].replace('T', ' '))}</td><td>{cell}</td><td><a href='{url}'>{int(run)}</a></td>"
                    f"<td>{e(branch or '-')}</td><td>{e(event or '-')}</td></tr>")
    body.append("</table></div>")
    if len(keep) < len(rows):
        body.append(f"<p class=mut>Showing the newest {MAX_ROWS} runs and up to {MAX_ROWS} older flakes; "
                    f"{len(rows) - len(keep)} older runs left out.</p>")
    return shell.page(label, repo, None, sub, "".join(body), pages, root="../", app_route=f"ci/{kind}/{quote(label, safe='')}")
