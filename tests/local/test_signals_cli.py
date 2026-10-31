from mergescout.signals.__main__ import main


def test_from_releases_reads_the_store_repo(monkeypatch, tmp_path):
    from mergescout.signals import __main__ as cli
    monkeypatch.setenv("MS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MS_RELEASE_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "me/crawler")
    monkeypatch.setenv("MS_STORE_REPO", "me/store")
    seen = []
    monkeypatch.setattr(cli, "Releases", lambda token, repo: seen.append(repo) or object())
    monkeypatch.setattr(cli, "fetch_bronze", lambda releases, data_dir, log=None: None)
    assert main(["build", "--from-releases", "--out", str(tmp_path / "out")]) == 1  # no crawl data found
    assert seen == ["me/store"]
