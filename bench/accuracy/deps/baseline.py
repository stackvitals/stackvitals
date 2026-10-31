"""Phase 16 baseline for the dependency evidence, before EPSS, KEV, transitive paths and rollback weighting are added:
what the crawl's files hold today and what the product can say from them.

    python bench/accuracy/deps/baseline.py --deps <crawl deps folder: deps-osv.json, deps-ledger.json, deps-map.json>

Writes baseline-results.json beside this script (counts only).
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent


def osv_baseline(osv: dict) -> dict:
    pk = osv["packages"]
    hit = [v for v in pk.values() if v.get("advisories")]
    ids = Counter(i.split("-", 1)[0] for v in hit for i in v.get("ids") or [])
    sev = Counter()
    for v in hit:
        sev.update(v.get("severity") or {})
    return {"packages": len(pk), "with_advisories": len(hit), "advisories": sum(v["advisories"] for v in hit),
            "unfixed": sum(v.get("unfixed") or 0 for v in hit), "malware_flags": sum(bool(v.get("malware")) for v in pk.values()),
            "id_prefixes": dict(ids.most_common()), "severity": dict(sev.most_common()),
            # EPSS and KEV are keyed by CVE: the cached records keep each advisory's aliases, CVEs among them.
            "records": len(osv.get("records") or {}),
            "records_with_a_cve": sum(1 for r in (osv.get("records") or {}).values()
                                      if any(a.startswith("CVE-") for a in [r.get("id") or "", *(r.get("aliases") or [])])),
            "epss_scored": 0, "kev_checked": 0, "complete": osv.get("complete")}


def ledger_baseline(ledger: dict) -> dict:
    cells = ledger["cells"]
    merged = sum(c["merged"] for c in cells)
    reverted = sum(c["reverted"] for c in cells)
    by_step = {}
    for step in ("major", "minor", "patch"):
        mine = [c for c in cells if c["bump"] == step]
        m, r = sum(c["merged"] for c in mine), sum(c["reverted"] for c in mine)
        by_step[step] = {"merged": m, "reverted": r, "share": round(r / m, 4) if m else None}
    worst = sorted((c for c in cells if c["reverted"]), key=lambda c: (-c["reverted"], c["package"]))[:10]
    return {"window_days": ledger["window_days"], "cells": len(cells), "prs": sum(c["prs"] for c in cells),
            "merged": merged, "reverted": reverted, "reverted_share": round(reverted / merged, 4) if merged else None,
            "cells_with_a_revert": sum(1 for c in cells if c["reverted"]), "by_step": by_step,
            "most_reverted": [{"ecosystem": c["ecosystem"], "package": c["package"], "bump": c["bump"],
                               "merged": c["merged"], "reverted": c["reverted"], "repos": c["repos"]} for c in worst]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--deps", type=Path, required=True)
    args = ap.parse_args(argv)
    load = lambda name: json.loads((args.deps / name).read_text(encoding="utf-8"))  # noqa: E731
    out = {"osv": osv_baseline(load("deps-osv.json")), "ledger": ledger_baseline(load("deps-ledger.json")),
           "built_at": load("deps-osv.json").get("built_at"),
           "product_today": {"transitive_paths": "none: the SBOM lists every resolved package but not which direct one "
                                                 "pulls it in", "fixed_version_per_advisory": "counted as unfixed or "
                                                 "not; the version that fixes each is not shown", "epss_kev": "not read",
                             "policy": "licence deny list only (no minimum Scorecard or severity)"}}
    (HERE / "baseline-results.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
