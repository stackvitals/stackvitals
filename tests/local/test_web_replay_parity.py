"""The app's "would have fired" preview (web/src/features/settingsReplay.ts) gives the same counts as the Action's rule
(core/alerts.replay) on the same published daily points, including gaps, thin days and recoveries."""
import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from stackvitals.core.alerts import HEADS_UP, MIN_N, replay


@pytest.mark.skipif(shutil.which("node") is None, reason="Node isn't installed")
def test_the_app_replays_alerts_exactly_like_the_action():
    # Loaded by Node with its types stripped.
    ver = subprocess.run(["node", "--version"], capture_output=True, text=True).stdout.strip().lstrip("v").split(".")
    if (int(ver[0]), int(ver[1])) < (22, 18):
        pytest.skip("Node 22.18+ is needed to load TypeScript")
    src = Path(__file__).resolve().parents[2] / "web" / "src" / "features"
    rng = random.Random(11)
    for trial in range(25):
        series = {}
        for metric in ("pickup_p75_hours", "review_p75_hours", "cycle_p75_hours", "change_failure_rate"):
            points = []
            for day in range(91):
                value = None if rng.random() < 0.1 else round(rng.uniform(0, 30 if metric != "change_failure_rate" else 0.4), 3)
                low = None if value is None or rng.random() < 0.2 else round(value * rng.uniform(0.3, 1.0), 3)
                points.append([f"d{day}", value, rng.choice([0, 5, 9, 10, 20, 40]), low])
            series[metric] = points
        limits = {"pickup_p75_hours": rng.choice([4, 8, 12]), "review_p75_hours": 14, "change_failure_rate": rng.choice([0.1, 0.15])}
        want = replay({m: [tuple(p) for p in v] for m, v in series.items()}, limits)
        script = (f"import {{ replay }} from './settingsReplay.ts'; console.log(JSON.stringify(replay({json.dumps(series)}, "
                  f"{json.dumps(limits)}, {{ headsUp: {HEADS_UP}, minN: {MIN_N} }})))")
        out = subprocess.run(["node", "--input-type=module", "-e", script], cwd=src, capture_output=True, text=True, timeout=30)
        assert out.returncode == 0, out.stderr
        assert json.loads(out.stdout) == want, (trial, limits)


def test_the_demo_settings_list_every_setting_as_the_schema_does():
    # web/demo/settings.json feeds the demo's Settings page; it must list exactly what core/schema.py publishes.
    from stackvitals.core import schema
    demo = json.loads((Path(__file__).resolve().parents[2] / "web" / "demo" / "settings.json").read_text(encoding="utf-8"))
    assert demo["settings"] == json.loads(json.dumps(schema.to_json()))
