import importlib.util
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

spec = importlib.util.spec_from_file_location("study", Path(__file__).parents[2] / "bench/accuracy/adoption/study.py")
study = importlib.util.module_from_spec(spec)
spec.loader.exec_module(study)

T = lambda s: datetime.fromisoformat(s).replace(tzinfo=timezone.utc)  # noqa: E731


def test_red_hours_count_time_any_workflow_s_latest_push_run_is_failing():
    runs = [{"wf": 1, "c": "failure", "at": T("2027-01-01T10:00")}, {"wf": 2, "c": "success", "at": T("2027-01-01T11:00")},
            {"wf": 1, "c": "success", "at": T("2027-01-01T14:00")}, {"wf": 2, "c": "failure", "at": T("2027-01-02T00:00")},
            {"wf": 2, "c": "cancelled", "at": T("2027-01-02T01:00")}]
    # Red 10:00-14:00 and from 00:00 to the window's end at 06:00 (a cancelled run doesn't turn it green): 10 hours.
    hours = study.red_hours(runs, T("2027-01-01T00:00"), T("2027-01-02T06:00"))
    assert abs(hours - 10 * 30 / 1.25) < 1e-6  # per 30 days of a 1.25-day window


def test_review_wait_and_newcomers_return_follow_the_protocol():
    prs = [{"repo": "a/b", "created": T("2027-01-01T00:00"), "author": "x", "assoc": "NONE", "bot": False,
            "review_at": T("2027-01-01T05:00"), "review_by": "m", "review_assoc": "MEMBER"},
           {"repo": "a/b", "created": T("2027-01-02T00:00"), "author": "y", "assoc": "NONE", "bot": False,
            "review_at": T("2027-01-02T09:00"), "review_by": "y", "review_assoc": "NONE"},
           {"repo": "a/b", "created": T("2027-01-03T00:00"), "author": "dependabot", "assoc": "NONE", "bot": True,
            "review_at": T("2027-01-03T01:00"), "review_by": "m", "review_assoc": "MEMBER"},
           {"repo": "a/b", "created": T("2027-02-01T00:00"), "author": "x", "assoc": "NONE", "bot": False,
            "review_at": None, "review_by": None, "review_assoc": None},
           {"repo": "a/b", "created": T("2026-06-01T00:00"), "author": "z", "assoc": "NONE", "bot": False,
            "review_at": None, "review_by": None, "review_assoc": None},
           {"repo": "a/b", "created": T("2027-01-04T00:00"), "author": "z", "assoc": "NONE", "bot": False,
            "review_at": None, "review_by": None, "review_assoc": None}]
    wait = study.review_wait(prs, T("2027-01-01T00:00"), T("2027-01-10T00:00"))
    assert wait == {"hours": 5.0, "reviewed": 1, "people_prs": 3}
    # x is new in the window and came back on 02-01; y never came back; z was not new.
    assert study.newcomer_return(prs, T("2027-01-01T00:00"), T("2027-01-10T00:00")) == {"share": 0.5, "newcomers": 2}


def test_comparison_repos_match_language_tier_and_volume_and_closest_wait_wins():
    adopter = {"repo": "a/b", "language": "Go", "tier": "1k-10k", "prs": 40, "wait": 10.0}
    pool = [{"repo": "c/1", "language": "Go", "tier": "1k-10k", "prs": 30, "wait": 11.0},
            {"repo": "c/2", "language": "Go", "tier": "1k-10k", "prs": 100, "wait": 10.0},
            {"repo": "c/3", "language": "Rust", "tier": "1k-10k", "prs": 40, "wait": 10.0},
            {"repo": "c/4", "language": "Go", "tier": "1k-10k", "prs": 20, "wait": 30.0},
            {"repo": "c/5", "language": "Go", "tier": "1k-10k", "prs": 79, "wait": 9.5},
            {"repo": "c/6", "language": "Go", "tier": "1k-10k", "prs": 41, "wait": 12.0}]
    assert [c["repo"] for c in study.match(adopter, pool, k=3)] == ["c/5", "c/1", "c/6"]


def test_comparison_repos_do_not_depend_on_the_pool_s_order():
    adopter = {"repo": "a/b", "language": "Go", "tier": "1k-10k", "prs": 40, "wait": 10.0}
    pool = [{"repo": f"c/{i}", "language": "Go", "tier": "1k-10k", "prs": 40, "wait": 11.0} for i in range(8)]
    assert study.match(adopter, pool) == study.match(adopter, pool[::-1])


def test_bootstrap_p_value_is_two_sided_and_floored_at_one_draw():
    lo, hi, p = study.bootstrap([-1.0 - i * 0.01 for i in range(25)], draws=2000)
    assert hi < 0 and p == 1 / 2000
    assert study.bootstrap([(-1) ** i * 10.0 for i in range(30)], draws=2000)[2] > 0.5


def test_holm_adjusts_across_the_outcomes():
    adj = study.holm({"a": 0.01, "b": 0.04, "c": 0.03})
    assert {k: round(v, 6) for k, v in adj.items()} == {"a": 0.03, "c": 0.06, "b": 0.06}
    # An outcome with no p-value counts as p = 1, so the family stays three.
    assert round(study.holm({"a": 0.02, "b": None, "c": 0.5})["a"], 6) == 0.06


def test_did_reads_each_outcome_with_holm_across_the_three():
    better = [{"adopter": -5.0 + i * 0.1, "controls": [0.0, 1.0]} for i in range(25)]
    worse_return = [{"adopter": -0.5 - i * 0.01, "controls": [0.0]} for i in range(25)]
    noisy = [{"adopter": (-1) ** i * 10.0, "controls": [0.0]} for i in range(30)]
    out = study.did({"red_ci_hours": better, "review_wait_hours": noisy, "newcomer_return": worse_return}, included=30)
    red = out["red_ci_hours"]
    assert red["adopters"] == 25 and red["read"] == "helped" and red["range"][1] < 0
    assert red["p"] == 1 / 2000 and abs(red["p_holm"] - 3 / 2000) < 1e-12
    assert out["review_wait_hours"]["read"] == "no measurable difference" and out["review_wait_hours"]["range"]
    assert out["newcomer_return"]["read"] == "hurt"  # a lower return share is worse


def test_did_counts_included_adopters_not_each_outcome_s_pairs():
    better = [{"adopter": -5.0, "controls": [0.0]} for _ in range(25)]
    few = study.did({"red_ci_hours": better, "review_wait_hours": [], "newcomer_return": []}, included=19)
    assert {o["read"] for o in few.values()} == {"too few adopters to tell"}
    enough = study.did({"red_ci_hours": better[:12], "review_wait_hours": [], "newcomer_return": []}, included=20)
    assert enough["red_ci_hours"]["read"] == "helped" and enough["red_ci_hours"]["adopters"] == 12
    assert enough["review_wait_hours"]["read"] == "no data"


def test_red_hours_is_none_without_runs_in_the_period():
    runs = [{"wf": 1, "c": "failure", "at": T("2026-12-28T00:00")}]
    assert study.red_hours(runs, T("2027-01-01T00:00"), T("2027-01-31T00:00")) is None
    assert study.red_hours([], T("2027-01-01T00:00"), T("2027-01-31T00:00")) is None


def test_red_hours_know_the_state_at_the_start_from_earlier_runs():
    runs = [{"wf": 1, "c": "failure", "at": T("2026-12-28T00:00")},
            {"wf": 1, "c": "success", "at": T("2027-01-01T06:00")}]
    hours = study.red_hours(runs, T("2027-01-01T00:00"), T("2027-01-02T00:00"))
    assert abs(hours - 6 * 30) < 1e-6


def test_runs_start_7_days_early_and_split_a_query_that_hits_the_api_cap(monkeypatch):
    calls = []

    def gh(path, params=None):
        calls.append(params["created"])
        lo, hi = (datetime.fromisoformat(s.replace("Z", "+00:00")) for s in params["created"].split(".."))
        if hi - lo > timedelta(days=40):  # the API stops at 1,000 runs per filtered query
            got = [] if params["page"] > 10 else [{"id": params["page"] * 1000 + i, "workflow_id": 1,
                                                   "conclusion": "success", "updated_at": "2027-01-20T00:00:00Z"}
                                                  for i in range(100)]
        else:
            got = [{"id": int(lo.timestamp()), "workflow_id": 1, "conclusion": "failure",
                    "updated_at": lo.strftime("%Y-%m-%dT%H:%M:%SZ")}]
        return {"workflow_runs": got}

    monkeypatch.setattr(study, "_gh", gh)
    runs = study._runs("a/b", "main", T("2027-01-01T00:00"), T("2027-03-01T00:00"))
    assert calls[0].startswith("2026-12-25T00:00:00Z..")
    assert len(runs) == 2 and len({r["id"] for r in runs}) == 2


def test_find_takes_the_oldest_commit_across_every_page(tmp_path, monkeypatch):
    def gh(path, params=None):
        if path == "/search/code":
            return {"items": [{"path": ".github/workflows/sv.yml",
                               "repository": {"full_name": "o/r", "fork": False}}]}
        # A full first page of newer commits, then the file's first commit alone on page 2.
        if params["page"] == 1:
            return [{"commit": {"committer": {"date": f"2027-01-01T00:{i // 60:02d}:{i % 60:02d}Z"}}} for i in range(100)]
        return [{"commit": {"committer": {"date": "2026-11-05T00:00:00Z"}}}]

    monkeypatch.setattr(study, "_gh", gh)
    monkeypatch.setattr(study, "ADOPTERS", tmp_path / "adopters.json")
    monkeypatch.setattr(study, "RESULTS", tmp_path / "results.json")
    assert study.find(today=date(2027, 7, 2)) == 0
    found = json.loads((tmp_path / "adopters.json").read_text())
    assert found == [{"repo": "o/r", "installed": "2026-11-05T00:00:00Z"}]


def test_score_refuses_early_or_when_the_protocol_changed(tmp_path, monkeypatch):
    assert study.score(None, None, today=date(2027, 6, 30)) == 2
    monkeypatch.setattr(study, "MANIFEST", tmp_path / "m.json")
    monkeypatch.setattr(study, "RESULTS", tmp_path / "results.json")
    (tmp_path / "m.json").write_text('{"preregistration_sha256": "x", "study_sha256": "y"}', encoding="utf-8")
    assert study.score(None, None, today=date(2027, 7, 2)) == 3


def test_a_finished_read_stands(tmp_path, monkeypatch):
    monkeypatch.setattr(study, "MANIFEST", tmp_path / "m.json")
    monkeypatch.setattr(study, "RESULTS", tmp_path / "results.json")
    monkeypatch.setattr(study, "ADOPTERS", tmp_path / "adopters.json")
    (tmp_path / "m.json").write_text(json.dumps(study._hashes()), encoding="utf-8")
    # After the last read day nothing is scored again.
    assert study.score(None, None, today=date(2028, 7, 2)) == 4
    assert study.find(today=date(2028, 7, 2)) == 4
    # A read that included 20 or more adopters is final.
    (tmp_path / "results.json").write_text('{"included": 20}', encoding="utf-8")
    assert study.score(None, None, today=date(2027, 10, 2)) == 4
    assert study.find(today=date(2027, 10, 2)) == 4
    (tmp_path / "results.json").write_text('{"included": 7}', encoding="utf-8")
    monkeypatch.setattr(study, "_crawl", lambda crawl: ({}, {}))
    (tmp_path / "adopters.json").write_text("[]", encoding="utf-8")
    assert study.score(None, None, today=date(2027, 10, 2)) == 0


def _prs(first: str, n: int, wait_hours: float | None) -> list[dict]:
    start = T(first)
    return [{"created": start + timedelta(days=i * 3), "author": f"u{i}", "assoc": "NONE", "bot": False,
             "review_at": start + timedelta(days=i * 3, hours=wait_hours) if wait_hours is not None else None,
             "review_by": "m" if wait_hours is not None else None,
             "review_assoc": "MEMBER" if wait_hours is not None else None} for i in range(n)]


def test_score_reports_included_adopters_and_why_others_were_left_out(tmp_path, monkeypatch):
    monkeypatch.setattr(study, "MANIFEST", tmp_path / "m.json")
    monkeypatch.setattr(study, "RESULTS", tmp_path / "results.json")
    (tmp_path / "m.json").write_text(json.dumps(study._hashes()), encoding="utf-8")
    meta = {n: {"language": "Go", "tier": "1k-10k", "branch": "main"} for n in ("a/1", "a/2", "c/1", "c/2")}
    meta["a/3"] = {"language": "Rust", "tier": "1k-10k", "branch": "main"}
    prs = {"a/1": _prs("2026-10-05T00:00", 15, 5.0) + _prs("2027-02-15T00:00", 15, 2.0),
           "a/2": _prs("2026-10-05T00:00", 15, None) + _prs("2027-02-15T00:00", 15, None),
           "a/3": _prs("2026-10-05T00:00", 15, 5.0),
           "c/1": _prs("2026-10-05T00:00", 15, 6.0) + _prs("2027-02-15T00:00", 15, 6.0),
           "c/2": _prs("2026-10-05T00:00", 15, 4.0) + _prs("2027-02-15T00:00", 15, 4.0)}
    monkeypatch.setattr(study, "_crawl", lambda crawl: (meta, prs))
    monkeypatch.setattr(study, "_runs", lambda *a: [])
    adopters = tmp_path / "adopters.json"
    adopters.write_text(json.dumps([{"repo": r, "installed": "2027-01-02T00:00:00Z"} for r in ("a/1", "a/2", "a/3")]),
                        encoding="utf-8")
    assert study.score(None, adopters, today=date(2027, 10, 2)) == 0
    out = json.loads((tmp_path / "results.json").read_text())
    assert out["included"] == 1 and out["adopters_found"] == 3
    assert out["left_out"] == {"no review wait before installing": 1, "no comparison repo": 1}
    assert out["outcomes"]["review_wait_hours"]["adopters"] == 1
    assert out["outcomes"]["red_ci_hours"]["adopters"] == 0
    assert {o["read"] for o in out["outcomes"].values()} == {"too few adopters to tell"}
