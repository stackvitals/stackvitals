"""Score the flaky-test sample: event precision against a plain "passed on retry" rule, the masking rate, the miss rate
and the cause mix, each with a Wilson 95% range, and agreement between two labellings when there are two.

    python bench/accuracy/flaky/score.py --home <work folder> --log <sampler output> [--second labels2.jsonl]

Reads <home>/items.jsonl and <home>/labels.jsonl (one label per item, in item order); writes card.json and items.csv
(links and labels, never log text) beside this script.
"""
import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

from stackvitals.core.stats import wilson

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fair import by_repo, compare_shares, mixture  # noqa: E402

INTERMITTENT = {"test", "product_race", "infrastructure", "network", "timeout"}
POOLS = re.compile(r"^(?P<repo>[^:\s]+/[^:\s]+): flagged (?P<flagged>\d+), vendor_extra (?P<extra>\d+), "
                   r"known_flaky_failure (?P<known>\d+), unflagged_failure (?P<unflagged>\d+)")


def _share(hits: int, n: int) -> dict:
    lo, hi = wilson(hits, n)
    return {"n": n, "share": round(hits / n, 4) if n else None, "low": round(lo, 4), "high": round(hi, 4)}


def _kappa(a: list[str], b: list[str]) -> float | None:
    if not a:
        return None
    seen = len(a)
    agree = sum(x == y for x, y in zip(a, b)) / seen
    ca, cb = Counter(a), Counter(b)
    chance = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (seen * seen)
    return round((agree - chance) / (1 - chance), 4) if chance < 1 else 1.0


def score(items: list[dict], labels: list[dict], pools: dict) -> dict:
    rows = [(i, l) for i, l in zip(items, labels) if i.get("sample") not in (None, "none")]
    by = lambda name: [(i, l) for i, l in rows if i["sample"] == name]  # noqa: E731
    sure = lambda pairs: [(i, l) for i, l in pairs if l["caused_by_change"] != "unclear"]  # noqa: E731
    right = lambda l: l["caused_by_change"] == "no" and l["own_failure"] == "yes"  # noqa: E731
    flagged, extra = sure(by("flagged")), sure(by("vendor_extra"))
    known, missed = sure(by("known_flaky_failure")), sure(by("unflagged_failure"))
    ours_k, extra_k = sum(right(l) for _i, l in flagged), sum(right(l) for _i, l in extra)
    ours, theirs_extra = _share(ours_k, len(flagged)), _share(extra_k, len(extra))
    total_f = sum(p["flagged"] for p in pools.values())
    total_v = sum(p["extra"] for p in pools.values())
    # The plain rule sees only retries: our retry events plus the ones we leave out, never same-commit flips.
    retry = [(i, l) for i, l in flagged if i.get("kind", "retry") == "retry"]
    retry_k = sum(right(l) for _i, l in retry)
    sampled = by("flagged")
    retry_pool = total_f * sum(i.get("kind", "retry") == "retry" for i, _l in sampled) / len(sampled) if sampled else 0
    vendor = None
    if retry_pool + total_v and retry and theirs_extra["share"] is not None:
        vendor = round((retry_pool * retry_k / len(retry) + total_v * theirs_extra["share"]) / (retry_pool + total_v), 4)
        mix = mixture([(retry_k, len(retry), retry_pool), (extra_k, len(extra), total_v)], against=(ours_k, len(flagged)))
        fair = {"precision_range": {"low": mix["low"], "high": mix["high"], "method": mix["method"]},
                "ours_minus_it": mix["difference"], "retry_events_right": _share(retry_k, len(retry)),
                "left_out_vs_ours": compare_shares(ours_k, len(flagged), extra_k, len(extra))}
    else:
        fair = {}
    signal = lambda kind, pairs: _share(sum(right(l) for i, l in pairs if i.get("kind", "retry") == kind),  # noqa: E731
                                        sum(i.get("kind", "retry") == kind for i, _l in pairs))
    by_signal = {"retry": signal("retry", flagged), "flip": signal("flip", flagged)}
    causes = Counter(l["cause"] for _i, l in by("flagged"))
    missed_right = lambda l: l["caused_by_change"] == "no" and l["cause"] in INTERMITTENT  # noqa: E731
    by_language = {}
    for group in sorted({i.get("group") or "other" for i, _l in rows}):
        f = [l for i, l in flagged if (i.get("group") or "other") == group]
        m = [l for i, l in missed if (i.get("group") or "other") == group]
        by_language[group] = {"event_precision": _share(sum(right(l) for l in f), len(f)),
                              "miss_rate": _share(sum(missed_right(l) for l in m), len(m))}
    return {
        "by_language": by_language, "by_signal": by_signal,
        "items": len(rows), "repos": len({i["repo"] for i, _l in rows}),
        "event_precision": {**ours, "unclear": len(by("flagged")) - len(flagged),
                            "real_bugs_among_flakes": _share(sum(l["cause"] == "product_race" for _i, l in flagged), len(flagged)),
                            "by_repo": by_repo([(i["repo"], right(l)) for i, l in flagged])},
        "plain_retry_rule": {"left_out_events_right": theirs_extra, "events_flagged_by_ours": total_f,
                             "events_only_it_flags": total_v, "precision": vendor, **fair},
        "masking_rate": {**_share(sum(l["caused_by_change"] == "yes" for _i, l in known), len(known)),
                         "unclear": len(by("known_flaky_failure")) - len(known)},
        "miss_rate": {**_share(sum(l["caused_by_change"] == "no" and l["cause"] in INTERMITTENT for _i, l in missed), len(missed)),
                      "unclear": len(by("unflagged_failure")) - len(missed)},
        "cause_mix_flagged": dict(causes.most_common()),
        "cause_mix_all": dict(Counter(l["cause"] for _i, l in rows).most_common()),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--home", type=Path, required=True)
    ap.add_argument("--log", type=Path, required=True, help="the sampler's printed output (pool sizes per repo)")
    ap.add_argument("--second", type=Path, help="a second, independent labelling of some items, for agreement")
    ap.add_argument("--labeller", default="model (Claude), audit pending")
    args = ap.parse_args(argv)
    items = [json.loads(x) for x in (args.home / "items.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    labels = [json.loads(x) for x in (args.home / "labels.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    labels = sorted(labels, key=lambda l: l["id"])
    by_id = {l["id"]: l for l in labels}
    items = [i for i in items if i.get("sample") != "none"]
    paired = [by_id.get(n + 1) for n in range(len(items))]
    missing = [n + 1 for n, l in enumerate(paired) if l is None]
    if missing:
        print(f"items without a label: {missing[:20]}", file=sys.stderr)
        return 1
    pools = {}
    for line in args.log.read_text(encoding="utf-8", errors="replace").splitlines():
        if (m := POOLS.match(line)):
            pools[m["repo"]] = {k: int(m[k]) for k in ("flagged", "extra", "known", "unflagged")}
    card = score(items, paired, pools)
    card["labeller"] = args.labeller
    if args.second:
        second = {l["id"]: l for l in (json.loads(x) for x in args.second.read_text(encoding="utf-8").splitlines() if x.strip())}
        both = [(by_id[k]["caused_by_change"], second[k]["caused_by_change"]) for k in second if k in by_id]
        card["agreement"] = {"items": len(both), "kappa_caused_by_change": _kappa([a for a, _ in both], [b for _, b in both]),
                             "same": round(sum(a == b for a, b in both) / len(both), 4) if both else None}
    here = Path(__file__).parent
    (here / "card.json").write_text(json.dumps(card, indent=1, sort_keys=True), encoding="utf-8")
    with (here / "items.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "sample", "repo", "group", "workflow", "job", "event", "url", "cause", "caused_by_change",
                    "own_failure", "confidence"])
        for n, (i, l) in enumerate(zip(items, paired), 1):
            w.writerow([n, i["sample"], i["repo"], i.get("group"), i.get("workflow"), i.get("job"), i.get("event"), i.get("url"),
                        l["cause"], l["caused_by_change"], l["own_failure"], l.get("confidence")])
    print(json.dumps(card, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
