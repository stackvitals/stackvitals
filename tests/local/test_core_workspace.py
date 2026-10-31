"""One checkout and one commit per job, shared by every module; what happens after the commit runs after it; overlapping
runs converge; nothing is lost when a step fails or the same event is processed twice."""
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from stackvitals.core.workspace import Workspace, run_job

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)


def remote(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    return bare


def show(bare, path):
    return subprocess.run(["git", "show", f"stackvitals-data:{path}"], cwd=bare, capture_output=True, text=True).stdout


def commits(bare):
    out = subprocess.run(["git", "rev-list", "--count", "stackvitals-data"], cwd=bare, capture_output=True, text=True).stdout
    return int(out.strip() or 0)


def env_for(tmp_path, bare):
    return {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": bare.as_uri(),
            "RUNNER_TEMP": str(tmp_path / "tmp")}


def writer(name, hooks):
    def step(ws: Workspace):
        (ws.path / f"{name}.txt").write_text(f"{name} data\n", encoding="utf-8")
        ws.after_commit(lambda: hooks.append(name), label=name)
        return {name: True}
    return step


def test_two_modules_share_one_checkout_and_one_commit_and_hooks_run_after_it(tmp_path):
    bare, hooks = remote(tmp_path), []
    out = run_job(env_for(tmp_path, bare), [("ci", writer("ci", hooks)), ("flow", writer("flow", hooks))], NOW)
    assert out["outcome"] == "pushed" and out["results"] == {"ci": {"ci": True}, "flow": {"flow": True}} and out["errors"] == {}
    assert commits(bare) == 1 and show(bare, "ci.txt") == "ci data\n" and show(bare, "flow.txt") == "flow data\n"
    assert hooks == ["ci", "flow"]
    again = run_job(env_for(tmp_path, bare), [("ci", writer("ci", hooks)), ("flow", writer("flow", hooks))], NOW)
    assert again["outcome"] == "unchanged" and commits(bare) == 1 and hooks == ["ci", "flow", "ci", "flow"]


def test_a_failing_step_does_not_lose_the_other_steps_work_and_is_reported(tmp_path):
    bare, hooks = remote(tmp_path), []

    def bad(ws):
        (ws.path / "half.txt").write_text("partial\n", encoding="utf-8")
        raise RuntimeError("GitHub said 502")
    out = run_job(env_for(tmp_path, bare), [("ci", writer("ci", hooks)), ("flow", bad)], NOW)
    assert out["outcome"] == "pushed" and "GitHub said 502" in out["errors"]["flow"] and out["results"] == {"ci": {"ci": True}}
    assert show(bare, "ci.txt") == "ci data\n" and show(bare, "half.txt") == "partial\n" and hooks == ["ci"]


def test_overlapping_runs_converge_without_losing_either_side(tmp_path):
    bare, hooks, seen = remote(tmp_path), [], []
    run_job(env_for(tmp_path, bare), [("ci", writer("ci", hooks))], NOW)

    def racing(ws):
        seen.append(1)
        if len(seen) == 1:
            # Another run pushes while this one works; the push is rejected and the steps run again on fresh data.
            run_job(env_for(tmp_path / "other", bare), [("other", writer("other", []))], NOW)
        (ws.path / "mine.txt").write_text(f"attempt {len(seen)}\n", encoding="utf-8")
        return {"attempts": len(seen)}
    out = run_job(env_for(tmp_path, bare), [("mine", racing)], NOW)
    assert out["outcome"] == "pushed" and out["results"]["mine"] == {"attempts": 2}
    assert show(bare, "other.txt") == "other data\n" and show(bare, "mine.txt") == "attempt 2\n" and show(bare, "ci.txt") == "ci data\n"


def test_a_hook_that_fails_is_noted_and_the_next_hooks_still_run(tmp_path):
    bare, hooks = remote(tmp_path), []

    def step(ws):
        (ws.path / "x.txt").write_text("x\n", encoding="utf-8")
        ws.after_commit(lambda: (_ for _ in ()).throw(OSError("chat down")), label="webhook")
        ws.after_commit(lambda: hooks.append("summary"), label="summary")
        return {}
    out = run_job(env_for(tmp_path, bare), [("ci", step)], NOW)
    assert hooks == ["summary"] and out["notes"] == ["webhook: chat down"]
    assert not Path(env_for(tmp_path, bare)["RUNNER_TEMP"]).exists() or not list(Path(env_for(tmp_path, bare)["RUNNER_TEMP"]).glob("stackvitals-*"))


def test_the_job_keeps_house_retention_cap_counter_and_an_opt_in_squash(tmp_path):
    import json
    from stackvitals.core.store import META, SQUASH_EVERY
    bare = remote(tmp_path)

    def seed(ws):
        for stream, day in (("ci/days", "2024-01-01"), ("ci/days", "2026-10-19"), ("flow/closed", "2026-10-18")):
            (ws.path / stream).mkdir(parents=True, exist_ok=True)
            (ws.path / stream / f"{day}.ndjson").write_text("x" * 3000 + "\n", encoding="utf-8")
        return {}
    env = env_for(tmp_path, bare) | {"STACKVITALS_SIZE_CAP_MB": "0.005"}  # about 5 KB: one of the two kept files must go
    out = run_job(env, [("seed", seed)], NOW)
    assert out["outcome"] == "pushed" and out["housekeeping"]["removed"] == {"ci/days": 1}
    assert out["housekeeping"]["dropped"] == ["flow/closed/2026-10-18.ndjson"]
    assert json.loads(show(bare, META))["commits"] == 1 and show(bare, "ci/days/2026-10-19.ndjson")
    # Squash is opt-in and waits for the counter; when it fires, the files stay the same and the history is one commit.
    out = run_job(env | {"STACKVITALS_SQUASH": "true"}, [("touch", lambda ws: (ws.path / "t.txt").write_text("1\n") or {})], NOW)
    assert commits(bare) == 2 and out["housekeeping"]["squashed"] is False

    def many(ws):
        meta = json.loads((ws.path / META).read_text(encoding="utf-8"))
        (ws.path / META).write_text(json.dumps({**meta, "commits": SQUASH_EVERY - 1}), encoding="utf-8")
        return {}
    out = run_job(env | {"STACKVITALS_SQUASH": "true"}, [("many", many)], NOW)
    assert out["housekeeping"]["squashed"] is True and commits(bare) == 1
    assert show(bare, "ci/days/2026-10-19.ndjson") == "x" * 3000 + "\n" and show(bare, "t.txt") == "1\n"
    assert json.loads(show(bare, META))["commits"] == 0
