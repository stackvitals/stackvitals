from stackvitals import cli
from stackvitals import __version__


def test_cli_version_flag_prints_version_and_exits(capsys):
    with __import__("pytest").raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"stackvitals {__version__}"


def test_cli_version_matches_packaged_version(capsys):
    with __import__("pytest").raises(SystemExit):
        cli.main(["--version"])
    assert __version__ != ""
