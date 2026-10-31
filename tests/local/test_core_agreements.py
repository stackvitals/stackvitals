"""Working agreements (Swarmia's team rules): off until a team sets them; then every pull request of the last 14 days that
broke one is listed (open ones still waiting count too), with a weekly series for the app's "how often would this have
been broken" preview, and the Delivery page shows them."""
from test_core_delivery import NOW, pr, review

from stackvitals.core import agreements, delivery
from stackvitals.core.config import parse


def rows(prs):
    return [(p, delivery.phases(p, None), None) for p in prs]


MERGED = [pr(1, cr=100, mg=60, ev=[review(95)], add=30, dele=5),          # picked up in 5 h, merged in 40 h, small
          pr(2, cr=200, mg=40, ev=[review(150)], add=800, dele=100),     # picked up in 50 h, merged in 160 h, big
          pr(3, cr=90, mg=80)]                                           # merged without any review
OPEN = [pr(4, cr=72)]                                                   # waiting 72 h with no answer


def test_nothing_is_checked_until_a_team_sets_an_agreement():
    assert agreements.check(rows(MERGED), OPEN, parse("")[0]["agreements"], NOW) is None


def test_exceptions_of_the_last_two_weeks_with_open_prs_still_waiting():
    cfg = parse("[agreements]\nreview_within_hours = 24\nmax_pr_lines = 400\nreview_before_merge = true\n")[0]
    out = agreements.check(rows(MERGED), OPEN, cfg["agreements"], NOW)
    broken = {(e["pr"], e["rule"]) for e in out["exceptions"]}
    # PR 3 merged 10 h after opening with no review: by LinearB's definition its pickup is those 10 h, so it breaks only
    # "review before merge".
    assert broken == {(2, "review_within_hours"), (2, "max_pr_lines"), (3, "review_before_merge"), (4, "review_within_hours")}
    assert out["counts"]["max_pr_lines"] == 1 and out["merged"] == 3 and out["window_days"] == 14
    assert next(e for e in out["exceptions"] if e["pr"] == 4)["open"] is True
    assert len(out["weekly"]["max_pr_lines"]) == 13 and out["weekly"]["max_pr_lines"][-1][1] == 1


def test_the_delivery_page_lists_them():
    from stackvitals.core.delivery_report import render_html
    cfg = parse("[agreements]\nmax_pr_lines = 400\n")[0]
    out = delivery.build({"open": OPEN, "closed": MERGED}, {"default_branch": "main"}, {"runs": [], "jobs": []}, [], NOW, 90, cfg)
    assert out["agreements"]["counts"]["max_pr_lines"] == 1
    page = render_html({**out, "generated": "2026-10-20T12:00:00Z", "peers": None}, "o/r")
    assert "Working agreements" in page and "PRs under 400 lines" in page


def test_a_bot_comment_or_the_authors_own_does_not_count_as_an_answer():
    """Found on the sandbox: open PRs carrying StackVitals' own CI comment were not counted as waiting."""
    from test_core_delivery import comment
    waiting = pr(5, cr=72, cm=[comment(70, "github-actions[bot]", "Bot"), comment(60, "amy")])
    out = agreements.check([], [waiting], parse("[agreements]\nreview_within_hours = 24\n")[0]["agreements"], NOW)
    assert [(e["pr"], e["open"]) for e in out["exceptions"]] == [(5, True)]
