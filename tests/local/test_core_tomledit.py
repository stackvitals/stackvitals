"""Settings changes from the app become small edits of `.github/stackvitals.toml`: people's comments and layout stay, a
missing table is added, a value back to its default is removed, and a file it can't edit safely is refused, never
rewritten blindly."""
import pytest

from stackvitals.core import config
from stackvitals.core.tomledit import EditError, apply

FILE = """# our team's StackVitals settings
[alerts]
pickup_p75_hours = 4   # LinearB's good band
channels = ["webhook"]

[ci.quarantine]
always = [
  "tests/a.py::test_x",
]
"""


def test_a_value_is_replaced_in_place_and_comments_stay():
    out = apply(FILE, {"alerts.pickup_p75_hours": 6})
    assert "pickup_p75_hours = 6" in out and "# our team's StackVitals settings" in out and "channels = [\"webhook\"]" in out
    assert config.parse(out)[0]["alerts"]["pickup_p75_hours"] == 6.0


def test_a_multi_line_list_is_replaced_whole():
    out = apply(FILE, {"ci.quarantine.always": ["tests/b.py::test_y"]})
    assert config.parse(out)[0]["ci"]["quarantine"]["always"] == ["tests/b.py::test_y"]
    assert "tests/a.py::test_x" not in out


def test_a_missing_key_and_a_missing_table_are_added():
    out = apply(FILE, {"alerts.review_p75_hours": 20, "automation.issues": True, "ci.monitors.broken.streak": 4})
    cfg = config.parse(out)[0]
    assert cfg["alerts"]["review_p75_hours"] == 20.0 and cfg["automation"]["issues"] is True
    assert cfg["ci"]["monitors"]["broken"]["streak"] == 4
    assert apply(None, {"alerts.channels": ["webhook", "issue"]}).strip() == '[alerts]\nchannels = ["webhook", "issue"]'


def test_none_removes_a_key_so_its_default_applies():
    out = apply(FILE, {"alerts.pickup_p75_hours": None})
    assert "pickup_p75_hours" not in out and config.parse(out)[0]["alerts"]["pickup_p75_hours"] == 4.0


def test_maps_are_written_as_their_own_table():
    out = apply(FILE, {"ci.mute": {"tests/net.py::*": "2026-12-31"}, "identity.teams": {"web": ["amy", "bob"]}})
    cfg = config.parse(out)[0]
    assert cfg["ci"]["mute"] == {"tests/net.py::*": "2026-12-31"} and cfg["identity"]["teams"] == {"web": ["amy", "bob"]}


def test_unknown_keys_and_bad_values_are_refused():
    with pytest.raises(EditError):
        apply(FILE, {"alerts.nonsense": 1})
    with pytest.raises(EditError):
        apply(FILE, {"alerts.pickup_p75_hours": -3})
    with pytest.raises(EditError):
        apply(FILE, {"delivery.deploy_workflow": "(unclosed"})


def test_a_file_written_in_another_layout_is_refused_not_broken():
    dotted = "[ci]\nmonitors.broken.streak = 5\n"
    with pytest.raises(EditError):
        apply(dotted, {"ci.monitors.broken.streak": 4})
