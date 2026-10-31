"""Summaries rewrite nothing when their rows did not change, so a quiet repo's scheduled run makes no commit."""
import json
from datetime import datetime, timedelta, timezone

from stackvitals.core.summary import _write

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)


def test_unchanged_rows_leave_the_file_and_its_manifest_entry_alone(tmp_path):
    _write(tmp_path, "prs.jsonl", [{"number": 1}], NOW)
    before = (tmp_path / "summary" / "manifest.json").read_text(encoding="utf-8")
    _write(tmp_path, "prs.jsonl", [{"number": 1}], NOW + timedelta(hours=3))
    assert (tmp_path / "summary" / "manifest.json").read_text(encoding="utf-8") == before
    _write(tmp_path, "prs.jsonl", [{"number": 1}, {"number": 2}], NOW + timedelta(hours=6))
    entry = json.loads((tmp_path / "summary" / "manifest.json").read_text(encoding="utf-8"))["files"]["prs.jsonl"]
    assert entry == {"rows": 2, "generated": "2026-10-20T18:00:00Z"}
