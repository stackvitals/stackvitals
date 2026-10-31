"""How the outside-failure log signatures (`ci/feedback.py`, OUTSIDE) do on the labelled failures: of the logs they match,
how many the change caused, and how many network and infrastructure failures they find.

    python bench/accuracy/flaky/outside.py --home <work folder>

Reads the sample's items.jsonl and labels.jsonl and masking's asof-items.jsonl and asof-labels.jsonl; writes
outside-results.json beside this script (counts only).
"""
import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fair import by_repo  # noqa: E402
from stackvitals.ci.feedback import outside_signature
from stackvitals.core.stats import wilson


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.exists() else []


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--home", type=Path, required=True)
    args = ap.parse_args(argv)
    items = [i for i in _jsonl(args.home / "items.jsonl") if i.get("sample") != "none"]
    labels = {r["id"]: r for r in _jsonl(args.home / "labels.jsonl")}
    rows = [(i, labels[n]) for n, i in enumerate(items, 1)]
    asof_labels = {r["id"]: r for r in _jsonl(args.home / "asof-labels.jsonl")}
    rows += [(x, asof_labels[1000 + n]) for n, x in enumerate(_jsonl(args.home / "asof-items.jsonl"), 1)]
    matched = [(i, lab, sig) for i, lab in rows if (sig := outside_signature(i.get("log")))]
    caused = Counter(lab["caused_by_change"] for _i, lab, _s in matched)
    sure = caused["yes"] + caused["no"]
    lo, hi = wilson(caused["no"], sure)
    infra = [lab for _i, lab in rows if lab["caused_by_change"] == "no" and lab["cause"] in ("network", "infrastructure")]
    missed = [(i, lab) for i, lab in rows if i.get("sample") == "unflagged_failure" and lab["caused_by_change"] == "no"
              and lab["cause"] in ("test", "product_race", "infrastructure", "network", "timeout")]
    out = {"logs": len(rows), "matched": len(matched),
           "not_caused_by_change": {"n": sure, "share": round(caused["no"] / sure, 4) if sure else None, "low": round(lo, 4), "high": round(hi, 4)},
           "caused_by_change": caused["yes"], "unclear": caused["unclear"],
           "network_or_infrastructure_found": sum(1 for _i, lab, _s in matched if lab["caused_by_change"] == "no"
                                                  and lab["cause"] in ("network", "infrastructure")),
           "network_or_infrastructure": len(infra),
           "detector_misses_found": sum(1 for i, lab in missed if outside_signature(i.get("log"))), "detector_misses": len(missed),
           "by_repo": by_repo([(i["repo"], lab["caused_by_change"] == "yes") for i, lab, _s in matched
                               if lab["caused_by_change"] in ("yes", "no")]),
           "signatures": dict(Counter(s.lower() for _i, _l, s in matched).most_common()),
           "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    (Path(__file__).with_name("outside-results.json")).write_text(json.dumps(out, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
