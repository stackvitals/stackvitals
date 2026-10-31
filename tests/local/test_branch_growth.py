import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bench" / "accuracy" / "features"))

from branch_growth import simulate  # noqa: E402


def _day(tmp_path):
    rows = [{"t": "run", "id": n, "cr": "2026-10-17T07:00:00Z", "c": "success"} for n in range(20)]
    path = tmp_path / "day.ndjson"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def test_simulation_keeps_retention_and_squashes(tmp_path):
    out = simulate(_day(tmp_path), tmp_path / "sim", days=6, runs=2, retention=3, squash_every=5, checkpoint=3)
    days = sorted(p.name for p in (tmp_path / "sim" / "repo" / "ci" / "days").iterdir())
    assert len(days) <= 4 and days[-1].startswith("2025-01-06") and days[0].endswith(".gz")
    last = out["checkpoints"][-1]
    assert last["commits_made"] == 12 and last["squashes"] == 2 and last["commits_on_branch"] < 5
    log = subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=tmp_path / "sim" / "repo", capture_output=True, text=True)
    assert int(log.stdout) == last["commits_on_branch"]


def test_each_day_replays_the_records_with_its_own_date(tmp_path):
    simulate(_day(tmp_path), tmp_path / "sim", days=1, runs=1, retention=3, checkpoint=1)
    text = (tmp_path / "sim" / "repo" / "ci" / "days" / "2025-01-01.ndjson").read_text(encoding="utf-8")
    assert "2025-01-01T07:00:00Z" in text and "2026-10-17" not in text and len(text.splitlines()) == 20


def test_git_never_reaches_a_repo_above_a_missing_simulation(tmp_path):
    # 2026-10-22: a simulation folder deleted mid-run let `git add -A; git commit` land 158 commits in the real repo.
    import pytest
    from branch_growth import _git
    outer = tmp_path / "outer"
    outer.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=outer, check=True)
    inner = outer / "sim" / "repo"
    inner.mkdir(parents=True)
    with pytest.raises(subprocess.CalledProcessError):
        _git(inner, "commit", "-q", "--allow-empty", "-m", "stray")
    log = subprocess.run(["git", "rev-list", "--all", "--count"], cwd=outer, capture_output=True, text=True)
    assert log.stdout.strip() == "0"
