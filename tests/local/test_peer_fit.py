from stackvitals.ci import bench
from stackvitals.ci.report import _bench

Q = {"p10": 20, "p25": 30, "p50": 60, "p75": 90, "p90": 120}
STATS = {"median_s": 50, "first_try_share": 0.9, "pushes": 80}


def _bench_file(keys):
    return {"built_at": "2026-10-23", "groups": {k: {"repos": 40, "median_s": Q, "first_try_share": {"p10": 0.5, "p25": 0.7, "p50": 0.8, "p75": 0.9, "p90": 0.95}}
                                                for k in keys}}


def test_a_close_group_has_no_note_and_a_wider_one_says_it_is_a_loose_fit(monkeypatch):
    monkeypatch.setattr(bench, "_valid", lambda b: b)
    size = bench.tier(500)
    close = bench.compare(STATS, _bench_file([f"Python|{size}"]), "Python", 500)
    loose = bench.compare(STATS, _bench_file(["all|all"]), "Python", 500)
    assert close["fit"] == "" and "loose fit" in loose["fit"]
    head, _lines = _bench({"benchmark": loose})
    assert "loose fit" in head and "active public open-source repos" in head
