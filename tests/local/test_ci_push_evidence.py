from datetime import datetime, timezone

from stackvitals.ci.bench import push_stats

NOW = datetime(2026, 10, 28, tzinfo=timezone.utc)


def run(rid, sha, c, day, att=1, br="main", path=".github/workflows/ci.yml"):
    t = f"2026-10-{day:02d}T10:00:00Z"
    return {"id": rid, "att": att, "ev": "push", "sha": sha, "br": br, "c": c, "cr": t, "st": t, "up": f"2026-10-{day:02d}T10:05:00Z", "path": path}


def test_the_first_try_share_names_the_pushes_that_were_not_green_first_time():
    runs = [run(i, f"{i:040x}", "success", 10 + i) for i in range(1, 6)]
    runs += [run(20, "f" * 40, "failure", 20), run(21, "f" * 40, "success", 20, path=".github/workflows/lint.yml"),
             run(30, "e" * 40, "success", 22, att=2)]
    out = push_stats({"runs": runs}, NOW, days=30)
    assert out["pushes"] == 7 and round(out["first_try_share"] * 7) == 5
    # Newest first: the re-run push (run 30, attempt 2), then the failed one (run 20).
    assert out["not_first_try"] == [["eeeeeeeeeeee", "main", [30]], ["ffffffffffff", "main", [20]]]
    assert out["not_first_try_total"] == 2
