import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _sync():
    spec = importlib.util.spec_from_file_location("sync", ROOT / "scripts" / "sync_crawler.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_both_commands_start():
    for mod in ("stackvitals.cli", "mergescout.cli"):
        run = subprocess.run([sys.executable, "-m", mod, "--help"], capture_output=True, text=True, timeout=60)
        assert run.returncode == 0, run.stderr
