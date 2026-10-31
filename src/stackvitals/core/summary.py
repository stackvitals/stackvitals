"""Tier 1 storage: small JSON-lines summaries in the data branch (`summary/`), one row per PR, job or test, that DuckDB
reads locally and DuckDB-WASM reads in the browser straight from GitHub, with no server and no extra install in the
Action (Parquet needs pyarrow, which would cost every CI-triggered run several seconds)."""
import json
from datetime import datetime
from pathlib import Path

from stackvitals.core.actors import People
from stackvitals.core.model import ChangeRequest
from stackvitals.core.store import SCHEMA
from stackvitals.core.time import iso

FOLDER = "summary"
# Fixed column types, so tables from several repos combine even when one repo's column is all empty (DuckDB would read
# an all-null column as JSON). A new summary field needs its type here (a test checks).
_RATE = {"flake_rate": "DOUBLE", "rate_low": "DOUBLE", "rate_high": "DOUBLE"}
TYPES = {
    "prs": {"number": "BIGINT", "status": "VARCHAR", "draft": "BOOLEAN", "author": "VARCHAR", "author_kind": "VARCHAR",
            "role": "VARCHAR", "created_at": "TIMESTAMP", "ready_at": "TIMESTAMP", "merged_at": "TIMESTAMP",
            "closed_at": "TIMESTAMP", "additions": "BIGINT", "deletions": "BIGINT", "changed_files": "BIGINT",
            "base_ref": "VARCHAR", "head_ref": "VARCHAR", "reviews": "BIGINT", "first_review_at": "TIMESTAMP",
            "pickup_s": "DOUBLE", "cycle_s": "DOUBLE", "labels": "VARCHAR[]", "linked_issue": "BOOLEAN"},
    "ci_jobs": {"workflow": "VARCHAR", "job": "VARCHAR", "state": "VARCHAR", "runs": "BIGINT", "failures": "BIGINT",
                "flake_events": "BIGINT", **_RATE, "median_s": "DOUBLE", "p95_s": "DOUBLE", "last_flake": "TIMESTAMP",
                "retry_minutes": "DOUBLE", "prs_affected": "BIGINT", "top_step": "VARCHAR", "window_days": "BIGINT"},
    "tests": {"test_id": "VARCHAR", "suite": "VARCHAR", "workflow": "VARCHAR", "state": "VARCHAR", "runs": "BIGINT",
              "failures": "BIGINT", "flake_events": "BIGINT", **_RATE, "last_flake": "TIMESTAMP", "message": "VARCHAR",
              "prs_affected": "BIGINT", "window_days": "BIGINT"},
}


def table_types(stem: str) -> dict | None:
    """The column types of a summary file (ours, or DevLake's for devlake_*), or None for a file we don't know."""
    if stem.startswith("devlake_"):
        from stackvitals.core.export import COLUMNS
        return COLUMNS.get(stem[len("devlake_"):])
    return TYPES.get(stem)


def _write(root: Path, name: str, rows: list[dict], now: datetime) -> str:
    folder = root / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    text = "".join(json.dumps(r, separators=(",", ":"), ensure_ascii=False) + "\n" for r in rows)
    try:
        if path.read_text(encoding="utf-8") == text:
            return f"{FOLDER}/{name}"  # same rows: no rewrite and no new time stamp, so a quiet run commits nothing
    except OSError:
        pass
    path.write_text(text, encoding="utf-8", newline="\n")
    manifest_path = folder / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = {}
    files = dict(manifest.get("files") or {})
    files[name] = {"rows": len(rows), "generated": iso(now)}
    manifest_path.write_text(json.dumps({"schema": SCHEMA, "generated": iso(now), "files": files}, indent=1), encoding="utf-8",
                             newline="\n")
    return f"{FOLDER}/{name}"


def pr_rows(data: dict, now: datetime, repo: str = "") -> list[dict]:
    from stackvitals.flow.analyze import _human_reviews, stages
    prs = (data.get("open") or []) + (data.get("closed") or [])
    people = People(prs)
    rows = []
    for p in prs:
        cr = ChangeRequest.from_flow(p, repo)
        st = stages(p)
        reviews = _human_reviews(p)
        rows.append({"number": cr.number, "status": cr.state, "draft": cr.draft, "author": cr.author, "author_kind": cr.author_kind,
                     "role": people.role(cr.author), "created_at": cr.created_at, "ready_at": cr.ready_at, "merged_at": cr.merged_at,
                     "closed_at": cr.closed_at, "additions": cr.additions, "deletions": cr.deletions, "changed_files": cr.changed_files,
                     "base_ref": cr.base_ref, "head_ref": cr.head_ref, "reviews": len(reviews),
                     "first_review_at": reviews[0][1] if reviews else None, "pickup_s": st["pickup"], "cycle_s": st["cycle"],
                     "labels": cr.labels, "linked_issue": cr.linked_issue})
    return rows


def write_pr_summary(root: Path, data: dict, now: datetime, repo: str = "") -> list[str]:
    return [_write(root, "prs.jsonl", pr_rows(data, now, repo), now)]


def write_ci_summary(root: Path, result: dict, now: datetime) -> list[str]:
    window = result.get("window_days")
    jobs = [{"workflow": j.get("workflow"), "job": j.get("job"), "state": j.get("state"), "runs": j.get("runs"),
             "failures": j.get("failures"), "flake_events": j.get("flake_events"), "flake_rate": j.get("flake_rate"),
             "rate_low": j.get("rate_low"), "rate_high": j.get("rate_high"), "median_s": j.get("median_s"), "p95_s": j.get("p95_s"),
             "last_flake": j.get("last_flake"), "retry_minutes": j.get("retry_minutes"),
             "prs_affected": len(j.get("prs_affected") or []), "top_step": j.get("top_step"), "window_days": window}
            for j in result.get("jobs") or []]
    tests = [{"test_id": t.get("id"), "suite": t.get("suite"), "workflow": t.get("workflow"), "state": t.get("state"),
              "runs": t.get("runs"), "failures": t.get("failures"), "flake_events": t.get("flake_events"),
              "flake_rate": t.get("flake_rate"), "rate_low": t.get("rate_low"), "rate_high": t.get("rate_high"),
              "last_flake": t.get("last_flake"), "message": t.get("message"), "prs_affected": len(t.get("prs_affected") or []),
              "window_days": window}
             for t in result.get("tests") or []]
    return [_write(root, "ci_jobs.jsonl", jobs, now), _write(root, "tests.jsonl", tests, now)]


def write_devlake_summary(root: Path, tables: dict[str, list[dict]], now: datetime) -> list[str]:
    """DevLake's domain tables beside the other summaries (`devlake_<table>.jsonl`), for DevLake's own SQL anywhere."""
    return [_write(root, f"devlake_{name}.jsonl", rows, now) for name, rows in tables.items()]
