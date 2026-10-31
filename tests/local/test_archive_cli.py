from datetime import datetime, timedelta, timezone

import pytest

from mergescout.archive.__main__ import main


def test_bad_hour_key_fails_cleanly(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MS_DATA_DIR", str(tmp_path / "data"))
    assert main(["2026-10-01-24"]) == 1
    assert "failed" in capsys.readouterr().err


@pytest.mark.network
def test_convert_one_real_hour(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MS_DATA_DIR", str(tmp_path / "data"))
    day = (datetime.now(timezone.utc) - timedelta(days=3)).date().isoformat()
    assert main([f"{day}-3"]) == 0
    assert "done" in capsys.readouterr().out
