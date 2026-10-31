"""Phase 13 M3: the flaky sample's evidence for labellers."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bench" / "accuracy" / "flaky"))

from sample import LOG_CHARS, _excerpt  # noqa: E402


def test_the_excerpt_keeps_the_first_error_line_however_long_the_lines_before_it():
    before = [f"2026-10-19T10:00:{k % 60:02d}.0000000Z compiling module {k} " + "x" * 150 for k in range(80)]
    after = [f"2026-10-19T10:05:{k % 60:02d}.0000000Z cleanup step {k} " + "y" * 150 for k in range(200)]
    log = "\n".join(before + ["2026-10-19T10:04:00.0000000Z ##[error]test_parse failed: KeyError 'id'"] + after)
    out = _excerpt(log)
    assert "##[error]test_parse failed: KeyError 'id'" in out and len(out) <= LOG_CHARS + 10
    assert "cleanup step 199" in out  # the log's end, where runners print which tests failed


def test_a_log_without_an_error_marker_keeps_its_end():
    log = "\n".join(f"line {k} " + "z" * 100 for k in range(300))
    out = _excerpt(log)
    assert "line 299" in out and len(out) <= LOG_CHARS + 10
