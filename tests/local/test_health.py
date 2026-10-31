"""Data health: one file a run writes (docs/health.json) answering is the data current, did collection finish, how far
back does each history go, and what was dropped, for the app's Data health page."""
import json
from datetime import datetime, timezone

from stackvitals.core import health

NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
LATER = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)


class Ws:
    def __init__(self, root, now=NOW):
        self.path, self.now, self.notes, self.cache = root, now, [], {}


def read(root):
    return json.loads((root / "docs" / "health.json").read_text(encoding="utf-8"))


def test_each_step_says_when_it_last_worked_and_whether_it_finished(tmp_path):
    (tmp_path / "docs").mkdir()
    health.write_health(Ws(tmp_path), {"CI Health": {"runs": 12, "requests": 40, "complete": False, "note": "x"},
                                       "Team Flow": {"prs": 30, "complete": True}}, {}, {"removed": {}, "dropped": {}})
    got = read(tmp_path)["sources"]
    assert got["CI Health"] == {"kind": "module", "last_try": "2026-10-28T12:00:00Z", "last_ok": "2026-10-28T12:00:00Z",
                                "failing_since": None, "error": None, "complete": False, "read": {"runs": 12, "requests": 40}}
    assert got["Team Flow"]["complete"] is True and got["Team Flow"]["read"] == {"prs": 30}


def test_a_failing_step_keeps_its_last_good_run_and_says_since_when(tmp_path):
    (tmp_path / "docs").mkdir()
    health.write_health(Ws(tmp_path), {"CI Health": {"runs": 1, "complete": True}}, {}, {})
    health.write_health(Ws(tmp_path, LATER), {}, {"CI Health": "GitHub's hourly limit is used up"}, {})
    got = read(tmp_path)["sources"]["CI Health"]
    assert got["last_ok"] == "2026-10-28T12:00:00Z" and got["last_try"] == "2026-10-29T12:00:00Z"
    assert got["failing_since"] == "2026-10-29T12:00:00Z" and got["error"] == "GitHub's hourly limit is used up"
    health.write_health(Ws(tmp_path, datetime(2026, 10, 30, tzinfo=timezone.utc)), {}, {"CI Health": "again"}, {})
    assert read(tmp_path)["sources"]["CI Health"]["failing_since"] == "2026-10-29T12:00:00Z"


def test_a_step_that_did_not_run_this_time_keeps_its_last_entry(tmp_path):
    (tmp_path / "docs").mkdir()
    health.write_health(Ws(tmp_path), {"Portal": {"repos": 3, "complete": True}}, {}, {})
    health.write_health(Ws(tmp_path, LATER), {"CI Health": {"runs": 1}}, {}, {})
    got = read(tmp_path)["sources"]
    assert got["Portal"]["last_try"] == "2026-10-28T12:00:00Z" and got["CI Health"]["complete"] is None


def test_connectors_report_from_their_own_status(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "connectors.json").write_text(json.dumps({"connectors": {
        "jira": {"name": "Jira", "as_of": "2026-10-28T11:00:00Z", "error": None, "rows": {"issue": 8, "change": 3},
                 "complete": True},
        "linear": {"name": "Linear", "as_of": "2026-10-28T11:00:00Z", "error": "Linear refused the key (401): check it.",
                   "rows": {"issue": 2}, "complete": False},
        "chat": {"name": "Chat", "check": {"ok": True}}}}), encoding="utf-8")
    health.write_health(Ws(tmp_path), {}, {}, {})
    got = read(tmp_path)["sources"]
    assert got["Jira"]["kind"] == "connector" and got["Jira"]["read"] == {"issue": 8, "change": 3}
    assert got["Jira"]["last_ok"] == "2026-10-28T11:00:00Z" and got["Linear"]["error"].startswith("Linear refused")
    assert got["Linear"]["failing_since"] == "2026-10-28T11:00:00Z" and "Chat" not in got


def test_history_says_how_far_back_each_stream_goes_and_what_the_cap_dropped(tmp_path):
    (tmp_path / "docs").mkdir()
    days = tmp_path / "ci" / "days"
    days.mkdir(parents=True)
    for d in ("2026-08-01", "2026-09-15", "2026-10-27"):
        (days / f"{d}.ndjson.gz").write_bytes(b"x" * 10)
    health.write_health(Ws(tmp_path), {}, {}, {"removed": {"ci/days": 2}, "dropped": {"flow/closed": 5}})
    got = read(tmp_path)
    assert got["history"]["ci/days"] == {"oldest": "2026-08-01", "newest": "2026-10-27", "files": 3, "bytes": 30,
                                         "keeps_days": 180}
    assert got["dropped"] == {"at": "2026-10-28T12:00:00Z", "retention": {"ci/days": 2}, "size_cap": {"flow/closed": 5}}
    health.write_health(Ws(tmp_path, LATER), {}, {}, {"removed": {}, "dropped": {}})
    assert read(tmp_path)["dropped"]["size_cap"] == {"flow/closed": 5}  # the last time anything went is remembered


def test_a_run_that_changes_nothing_but_the_clock_does_not_rewrite_the_file(tmp_path):
    # Otherwise every run would commit to the data branch only to move a time.
    (tmp_path / "docs").mkdir()
    health.write_health(Ws(tmp_path), {"CI Health": {"runs": 1, "complete": True}}, {}, {})
    before = (tmp_path / "docs" / "health.json").read_text(encoding="utf-8")
    health.write_health(Ws(tmp_path, LATER), {"CI Health": {"runs": 1, "complete": True}}, {}, {})
    assert (tmp_path / "docs" / "health.json").read_text(encoding="utf-8") == before
    health.write_health(Ws(tmp_path, LATER), {}, {"CI Health": "broke"}, {})
    assert read(tmp_path)["sources"]["CI Health"]["error"] == "broke"


def test_a_job_run_writes_the_health_file_with_each_step(tmp_path):
    # Guards the wiring: the runner skips a broken extra page quietly, so its absence must fail here.
    import subprocess

    from stackvitals.core.workspace import run_job
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    env = {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": bare.as_uri(),
           "RUNNER_TEMP": str(tmp_path / "tmp")}

    def step(ws):
        (ws.path / "docs").mkdir(parents=True, exist_ok=True)
        return {"runs": 3, "complete": True}

    def broken(ws):
        raise RuntimeError("GitHub's hourly limit is used up")
    out = run_job(env, [("CI Health", step), ("Team Flow", broken)], NOW)
    assert not any("Data health" in n for n in out["notes"])
    got = json.loads(subprocess.run(["git", "show", "stackvitals-data:docs/health.json"], cwd=bare, capture_output=True,
                                    text=True).stdout)
    assert got["sources"]["CI Health"]["complete"] is True and got["sources"]["CI Health"]["read"] == {"runs": 3}
    assert got["sources"]["Team Flow"]["error"] == "GitHub's hourly limit is used up"


def test_a_step_that_nests_its_collection_stats_is_read_one_level_down(tmp_path):
    # CI Health returns {"collect": {"runs", "requests", "complete"}, "flaky": n, ...}.
    (tmp_path / "docs").mkdir()
    health.write_health(Ws(tmp_path), {"CI Health": {"collect": {"runs": 9, "requests": 20, "complete": False}, "flaky": 1}}, {}, {})
    got = read(tmp_path)["sources"]["CI Health"]
    assert got["complete"] is False and got["read"] == {"flaky": 1, "runs": 9, "requests": 20}
