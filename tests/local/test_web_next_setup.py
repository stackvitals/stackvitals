"""The web app's GitHub client, setup state machine and workflow generator tests (npm test in web/), and the sign-in
relay's tests (worker/relay), run from pytest when node is installed."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(not NODE, reason="node isn't installed")


@needs_node
def test_web_setup_unit_tests_pass():
    if not (ROOT / "web" / "node_modules" / "esbuild").exists():
        pytest.skip("run npm ci in web/ first")
    out = subprocess.run([NODE, "test/run.mjs"], cwd=ROOT / "web", capture_output=True, text=True, timeout=300, encoding="utf-8")
    assert out.returncode == 0, (out.stdout + out.stderr)[-4000:]
    assert "# fail 0" in out.stdout or "ℹ fail 0" in out.stdout
    # The workflow parity test must really compare with Python, not skip.
    assert "skip" not in out.stdout.split("matches stackvitals ci init")[1].splitlines()[0]


@needs_node
def test_sign_in_relay_tests_pass():
    relay = ROOT / "worker" / "relay"
    tests = sorted(str(p.relative_to(relay)) for p in (relay / "test").glob("*.test.mjs"))
    out = subprocess.run([NODE, "--test", *tests], cwd=relay, capture_output=True, text=True, timeout=120, encoding="utf-8")
    assert out.returncode == 0, (out.stdout + out.stderr)[-4000:]
