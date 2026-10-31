import pyarrow.parquet as pq

from mergescout.crawl import __main__ as cli
from mergescout.crawl.__main__ import main
from mergescout.crawl.state import CrawlState
from test_crawl_runner import GQL, budget
from test_crawl_seed import repo, write_basics


def env(monkeypatch, tmp_path, token="t"):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MS_DATA_DIR", str(tmp_path))
    if token:
        monkeypatch.setenv("GITHUB_TOKEN", token)
    else:
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)


def test_status_on_empty_state(monkeypatch, tmp_path, capsys):
    env(monkeypatch, tmp_path)
    assert main(["status"]) == 0
    assert "repos={}" in capsys.readouterr().out


def test_run_without_token_fails_clearly(monkeypatch, tmp_path, capsys):
    env(monkeypatch, tmp_path, token=None)
    assert main(["run", "--minutes", "1"]) == 1
    assert "GITHUB_TOKEN" in capsys.readouterr().err


def test_backup_copies_state(monkeypatch, tmp_path):
    env(monkeypatch, tmp_path)
    CrawlState(tmp_path / "crawl.sqlite").upsert_repos([{"repo_id": 1, "name": "o/r", "stars": 100,
                                                          "pushed_at": None, "priority": 0}])
    assert main(["backup", str(tmp_path / "copy.sqlite")]) == 0
    assert CrawlState(tmp_path / "copy.sqlite").counts() == {"queued": 1}
