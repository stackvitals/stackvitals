"""The accuracy cards and the rules they measured stay in step: the published page is rebuilt from the cards' results, and
the frozen labels give the same numbers under the rules the code uses now."""
import csv
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "bench" / "accuracy"


def test_the_accuracy_page_and_the_apps_table_match_the_cards():
    out = subprocess.run([sys.executable, str(BENCH / "summary.py"), "--check"], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr


def test_the_frozen_masking_labels_give_the_card_under_todays_safe_to_rerun_rule():
    # 15 of 34 "known flaky" pull-request failures were caused by the change under the old rule; loosening SAFE_FLAKES
    # must fail here until the card is measured again.
    from stackvitals.ci.feedback import SAFE_FLAKES
    rows = list(csv.DictReader((BENCH / "flaky" / "masking-labels.csv").open(encoding="utf-8")))
    card = json.loads((BENCH / "flaky" / "masking-results.json").read_text(encoding="utf-8"))
    safe = [r for r in rows if int(r["flakes_before"]) >= SAFE_FLAKES and r["step_matches"] == "True"]
    sure = [r for r in safe if r["caused_by_change"] != "unclear"]
    assert card["safe_flakes"] == SAFE_FLAKES
    assert (len(sure), sum(r["caused_by_change"] == "yes" for r in sure)) == (card["new_rule"]["n"], card["new_rule"]["caused_by_change"])


def test_the_deployment_source_card_counts_what_its_frozen_labels_say():
    rows = list(csv.DictReader((BENCH / "dora" / "sources-labels.csv").open(encoding="utf-8")))
    card = json.loads((BENCH / "dora" / "sources-results.json").read_text(encoding="utf-8"))
    for rule in ("stackvitals", "devlake", "merges"):
        assert sum(r[f"{rule}_right"] == "True" for r in rows) == round(card["source_right"][rule]["share"] * len(rows))


def test_the_flaky_cards_event_precision_rebuilds_from_its_frozen_labels():
    # The card's headline from items.csv alone: flagged flakes neither caused by the change nor a side effect of another job.
    rows = list(csv.DictReader((BENCH / "flaky" / "items.csv").open(encoding="utf-8")))
    card = json.loads((BENCH / "flaky" / "card.json").read_text(encoding="utf-8"))["event_precision"]
    sure = [r for r in rows if r["sample"] == "flagged" and r["caused_by_change"] != "unclear"]
    right = sum(r["caused_by_change"] == "no" and r["own_failure"] == "yes" for r in sure)
    assert (len(sure), round(right / len(sure), 4)) == (card["n"], card["share"])


LABELLED = {"flaky": ("flaky", "flaky"), "masking": ("flaky", "masking"), "community-main": ("community", "main"),
            "community-validation": ("community", "validation"), "dora": ("dora", "sources")}


def test_every_labelled_card_publishes_both_labellers_and_every_ruling_without_quoted_text():
    # Two model families label each sample; a card that drops one labeller's labels or the rulings hides how much they disagree.
    for folder, name in LABELLED.values():
        gemini = BENCH / folder / f"labels-gemini-{name}.csv"
        rulings = BENCH / folder / f"adjudication-{name}.csv"
        agreement = json.loads((BENCH / folder / f"agreement-gemini-{name}.json").read_text(encoding="utf-8"))
        assert gemini.exists() and rulings.exists() and agreement["fields"]
        assert "evidence" not in gemini.read_text(encoding="utf-8").splitlines()[0]
        for row in csv.DictReader(rulings.open(encoding="utf-8")):
            assert row["winner"] in ("first", "second", "neither", "undecided") and len(row["reason"]) <= 200


def test_the_label_sensitivity_matches_each_cards_published_headline():
    # The adjudicated column must be the number the card shows; the other columns show how far each labeller moves it.
    sens = json.loads((BENCH / "label-sensitivity.json").read_text(encoding="utf-8"))
    flaky = json.loads((BENCH / "flaky" / "card.json").read_text(encoding="utf-8"))
    dora = json.loads((BENCH / "dora" / "sources-results.json").read_text(encoding="utf-8"))
    community = json.loads((BENCH / "community" / "labels-results.json").read_text(encoding="utf-8"))["validation"]
    for card in ("flaky", "dora", "community"):
        assert set(sens[card]) == {"claude", "gemini", "adjudicated"}
    assert sens["flaky"]["adjudicated"]["event_precision"] == flaky["event_precision"]["share"]
    assert sens["dora"]["adjudicated"]["stackvitals"] == dora["source_right"]["stackvitals"]["share"]
    assert sens["community"]["adjudicated"]["drive_bys_counted_by_issue_metrics"] == community["drive_by_counted_by_issue_metrics"]["share"]


def test_the_registry_names_every_rule_a_card_rests_on():
    registry = json.loads((BENCH / "registry.json").read_text(encoding="utf-8"))
    cards = {r["card"] for r in registry["rules"]}
    assert {"flaky", "dora", "community", "uncertainty", "ai"} <= cards
    for rule in registry["rules"]:
        assert rule["held_out"] and all({"date", "from", "why", "effect"} <= set(v) for v in rule["revisions"])


def test_the_history_check_needs_no_labeller_and_agrees_with_the_card():
    # The history check's verdicts stay well formed, and a flagged flake (it passed on identical code) is never called
    # caused: if that ever happens, the check itself changed and the card must be measured again.
    nat = json.loads((BENCH / "flaky" / "natural-results.json").read_text(encoding="utf-8"))
    assert nat["by_sample"]["flagged"].get("caused", 0) == 0 and nat["by_sample"]["flagged"]["not caused"] > 0
    for v in nat["verdicts"].values():
        assert v["verdict"] in ("caused", "not caused", "undetermined")
