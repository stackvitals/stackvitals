"""Settle the items two labellers disagree on, blind: the adjudicator sees the item and the two labels as A and B in a
seeded random order, never which labeller gave which, and may pick a third label.

    python bench/accuracy/adjudicate.py flaky --work bench/accuracy/.work/flaky --packets    # write packets-NN.jsonl
    python bench/accuracy/adjudicate.py flaky --work bench/accuracy/.work/flaky --apply      # read decisions-NN.jsonl

--apply writes <card>/adjudication-<name>.csv (ids, labels and reasons, no item text) and final/<card>.jsonl beside the
work folder: the agreed label where both agree, the adjudicated one where they don't.
"""
import argparse
import csv
import json
import random
import sys
from pathlib import Path

from labeller import CARDS, HERE, Cache, _hash, _short, codebook, first_labels, load_items, second_labels

PART = 40


def packets(items: dict, first: dict, second: dict, fields: list[str], seed: int = 13) -> list[dict]:
    """One packet per (item, field) the two labellers disagree on, with the labels shown as A and B in random order."""
    rng = random.Random(seed)
    out = []
    for item_id in sorted(first, key=str):
        if item_id not in second or item_id not in items:
            continue
        for field in fields:
            a, b = first[item_id].get(field), second[item_id].get(field)
            if a is None or b is None or str(a) == str(b):
                continue
            flip = rng.random() < 0.5
            out.append({"id": item_id, "field": field, "item": _short(items[item_id], 6000),
                        "labels": {"A": str(b if flip else a), "B": str(a if flip else b)}, "_first": "B" if flip else "A"})
    return out


def apply(packs: list[dict], decisions: list[dict], first: dict, second: dict, out_csv: Path | None) -> tuple[dict, dict]:
    """Final labels and, per field, how many disagreements each labeller won (or neither, or undecided)."""
    final = {k: dict(v) for k, v in first.items()}
    got = {(d["id"], d["field"]): d for d in decisions}
    summary, rows = {}, []
    for p in packs:
        s = summary.setdefault(p["field"], {"disagreements": 0, "first": 0, "second": 0, "neither": 0, "undecided": 0})
        s["disagreements"] += 1
        d = got.get((p["id"], p["field"]))
        a, b = str(first[p["id"]][p["field"]]), str(second[p["id"]][p["field"]])
        if not d:
            s["undecided"] += 1
            winner, label, reason = "undecided", a, ""
        else:
            label = str(d.get("label") or p["labels"].get(d.get("pick"), ""))
            winner = "first" if label == a else "second" if label == b else "neither"
            s[winner] += 1
            reason = str(d.get("reason") or "")[:200]
            final[p["id"]][p["field"]] = label
        rows.append([p["id"], p["field"], a, b, label, winner, reason])
    if out_csv:
        with out_csv.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["id", "field", "first", "second", "final", "winner", "reason"])
            w.writerows(rows)
    return final, summary


def final_lines(final: dict) -> str:
    # The item's own key wins over any "id" column a label file carried (a CSV row's id is text).
    return "".join(json.dumps({**v, "id": k}, ensure_ascii=False) + "\n" for k, v in final.items())


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("card", choices=sorted(CARDS))
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--model", default="gemini-3.5-flash-lite")
    ap.add_argument("--packets", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)
    spec = CARDS[args.card]
    cache = Cache(args.work / "gemini-cache", args.card, args.model, _hash(codebook(args.card)))
    first, second = first_labels(args.card, args.work), second_labels(args.card, cache)
    items = {i["id"]: i for i in load_items(args.card, args.work)}
    if args.card.startswith("dora-sources"):
        # Workflow labels are keyed "repo|path"; their packets show the repo's view.
        items |= {k: items[k.split("|")[0]] for k in first if "|" in k and k.split("|")[0] in items}
    packs = packets(items, first, second, spec["compare"])
    folder = args.work / f"adjudicate-{args.card}"
    if args.packets:
        folder.mkdir(exist_ok=True)
        for n in range(0, len(packs), PART):
            blind = [{k: v for k, v in p.items() if k != "_first"} for p in packs[n:n + PART]]
            (folder / f"packets-{n // PART:02d}.jsonl").write_text(
                "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in blind), encoding="utf-8")
        print(f"{len(packs)} disagreements in {(len(packs) + PART - 1) // PART} packet files in {folder}")
        return 0
    if args.apply:
        decisions = [d for f in sorted(folder.glob("decisions-*.jsonl")) for d in _jsonl(f)]
        suffix = args.card.split("-", 1)[1] if "-" in args.card else args.card
        final, summary = apply(packs, decisions, first, second, HERE / spec["folder"] / f"adjudication-{suffix}.csv")
        # Kept outside the card's work folder, whose scripts read every labels-*.jsonl there.
        final_dir = args.work.parent / "final"
        final_dir.mkdir(exist_ok=True)
        (final_dir / f"{args.card}.jsonl").write_text(final_lines(final), encoding="utf-8")
        print(json.dumps(summary))
        return 0
    print(f"{len(packs)} disagreements; use --packets or --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
