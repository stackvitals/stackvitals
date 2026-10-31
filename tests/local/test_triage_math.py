import math
import random

from mergescout.signals.triage_math import (FEATURES, buckets, calibration, explain, fit, predict)


def test_inputs_become_plain_buckets():
    b = buckets(here_merged=4, lines=120, linked_issue=True, first_timer=False, repo_rate=0.25)
    assert b == {"history": "3+", "size": "50-199", "issue": "yes", "repo_rate": "<30%"}
    assert buckets(3, 5000, False, False, None)["repo_rate"] == "unknown"
    # One input for the author's past here, so "first contribution" and "merged before" can't overlap.
    assert [buckets(m, 5, False, ft, None)["history"] for m, ft in ((0, True), (0, False), (2, False))] == ["new", "tried", "1-2"]


def synthetic(n=6000, seed=1):
    # Truth: experienced authors and welcoming repos merge more; huge PRs merge less.
    rng = random.Random(seed)
    rows = []
    for _ in range(n):
        f = {name: rng.choice(values) for name, values in FEATURES.items()}
        # Effects add up on the logistic scale, the model's own shape, so calibration tests the fitting code.
        z = -0.3 + (1.2 if f["history"] == "3+" else 0) - (0.4 if f["history"] == "tried" else 0) \
            - (1.1 if f["repo_rate"] == "<30%" else 0) + (0.9 if f["repo_rate"] == "80%+" else 0) - (0.7 if f["size"] == "1000+" else 0)
        rows.append({**f, "merged": rng.random() < 1 / (1 + math.exp(-z)), "repo": rng.randrange(400)})
    return rows


def test_the_model_learns_the_right_directions_and_is_calibrated_on_unseen_rows():
    train, test = synthetic(seed=1), synthetic(seed=2)
    model = fit(train)
    w = model["coef"]
    assert w["history=3+"] > 0.5 and w["repo_rate=<30%"] < -0.5 and w["size=1000+"] < 0
    cal = calibration(model, test)
    assert all(abs(d["predicted"] - d["actual"]) <= 0.05 for d in cal["deciles"] if d["n"] >= 200)
    assert cal["brier"] < cal["baseline_brier"]


def test_a_score_comes_with_plain_reasons():
    model = fit(synthetic())
    feats = {"history": "3+", "size": "1000+", "issue": "no", "repo_rate": "<30%"}
    p = predict(model, feats)
    reasons = explain(model, feats)
    assert 0 < p < 1 and len(reasons) <= 3
    assert any("in this repo already" in r["why"] and r["effect"] == "raises" for r in reasons)
    assert any("this repo" in r["why"] and r["effect"] == "lowers" for r in reasons)


def test_being_new_is_the_reference_so_it_is_never_given_as_a_reason():
    # Real crawl: first-timers merge more than people whose earlier PRs here all failed, but less than past contributors.
    model = fit(synthetic())
    new = explain(model, {"history": "new", "size": "<50", "issue": "no", "repo_rate": "unknown"})
    tried = explain(model, {"history": "tried", "size": "<50", "issue": "no", "repo_rate": "unknown"})
    assert not any("first" in r["why"] for r in new)
    assert tried and tried[0]["why"] == "has opened PRs here before, none merged yet" and tried[0]["effect"] == "lowers"
