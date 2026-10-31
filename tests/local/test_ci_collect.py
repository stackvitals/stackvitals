import gzip
from datetime import timedelta

import httpx
from ci_fake import T0, FakeGitHub, Run, job
from stackvitals.ci.api import ActionsAPI
from stackvitals.ci.collect import collect
from stackvitals.ci.store import DataStore

COLLECT_NOW = T0 + timedelta(days=3)


def api_for(fake, **kw):
    return ActionsAPI("tok", "o/r", client=httpx.Client(transport=fake.transport()), sleep=lambda s: None, **kw)


def two_runs():
    a = Run(1, T0, [("failure", [job(11, "test (3.11)", "failure", T0, 60)]),
                    ("success", [job(12, "test (3.11)", "success", T0 + timedelta(minutes=10), 60, attempt=2)])])
    b = Run(2, T0 + timedelta(days=1), [("success", [job(21, "test (3.11)", "success", T0 + timedelta(days=1), 70)])])
    own = Run(3, T0 + timedelta(days=1), [("success", [job(31, "vitals", "success", T0 + timedelta(days=1), 30)])],
              path=".github/workflows/stackvitals.yml", name="StackVitals")
    return [a, b, own]


def test_a_second_collect_fetches_only_new_attempts(tmp_path):
    fake = FakeGitHub(two_runs())
    store = DataStore(tmp_path)
    collect(api_for(fake), store, COLLECT_NOW, days=5)
    first = len(fake.calls)
    collect(api_for(fake), store, COLLECT_NOW, days=5)
    job_calls = [c for c in fake.calls[first:] if "/jobs" in c or "/attempts/" in c]
    assert job_calls == [] and len(store.load()["jobs"]) == 4


# GitHub returns at most 1,000 runs per filtered query, so runs are listed one day at a time.
def test_runs_are_listed_one_day_at_a_time(tmp_path):
    fake = FakeGitHub(two_runs())
    collect(api_for(fake), DataStore(tmp_path), COLLECT_NOW, days=3)
    days = sorted({c.split("created=")[1].split("&")[0] for c in fake.calls if "created=" in c})
    assert days == ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"]


def test_secondary_rate_limits_are_waited_out(tmp_path):
    fake = FakeGitHub(two_runs(), fail_first=2)
    stats = collect(api_for(fake), DataStore(tmp_path), COLLECT_NOW, days=5)
    assert stats["complete"] and stats["runs"] == 3


def test_closed_days_are_compressed_and_still_readable(tmp_path):
    store = DataStore(tmp_path)
    store.add([{"t": "run", "id": 5, "att": 1, "cr": "2026-09-01T00:00:00Z"}], day="2026-09-01")
    store.add([{"t": "run", "id": 6, "att": 1, "cr": "2026-10-04T00:00:00Z"}], day="2026-10-04")
    store.compact(today="2026-10-04", retention_days=180)
    assert (tmp_path / "ci" / "days" / "2026-09-01.ndjson.gz").exists()
    assert (tmp_path / "ci" / "days" / "2026-10-04.ndjson").exists()
    assert gzip.decompress((tmp_path / "ci" / "days" / "2026-09-01.ndjson.gz").read_bytes())
    assert sorted(r["id"] for r in store.load()["runs"]) == [5, 6]
    store.compact(today="2027-06-01", retention_days=180)
    assert store.load()["runs"] == []


def test_parallel_fetching_stores_the_same_history(tmp_path):
    a, b = DataStore(tmp_path / "a"), DataStore(tmp_path / "b")
    collect(api_for(FakeGitHub(two_runs())), a, COLLECT_NOW, days=5, workers=1)
    collect(api_for(FakeGitHub(two_runs())), b, COLLECT_NOW, days=5, workers=8)
    key = lambda d: (sorted((r["id"], r["att"]) for r in d["runs"]), sorted(j["id"] for j in d["jobs"]))
    assert key(a.load()) == key(b.load())


# Real run (astral-sh/ruff, 2026-10-16): a busy repo took over 10 minutes with no output at all.
def test_progress_is_reported_for_each_day_read(tmp_path):
    lines = []
    collect(api_for(FakeGitHub(two_runs())), DataStore(tmp_path), COLLECT_NOW, days=3, log=lines.append)
    assert any("2026-10-02" in l and "2 run" in l for l in lines) and len(lines) == 4
