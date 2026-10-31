"""How well the flake kinds (`ci/feedback.py`, flake_kind) match the labelled causes: for failures the change didn't
cause, how often each kind agrees with the label's cause, and how many flakes get a kind at all.

    python bench/accuracy/flaky/kinds.py --home <final work folder>

Reads the sample's items.jsonl and labels.jsonl and masking's asof-items.jsonl and asof-labels.jsonl; writes
kinds-results.json beside this script (counts only).
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from stackvitals.ci.feedback import flake_kind
from stackvitals.core.stats import wilson

# The label causes each kind stands for (codebook.md): timing waits are the test's own, or a step running out of time.
MEANS = {"infrastructure": {"infrastructure"}, "network": {"network"}, "concurrency": {"product_race", "test"},
         "timing": {"test", "timeout"}}


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.exists() else []


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--home", type=Path, required=True)
    args = ap.parse_args(argv)
    items = [i for i in _jsonl(args.home / "items.jsonl") if i.get("sample") != "none"]
    labels = {r["id"]: r for r in _jsonl(args.home / "labels.jsonl")}
    rows = [(i, labels[n]) for n, i in enumerate(items, 1)]
    asof = {r["id"]: r for r in _jsonl(args.home / "asof-labels.jsonl")}
    rows += [(x, asof[1000 + n]) for n, x in enumerate(_jsonl(args.home / "asof-items.jsonl"), 1)]
    flakes = [(flake_kind(i.get("log")), lab) for i, lab in rows if lab["caused_by_change"] == "no"]
    caused = [flake_kind(i.get("log")) for i, lab in rows if lab["caused_by_change"] == "yes"]
    out = {"flakes": len(flakes), "flakes_with_a_kind": sum(k is not None for k, _l in flakes), "kinds": {}}
    for name, means in MEANS.items():
        got = [lab for k, lab in flakes if k == name]
        right = sum(lab["cause"] in means for lab in got)
        lo, hi = wilson(right, len(got))
        out["kinds"][name] = {"n": len(got), "matches_label": right, "low": round(lo, 4), "high": round(hi, 4),
                              "labels": dict(Counter(lab["cause"] for lab in got).most_common()),
                              "on_changes_that_caused_it": caused.count(name)}
    (Path(__file__).with_name("kinds-results.json")).write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
