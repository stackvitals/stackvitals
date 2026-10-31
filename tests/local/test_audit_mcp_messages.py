"""Pre-launch audit: user-facing snapshot errors spoke of an internal phase and a personal repo; now plain for outsiders."""
import pytest

from mergescout import mcp_server
from mergescout.github.releases import ReleaseError
from mergescout.tool import store


def test_release_errors_read_plainly():
    msg = mcp_server.plain(ReleaseError("404 Not Found"))
    assert "Phase" not in msg and "kaushik-yadav" not in msg
    assert "isn't published for outside use" in msg and "MERGESCOUT_TOKEN" in msg


def test_no_snapshot_reads_plainly(tmp_path):
    class Empty:
        def ensure(self, log=None):
            return None
    state = mcp_server.App.__new__(mcp_server.App)
    state.store, state.log, state._snap = Empty(), None, None
    import threading
    state._lock = threading.Lock()
    with pytest.raises(mcp_server.NoSnapshot) as err:
        state.snapshot()
    assert "Phase" not in str(err.value) and "kaushik-yadav" not in str(err.value) and "mergescout update" in str(err.value)


def test_the_data_repo_is_unchanged():
    assert store.DEFAULT_REPO == "kaushik-yadav/merge-scout"
