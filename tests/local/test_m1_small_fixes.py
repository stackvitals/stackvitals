"""Small trust fixes from the code audit: `ui` opens any page, local Delivery finds Community's issues where `community
report` keeps them, the job summary starts with what to fix first, and Community stamps its numbers in ISO time."""
import json
import subprocess
from datetime import datetime, timezone

from stackvitals.core.uicli import first_page
from stackvitals.core.workspace import run_job

NOW = datetime(2026, 10, 21, 9, tzinfo=timezone.utc)


def test_ui_opens_a_portal_only_branch(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    assert first_page(docs) is None
    (docs / "portal.html").write_text("x", encoding="utf-8")
    assert first_page(docs) == "portal.html"
    (docs / "flow.html").write_text("x", encoding="utf-8")
    assert first_page(docs) == "flow.html"


def test_local_delivery_reads_community_issues_where_the_community_report_keeps_them(tmp_path):
    from stackvitals.core.services import local_issues
    from stackvitals.flow.store import FlowStore
    store = FlowStore(tmp_path / "community" / "o__r", "issues")
    store.save_open({5: {"n": 5, "cr": "2026-10-01T00:00:00Z", "lb": ["incident"]}})
    assert [i["n"] for i in local_issues(tmp_path, "o/r")] == [5]


def test_the_job_summary_starts_with_what_to_fix_first(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    env = {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": bare.as_uri(),
           "RUNNER_TEMP": str(tmp_path / "tmp")}
    order = []

    def module(ws):
        ws.after_commit(lambda: order.append("CI Health"), "CI Health")

    def insights(ws):
        ws.after_commit(lambda: order.append("Insights"), "Insights", first=True)
    run_job(env, [("CI Health", module), ("Insights", insights)], NOW)
    assert order == ["Insights", "CI Health"]


def test_community_stamps_its_numbers_in_iso_time_and_shows_them_plainly():
    from stackvitals.community.build import build
    from stackvitals.community.report import render_html, render_text
    result = build({"open": [], "closed": []}, {"open": [], "closed": []}, None, None, {}, NOW)
    assert result["generated"] == "2026-10-21T09:00:00Z"
    assert "updated 2026-10-21 09:00 UTC" in render_text(result, "o/r")
    assert "Updated 2026-10-21 09:00 UTC" in render_html(result, "o/r")
