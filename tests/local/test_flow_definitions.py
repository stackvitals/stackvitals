"""Team Flow's "first review" and release proxy say how they differ from Delivery's pickup and change failure rate, so the
same word never means two numbers."""
from stackvitals.flow.report import _delivery_lines, stage_note


def test_the_stage_table_explains_first_review_against_delivery_pickup():
    note = stage_note({"delivery.html"})
    assert "first comment" in note and "delivery.html" in note
    assert "delivery.html" not in stage_note(set())


def test_the_release_proxy_points_to_delivery():
    r = {"window_days": 90, "delivery": {"source": "releases", "releases": 4, "per_week": 0.3, "lead_time_median_s": 3600,
                                         "recovery_median_s": None, "change_fail": {"failed": 1, "of": 4}}}
    assert "Delivery" in _delivery_lines(r)[-1]
