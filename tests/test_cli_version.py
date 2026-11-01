"""Tests for the top-level stackvitals CLI, including --version."""

import pytest

from stackvitals.cli import main


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "stackvitals 0.2.0"
