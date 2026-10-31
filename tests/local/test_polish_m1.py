"""Polish pass M1: one shared shell, searchable tables, trend charts and a history page per flaky test or job."""
import json
import re
from datetime import timedelta

from ci_fake import T0, iso

from stackvitals import shell

NOW = T0 + timedelta(days=30)


def test_every_page_gets_one_header_that_links_only_the_pages_that_exist():
    html = shell.page("CI health", "o/r", "ci.html", "Last 30 days", "<p>hi</p>", pages={"community.html"})
    nav = re.search(r"<nav.*?</nav>", html, re.S).group(0)
    assert "ci.html" in nav and "community.html" in nav and "flow.html" not in nav
    assert "aria-current=page" in nav and html.count("<h1>") == 1 and "o/r" in html
    assert "color-scheme" in html and "max-width" in html  # light/dark and phone-width styles come with it
    # A page in a sub-folder (per-test history) links back up.
    deep = shell.page("Test history", "o/r", None, "", "", pages={"ci.html"}, root="../")
    assert "href='../ci.html'" in deep


def test_a_chart_is_drawn_from_its_own_table_so_the_numbers_always_match():
    fig = shell.chart("Flaky share per week", "Week", ["2026-09-28", "2026-10-05"],
                      [("Job runs that flaked", [2.5, None])], y="% of job runs", fmt=lambda v: f"{v:.1f}%")
    assert "data-chart=line" in fig and "<canvas" in fig and "<details open>" in fig
    cells = re.findall(r"<td data-v='([^']*)'>([^<]*)</td>", fig)
    assert cells == [("2.5", "2.5%"), ("", "-")]  # a week with no data is a gap, never a zero
    page = shell.page("CI health", "o/r", "ci.html", "", fig)
    script = re.search(r"<script defer src='([^']+)' integrity='([^']+)' crossorigin=anonymous", page)
    assert script and "/Chart.js/4.5.1/chart.umd.min.js" in script.group(1) and script.group(2).startswith("sha512-")
    assert "cdnjs.cloudflare.com" in script.group(1)
    assert "cdnjs" not in shell.page("CI health", "o/r", "ci.html", "", "<p>no charts</p>")


def test_long_tables_are_marked_for_search_and_their_state_column_for_a_filter():
    from test_ci_report import TESTS

    from stackvitals.ci.report import render_html
    page = render_html(TESTS, "o/r")
    assert "<table class=find" in page and "<th data-filter>State</th>" in page
    assert "q.type='search'" in page  # the inline script that adds the box; the table works without it


def jrun(rid, att, day, c, tree, ev="push", secs=300):
    cr = T0 + timedelta(days=day)
    return {"t": "run", "id": rid, "att": att, "path": ".github/workflows/ci.yml", "wfn": "CI", "ev": ev, "br": "main",
            "sha": f"s{rid}", "tree": tree, "pr": [], "c": c, "cr": iso(cr), "st": iso(cr),
            "up": iso(cr + timedelta(seconds=secs))}


def job(jid, rid, att, day, c, name="test"):
    st = T0 + timedelta(days=day, minutes=10 * (att - 1))
    return {"t": "job", "run": rid, "att": att, "id": jid, "n": name, "c": c, "cr": iso(st), "st": iso(st),
            "en": iso(st + timedelta(minutes=2)), "lb": ["ubuntu-latest"], "steps": [[2, "Run tests", c, iso(st), iso(st)]]}


def flaky_history():
    runs, jobs = [], []
    # Week of 2026-09-28: 6 pushes, 2 flaked (failed, then passed on a re-run). Week of 2026-10-12: 6 clean pushes.
    for i, day in enumerate([0, 1, 2, 3, 3, 3]):
        rid = 100 + i
        if i < 2:
            runs += [jrun(rid, 1, day, "failure", f"t{rid}"), jrun(rid, 2, day, "success", f"t{rid}")]
            jobs += [job(rid * 10, rid, 1, day, "failure"), job(rid * 10 + 1, rid, 2, day, "success")]
        else:
            runs.append(jrun(rid, 1, day, "success", f"t{rid}"))
            jobs.append(job(rid * 10, rid, 1, day, "success"))
    for i, day in enumerate([14, 15, 16, 17, 17, 17]):
        rid = 200 + i
        runs.append(jrun(rid, 1, day, "success", f"t{rid}", secs=600))
        jobs.append(job(rid * 10, rid, 1, day, "success"))
    return {"runs": runs, "jobs": jobs, "tests": []}


def test_ci_trends_count_flakes_and_push_waits_per_week_over_the_kept_history():
    from stackvitals.ci.analyze import analyze
    result = analyze(flaky_history(), NOW, default_branch="main")
    weeks = {w["week"]: w for w in result["weekly"]}
    assert list(weeks)[0] == "2026-09-28" and list(weeks)[-1] == "2026-10-26"  # every week, empty ones too
    assert weeks["2026-09-28"]["job_runs"] == 6 and weeks["2026-09-28"]["flakes"] == 2
    assert weeks["2026-10-05"]["job_runs"] == 0 and weeks["2026-10-05"]["push_median_s"] is None
    # Push waits use the benchmark's own rule: pushes that needed a re-run are left out.
    assert weeks["2026-10-12"]["push_median_s"] == 600 and weeks["2026-09-28"]["push_median_s"] == 300
    from stackvitals.ci.report import render_html
    page = render_html(result, "o/r")
    assert "Flaky share per week" in page and "Push to all checks done" in page
    assert "<td data-v='33.33'>33.33%</td>" in page  # 2 of 6 job runs flaked; one flake in 4,000 runs still shows


def test_each_flaky_job_gets_a_history_page_with_its_runs_and_flakes_marked(tmp_path):
    from stackvitals.ci.action import write_outputs
    from stackvitals.ci.analyze import analyze
    result = analyze(flaky_history(), NOW, default_branch="main")
    (tmp_path / "docs" / "history").mkdir(parents=True)
    old = tmp_path / "docs" / "history" / "job-gone-0123abcd.html"
    old.write_text("stale", encoding="utf-8")
    (tmp_path / "docs" / "history" / "notes.html").write_text("someone else's", encoding="utf-8")
    write_outputs(tmp_path, result, "o/r")
    docs = tmp_path / "docs"
    pages = sorted(p.name for p in (docs / "history").glob("job-*.html"))
    # Only items that are not ok get a page; our old pages go, other files stay.
    assert len(pages) == 1 and not old.exists() and (docs / "history" / "notes.html").exists()
    detail = (docs / "history" / pages[0]).read_text(encoding="utf-8")
    runs = re.search(r"<h2>Runs</h2>.*?</table>", detail, re.S).group(0)
    assert "https://github.com/o/r/actions/runs/100/attempts/1" in runs and runs.count("class='tag flaky'") == 2
    assert runs.count("<tr>") - 1 == 12 and "href='../ci.html'" in detail
    index = (docs / "ci.html").read_text(encoding="utf-8")
    assert f"href='history/{pages[0]}'" in index
    # The public data file stays small: the per-run history is only in the pages.
    assert "history" not in json.loads((docs / "data.json").read_text(encoding="utf-8"))


def test_pages_from_older_results_still_render():
    from test_ci_report import RESULT

    from stackvitals.ci.report import render_html
    from stackvitals.community.report import render_html as community_html
    from stackvitals.flow.report import render_html as flow_html
    assert "Flaky jobs" in render_html(RESULT, "o/r")  # no weekly, no history
    from test_flow_report import RESULT as FLOW
    assert "<nav" in flow_html({k: v for k, v in FLOW.items() if k != "monthly"}, "o/r")
    from test_community_report import result
    assert "<nav" in community_html({**result(), "stars": None}, "o/r")


def test_team_flow_draws_review_times_per_month_from_merged_prs():
    from test_flow_analyze import NOW as FLOW_NOW, at, pr, rv

    from stackvitals.flow.analyze import analyze as flow_analyze
    from stackvitals.flow.report import render_html as flow_html
    merged = [pr(n, st="MERGED", cr=100, mg=60, ev=[["ready", at(100)], rv(90, "bob"), ["merged", at(60), "bob"]])
              for n in range(1, 4)]
    r = flow_analyze({"open": [], "closed": merged}, FLOW_NOW)
    month = r["monthly"][-1]
    assert month["merged"] == 3 and month["pickup_median_s"] == 10 * 3600 and month["cycle_median_s"] == 40 * 3600
    page = flow_html({**r, "monthly": [{"month": "2026-09", "opened": 5, "merged": 4, "pickup_median_s": 7200,
                                        "cycle_median_s": 36000}, month]}, "o/r", pages={"ci.html"})
    assert "Review times per month" in page and "<td data-v='10.0'>10 h</td>" in page and "<td data-v='40.0'>40 h</td>" in page
    assert "PRs opened and merged per month" in page and "href='ci.html'" in page


def test_community_counts_first_answers_and_newcomers_per_quarter_and_draws_stars():
    from test_community_report import NOW as C_NOW, data, result

    from stackvitals.community.analyze import quarterly
    from stackvitals.community.report import render_html as community_html
    prs = data()
    q = quarterly(prs["open"] + prs["closed"], [], C_NOW)
    assert [x["quarter"] for x in q][-1] == "2026 Q4" and len(q) == 4
    for x in q:
        assert set(x) >= {"items", "median_hours", "within_1d", "newcomers"}
    r = {**result(), "stars": {"weeks": [["2026-09-28", 100], ["2026-10-05", 104], ["2026-10-12", 110]], "stars": 110,
                               "gained_12w": None, "growth_12w": None}}
    page = community_html(r, "o/r")
    assert "Stars per week" in page and "<td data-v='110'>110</td>" in page and "First answers per quarter" in page


def test_charts_with_nothing_to_show_are_left_out():
    # Real data (sandbox): no outside PRs and 0 stars drew three empty charts.
    from test_community_report import result

    from stackvitals.community.report import render_html as community_html
    empty = [{"quarter": f"2026 Q{i}", "items": 0, "median_hours": None, "within_1d": None, "newcomers": None if i < 4 else 0}
             for i in range(1, 5)]
    page = community_html({**result(), "quarters": empty,
                           "stars": {"weeks": [["2026-10-11", 0], ["2026-10-18", 0]], "stars": 0}}, "o/r")
    assert "<figure" not in page and "Trends" not in page and "cdnjs" not in page


def test_a_history_page_stays_small_even_for_a_job_that_flakes_all_the_time():
    from stackvitals.ci.report import render_detail
    rows = [[f"2026-{4 + i // 600:02d}-{1 + i % 28:02d}T{i % 24:02d}:00:00Z", 39000000000 + i, 1, True, "retry",
             f"feature/some-long-branch-name-{i}", "pull_request"] for i in range(3600)]  # 180 days, 20 runs a day
    item = {"workflow": ".github/workflows/ci.yml", "job": "test", "state": "flaky", "flake_events": 3600, "runs": 3600}
    page = render_detail("job", ".github/workflows/ci.yml|test", item, rows, {"window_days": 30, "weekly": []}, "o/r")
    assert len(page.encode("utf-8")) < 300_000 and "older" in page


def test_history_pages_are_written_only_for_items_the_dashboard_shows_and_all_are_linked():
    from stackvitals.ci.analyze import analyze
    from stackvitals.ci.report import render_html
    data = flaky_history()
    # A second job that keeps failing on main: listed under "Keeps failing", so its page must be linked there.
    data["runs"] += [jrun(300 + i, 1, 20 + i, "failure", f"t{300 + i}") for i in range(3)]
    data["jobs"] += [job(3000 + i, 300 + i, 1, 20 + i, "failure", name="lint") for i in range(3)]
    result = analyze(data, NOW, default_branch="main")
    states = {j["job"]: j["state"] for j in result["jobs"]}
    assert states["lint"] == "broken"
    shown = {k for k in result["history"]["jobs"]}
    assert shown == {".github/workflows/ci.yml|test", ".github/workflows/ci.yml|lint"}
    page = render_html(result, "o/r")
    assert page.count("href='history/job-") == 2
