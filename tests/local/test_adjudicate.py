import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bench" / "accuracy"))

from adjudicate import apply, packets  # noqa: E402


def _setup():
    items = {1: {"id": 1, "text": "same here"}, 2: {"id": 2, "text": "try v2"}, 3: {"id": 3, "text": "fixed in #9"}}
    first = {1: {"kind": "drive_by"}, 2: {"kind": "peer_help"}, 3: {"kind": "project_answer"}}
    second = {1: {"kind": "peer_help"}, 2: {"kind": "peer_help"}, 3: {"kind": "drive_by"}}
    return items, first, second


def test_packets_hold_only_disagreements_and_hide_who_said_what():
    items, first, second = _setup()
    out = packets(items, first, second, ["kind"], seed=3)
    assert [p["id"] for p in out] == [1, 3]
    for p in out:
        assert set(p["labels"]) == {"A", "B"} and "claude" not in json.dumps(p).lower()
        assert sorted(p["labels"].values()) == sorted([first[p["id"]]["kind"], second[p["id"]]["kind"]])
        assert p["item"] == items[p["id"]] and p["field"] == "kind"


def test_apply_maps_blind_picks_back_and_counts_who_was_right(tmp_path):
    items, first, second = _setup()
    out = packets(items, first, second, ["kind"], seed=3)
    decisions = [{"id": p["id"], "field": "kind", "pick": next(k for k, v in p["labels"].items() if v == first[p["id"]]["kind"]),
                  "label": first[p["id"]]["kind"], "reason": "matches the rule"} for p in out]
    decisions[1] |= {"pick": "neither", "label": "peer_help", "reason": "a user's workaround"}
    path = tmp_path / "adjudication.csv"
    final, summary = apply(out, decisions, first, second, path)
    assert final[1]["kind"] == "drive_by" and final[3]["kind"] == "peer_help" and final[2]["kind"] == "peer_help"
    assert summary["kind"] == {"disagreements": 2, "first": 1, "second": 0, "neither": 1, "undecided": 0}
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert [r["winner"] for r in rows] == ["first", "neither"] and "same here" not in path.read_text(encoding="utf-8")


def test_an_undecided_item_keeps_the_first_label():
    items, first, second = _setup()
    out = packets(items, first, second, ["kind"], seed=3)
    final, summary = apply(out, [], first, second, None)
    assert final[1]["kind"] == "drive_by" and summary["kind"]["undecided"] == 2


def test_final_file_keeps_the_item_id_even_when_labels_carry_their_own():
    import json

    from adjudicate import final_lines
    row = json.loads(final_lines({7: {"id": "7", "kind": "a"}}))
    assert row == {"id": 7, "kind": "a"}
