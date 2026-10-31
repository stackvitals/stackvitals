"""Scores a head-to-head run (preregistration.md): DevLake's DORA panels per repo, computed with its own dashboard SQL
(ported to DuckDB) on the domain tables it collected, next to StackVitals' DORA for the same repo and window.

    python bench/accuracy/devlake/score.py <folder holding results.json and devlake-tables/>
"""
import json
import re
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "src"))
from stackvitals.core.export import panels  # noqa: E402

MEASURES = ("deployment_frequency", "lead_time", "change_failure_rate", "recovery")
OURS = {"deployment_frequency": ("deployment_days_per_week", "frequency_tier"), "lead_time": ("lead_time_hours", "lead_time_tier"),
        "change_failure_rate": ("change_failure_rate", "cfr_tier"), "recovery": ("recovery_hours", "recovery_tier")}


def _read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


NUMBER = re.compile(r"-?\d+(\.\d+)?")


def _typed(v):
    return (float(v) if "." in v else int(v)) if isinstance(v, str) and NUMBER.fullmatch(v) else v


def tier_of(panel) -> str | None:
    """DevLake shows "26.5(high)"; the tier is in the brackets."""
    m = re.search(r"\(([a-z]+)\)", str(panel or ""))
    return m.group(1) if m else None


def scope_of(full: str, tables: Path) -> str | None:
    """DevLake's scope id for one repo, read from its own pull request rows (base_repo_id) and deployment rows."""
    name = full.split("/")[-1].lower()
    for row in _read(tables / "pull_requests.jsonl"):
        if f"/{full.lower()}/" in (row.get("url") or "").lower() + "/" or row.get("url", "").lower().endswith(f"{full.lower()}"):
            return row.get("base_repo_id")
    for row in _read(tables / "cicd_deployment_commits.jsonl"):
        if (row.get("repo_url") or "").lower().rstrip("/").endswith(full.lower()) or name == (row.get("repo_name") or "").lower():
            return row.get("cicd_scope_id")
    return None


def per_repo(tables: Path, full: str, start: datetime, end: datetime) -> dict:
    """DevLake's panels for one repo: its tables copied with a project that maps only this repo's scope."""
    scope = scope_of(full, tables)
    if not scope:
        return {"error": "DevLake collected nothing for this repo"}
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp)
        for f in tables.glob("*.jsonl"):
            # mysql --batch writes every value as text; numbers go back to numbers for DevLake's SQL.
            (dest / f.name).write_text("".join(json.dumps({k: _typed(v) for k, v in r.items()}) + "\n" for r in _read(f)),
                                       encoding="utf-8")
        from stackvitals.core.export import COLUMNS
        for name in COLUMNS:
            # Tables DevLake left empty for these repos (issues, CI tasks) are read as empty, not missing.
            if not (dest / f"{name}.jsonl").exists():
                (dest / f"{name}.jsonl").write_text("", encoding="utf-8")
        rows = [{"project_name": full, "table": t, "row_id": scope} for t in ("repos", "cicd_scopes")]
        (dest / "project_mapping.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        out = panels(dest, start, end, "2023", full)
    return {"scope": scope, **{k: out.get(k) for k in MEASURES}}


def main(folder: str) -> int:
    root = Path(folder)
    res = json.loads((root / "results.json").read_text(encoding="utf-8"))
    start, end = (datetime.fromisoformat(x + "+00:00") for x in res["window"])
    tables = root / "devlake-tables"
    rows = []
    for full in res["repos"]:
        dl = per_repo(tables, full, start, end) if tables.exists() else {"error": res.get("devlake_error") or "no DevLake tables"}
        sv = (res.get("stackvitals") or {}).get(full) or {}
        dora = sv.get("dora") or {}
        row = {"repo": full, "stackvitals_source": sv.get("deploy_source"), "stackvitals_seconds": sv.get("seconds")}
        for m in MEASURES:
            value_key, tier_key = OURS[m]
            row[m] = {"devlake": dl.get(m), "devlake_tier": tier_of(dl.get(m)),
                      "stackvitals": dora.get(value_key), "stackvitals_tier": dora.get(tier_key),
                      "same_tier": tier_of(dl.get(m)) is not None and tier_of(dl.get(m)) == dora.get(tier_key)}
        row["devlake_error"] = dl.get("error")
        rows.append(row)
    summary = {"run_at": res.get("run_at"), "devlake": {k: v for k, v in (res.get("devlake") or {}).items() if k not in ("dora_panels",)},
               "devlake_error": res.get("devlake_error"), "stackvitals_total_s": res.get("stackvitals_total_s"), "repos": rows,
               "same_tier": {m: sum(r[m]["same_tier"] for r in rows) for m in MEASURES}}
    (HERE / "head-to-head-results.json").write_text(json.dumps(summary, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps(summary["same_tier"]), "->", HERE / "head-to-head-results.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else str(HERE)))
