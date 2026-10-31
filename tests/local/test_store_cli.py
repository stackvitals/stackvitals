from mergescout.store import __main__ as cli
from test_store import MemReleases, make_data


def test_missing_token_or_repo_fails_clearly(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("MS_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("MS_RELEASE_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    assert cli.main(["push"]) == 1
    assert "MS_RELEASE_TOKEN" in capsys.readouterr().err


def test_store_repo_setting_overrides_the_workflow_repo(monkeypatch, tmp_path):
    monkeypatch.setenv("MS_RELEASE_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "me/crawler-repo")
    monkeypatch.setenv("MS_STORE_REPO", "me/private-project")
    monkeypatch.setenv("MS_DATA_DIR", str(tmp_path))
    made = []
    monkeypatch.setattr(cli, "Releases", lambda token, repo: made.append(repo) or MemReleases())
    assert cli.main(["pull"]) == 0
    assert made == ["me/private-project"]


def test_put_uploads_one_file(monkeypatch, tmp_path):
    monkeypatch.setenv("MS_RELEASE_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "me/repo")
    monkeypatch.setenv("MS_DATA_DIR", str(tmp_path))
    rel = MemReleases()
    monkeypatch.setattr(cli, "Releases", lambda token, repo: rel)
    f = tmp_path / "signals.tar"
    f.write_bytes(b"x")
    assert cli.main(["put", str(f), "--tag", "signals-latest"]) == 0
    assert rel.files[("signals-latest", "signals.tar")] == b"x"
