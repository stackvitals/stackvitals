"""Replay on real public repos (the ones whose PR runs upload test reports): test impact on their past PRs, and our flaky
rules next to Trunk's documented one (a test that both passed and failed on the same commit)."""
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
from stackvitals.ci import impact  # noqa: E402
from stackvitals.ci.analyze import analyze  # noqa: E402
from stackvitals.ci.store import DataStore  # noqa: E402
from stackvitals.flow.store import FlowStore  # noqa: E402

HOME = Path(__file__).with_name("work") / "tia-data"
now = datetime.now(timezone.utc)
out = {}
for d in sorted((HOME / "ci").iterdir()):
    data = DataStore(d).load()
    flow = FlowStore(HOME / "flow" / d.name).load()
    res = analyze(data, now, 45)
    ours = {t["id"] for t in res.get("tests") or [] if t.get("state") == "flaky"}
    # Trunk: failed and passed on the same commit, in any runs.
    runs = {r["id"]: r for r in data.get("runs") or []}
    seen = defaultdict(lambda: defaultdict(set))
    for rec in data.get("tests") or []:
        sha = (runs.get(rec["run"]) or {}).get("sha")
        if not sha:
            continue
        failed = {f[0] for f in rec.get("failed") or []} | set(rec.get("flaky") or [])
        for tid in failed:
            seen[tid][sha].add("fail")
        for tid, _ms in rec.get("all") or []:
            if tid not in failed:
                seen[tid][sha].add("pass")
    trunk = {tid for tid, by in seen.items() if any(v == {"fail", "pass"} for v in by.values())}
    pr_paths = {p["n"]: p.get("paths") or [] for p in flow.get("closed") or [] if p.get("paths")}
    hist = impact.history_from(data, pr_paths, ours | trunk)
    files = sorted({f for _c, failed in hist for f in failed} | {p for paths in pr_paths.values() for p in paths if impact.TEST.search(p)})
    out[d.name] = {"runs": len(data.get("runs") or []), "reports": len(data.get("tests") or []), "tests_seen": len(seen),
                   "prs_with_files": len(pr_paths), "impact": impact.backtest(hist, files) if hist else None,
                   "flaky_ours": len(ours), "flaky_trunk_rule": len(trunk), "both": len(ours & trunk),
                   "only_ours": sorted(ours - trunk)[:5], "only_trunk": sorted(trunk - ours)[:5]}
    print(d.name, json.dumps({k: v for k, v in out[d.name].items() if k not in ("only_ours", "only_trunk")}), flush=True)
Path(__file__).with_name("replay-results.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
