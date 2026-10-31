"""The pulse over time: each week's counts kept (never who answered), a share shown only for a week with 5 or more
answers to that question, and each question beside the number it explains."""
import json

from stackvitals.core import pulse


def counts(yes, no, mixed=0):
    return {"flow": {"yes": yes, "no": no, "mixed": mixed}, "friction": {"yes": 1, "no": 1, "mixed": 0},
            "satisfaction": {"yes": 0, "no": 0, "mixed": 0}}


def test_each_week_is_kept_once_and_a_year_at_most(tmp_path):
    (tmp_path / "docs").mkdir()
    pulse.record(tmp_path, "2026-W40", counts(4, 1))
    pulse.record(tmp_path, "2026-W40", counts(5, 1))  # the same week again replaces it
    pulse.record(tmp_path, "2026-W41", counts(2, 3))
    got = json.loads((tmp_path / "docs" / "pulse.json").read_text(encoding="utf-8"))
    assert [w["week"] for w in got["weeks"]] == ["2026-W40", "2026-W41"] and got["weeks"][0]["flow"]["yes"] == 5
    assert "login" not in json.dumps(got) and "user" not in json.dumps(got)
    for i in range(60):
        pulse.record(tmp_path, f"2027-W{i:02d}", counts(1, 1))
    assert len(json.loads((tmp_path / "docs" / "pulse.json").read_text(encoding="utf-8"))["weeks"]) == pulse.KEEP_WEEKS


def test_a_share_is_shown_only_with_enough_answers():
    weeks = [{"week": "2026-W40", **counts(4, 1)}, {"week": "2026-W41", **counts(1, 1)}]
    trend = pulse.trend(weeks)
    flow = trend["flow"]
    assert flow[0] == {"week": "2026-W40", "answers": 5, "yes_share": 0.8}
    assert flow[1] == {"week": "2026-W41", "answers": 2, "yes_share": None}  # too few to show a share
    assert trend["satisfaction"][0]["answers"] == 0


def test_each_question_names_the_number_it_sits_beside():
    assert pulse.BESIDE == {"flow": "pickup", "friction": "first_try", "satisfaction": "deployments"}
