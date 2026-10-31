"""How the "maybe flaky" signatures (`ci/feedback.py`, FLAKY_LOOK) do on the labelled failures: of the logs they match
(and the outside-failure signatures don't), how many the change caused, overall and among failures of jobs that had
never flaked, where StackVitals would otherwise say "likely from this change".

    python bench/accuracy/flaky/maybe.py --home <work folder>

Reads the sample's items.jsonl and labels.jsonl and masking's asof-items.jsonl and asof-labels.jsonl; writes
maybe-results.json beside this script (counts only).
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fair import by_repo  # noqa: E402
from stackvitals.ci.feedback import flaky_signature, outside_signature
from stackvitals.core.stats import wilson


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.exists() else []


def _caused(rows: list) -> dict:
    c = Counter(lab["caused_by_change"] for _i, lab in rows)
    lo, hi = wilson(c["yes"], c["yes"] + c["no"])
    return {"n": len(rows), "caused": c["yes"], "not_caused": c["no"], "unclear": c["unclear"],
            "caused_low": round(lo, 4), "caused_high": round(hi, 4)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--home", type=Path, required=True)
    args = ap.parse_args(argv)
    items = [i for i in _jsonl(args.home / "items.jsonl") if i.get("sample") != "none"]
    labels = {r["id"]: r for r in _jsonl(args.home / "labels.jsonl")}
    rows = [(i, labels[n]) for n, i in enumerate(items, 1)]
    asof = {r["id"]: r for r in _jsonl(args.home / "asof-labels.jsonl")}
    rows += [(x, asof[1000 + n]) for n, x in enumerate(_jsonl(args.home / "asof-items.jsonl"), 1)]
    matched = [(i, lab) for i, lab in rows if flaky_signature(i.get("log")) and not outside_signature(i.get("log"))]
    never = [(i, lab) for i, lab in rows if i.get("sample") == "unflagged_failure"]
    out = {"logs": len(rows), "matched": _caused(matched),
           "never_flaked": {"all": _caused(never), "matched": _caused([x for x in never if x in matched])},
           "signatures": dict(Counter(flaky_signature(i.get("log")).lower() for i, _l in matched).most_common()),
           "by_repo": by_repo([(i["repo"], lab["caused_by_change"] == "yes") for i, lab in never
                               if (i, lab) in matched and lab["caused_by_change"] in ("yes", "no")])}
    (Path(__file__).with_name("maybe-results.json")).write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
