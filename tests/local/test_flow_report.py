from datetime import datetime, timezone

from stackvitals.flow.report import render_html, render_markdown, render_text

NOW = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
STAGE = {"median_s": 5 * 3600, "p90_s": 30 * 3600, "n": 40}
EVIL = '<img src=x onerror=alert(1)> | `x` [y](z)'
RESULT = {
    "generated": "2026-10-17T12:00:00Z", "window_days": 90, "open": 12, "drafts": 2, "merged": 40, "closed_unmerged": 9,
    "stages": {"pickup": STAGE, "review": STAGE, "merge": STAGE, "cycle": STAGE}, "merged_without_review": 5,
    "groups": {"insider": {"merged": 30, "closed_unmerged": 1, "merge_rate": 0.97, "pickup": {"median_s": 600, "p90_s": 900, "n": 20}},
               "outsider": {"merged": 10, "closed_unmerged": 8, "merge_rate": 0.56, "pickup": {"median_s": 96 * 3600, "p90_s": None, "n": 10}}},
    "baselines": {"pickup": 50 * 3600, "merge": 3600, "author": 8 * 3600}, "stale": 3,
    "queue": [{"n": 7, "title": EVIL, "author": "alice", "outsider": True, "actor": "reviewers", "who": ["carol", "team:core"],
               "why": "review requested", "since": "2026-10-15T12:00:00Z", "step": "pickup", "waiting_s": 48 * 3600,
               "usual_s": 20 * 3600, "stale": False, "slow": True}],
    "load": [{"reviewer": "carol", "open_requests": 3, "oldest_since": "2026-10-15T12:00:00Z"}],
    "monthly": [{"month": "2026-10", "opened": 20, "merged": 15, "pickup_median_s": 3600}], "bots": {"open": 1, "closed": 4},
    "responders": [{"reviewer": "carol", "median_s": 7200, "n": 9}]}


def test_reports_show_the_queue_who_acts_next_and_how_outsiders_fare():
    for text in (render_text(RESULT, "o/r"), render_markdown(RESULT, "o/r"), render_html(RESULT, "o/r")):
        assert "#7" in text and "carol" in text and "2d 0h" in text and "96h" in text.replace("4d 0h", "96h")
        assert "3 stale" in text


def test_names_and_titles_from_prs_are_escaped_everywhere():
    assert "<img" not in render_html(RESULT, "o/r") and "<img" not in render_markdown(RESULT, "o/r")


def test_peoples_answer_speed_appears_only_in_the_private_text_view():
    assert "2h 0m" not in render_html(RESULT, "o/r").split("Answer times")[0] and "Answer times" not in render_html(RESULT, "o/r")
    assert "Answer times" not in render_markdown(RESULT, "o/r")
    assert "Answer times" in render_text(RESULT, "o/r")


M2 = RESULT | {
    "queue": [RESULT["queue"][0] | {"actor": "maintainers", "who": [], "why": "ready, but nobody was asked to review", "step": "pickup",
                                    "suggested": [{"login": "dana", "score": 1.0, "why": "wrote 6 and reviewed 0 merged PRs in src/db"}]}],
    "knowledge": {"areas": [{"area": "src/db", "prs": 7, "owner": "dana", "share": 0.95, "single_owner": True, "owner_quiet_days": 4},
                            {"area": "lib/old", "prs": 4, "owner": "hal", "share": 1.0, "single_owner": True, "owner_quiet_days": 200}],
                  "hotspots": [{"area": "src/db", "prs_90d": 6, "prs": 7}]},
    "delivery": {"source": "releases", "releases": 8, "per_week": 0.62, "lead_time_median_s": 3 * 86400,
                 "change_fail": {"failed": 1, "of": 8, "rate": 0.125, "proxy": True}, "recovery_median_s": 86400}}


def test_reports_show_suggested_reviewers_the_knowledge_map_and_delivery():
    for text in (render_text(M2, "o/r"), render_markdown(M2, "o/r"), render_html(M2, "o/r")):
        assert "dana" in text and "Suggested" in text or "suggested" in text
        assert "src/db" in text and "lib/old" in text and "200 days" in text
        assert "8 releases" in text and "1 of 8" in text and "proxy" in text


M3 = M2 | {
    "queue": [M2["queue"][0] | {"gaps": [{"what": "tests", "why": "84% of merged PRs in src/db include test files"}]}],
    "habits": {"scope": "whole repo", "merged_prs": 300, "include": {"tests": 0.84, "changelog": 0.01, "docs": 0.08},
               "size": {"median_lines": 170, "p75_lines": 400, "p90_lines": 900},
               "asks": [{"ask": "tests", "share": 0.1, "prs": 60}]}}


def test_reports_show_what_merged_prs_usually_include_and_each_prs_gaps():
    for text in (render_text(M3, "o/r"), render_markdown(M3, "o/r"), render_html(M3, "o/r")):
        assert "84% of merged PRs in src/db include test files" in text
        assert "84%" in text and "170 lines" in text and "tests (10%" in text


def test_reports_compare_review_flow_with_similar_repos():
    peers = {"group": "Python repos", "repos": 300, "metrics": [
        {"key": "first_review_hours", "name": "First maintainer review after", "kind": "hours", "you": 2.0, "typical": 12.0,
         "place": "faster than about 80%", "repos": 300},
        {"key": "outsider_merge_rate", "name": "Outside contributors' PRs merged", "kind": "share", "you": 0.5, "typical": 0.6,
         "place": "below about 60%", "repos": 280}]}
    for text in (render_text(M3 | {"peers": peers}, "o/r"), render_markdown(M3 | {"peers": peers}, "o/r"),
                 render_html(M3 | {"peers": peers}, "o/r")):
        assert "Compared with 300 Python repos" in text and "2h 0m (typical 12h 0m), faster than about 80%" in text
        assert "50% (typical 60%), below about 60%" in text
