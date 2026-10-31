from stackvitals.ci.feedback import TRACK_RECORD, render_comment

ITEMS = [{"kind": "job", "job_id": 1, "name": "CI / build", "verdict": "new",
          "detail": "no earlier flakes: likely from this change; the default branch failed in this step 3 hours before this "
                    "(run 7), with a different error; gemini-3.5-flash-lite read the log: likely this change (the test covers it)",
          "model": {"model": "gemini-3.5-flash-lite", "caused_by_change": "yes", "cause": "code_change", "why": "w"}},
         {"kind": "test", "name": "t::sync", "verdict": "known flaky",
          "detail": "flaked 5 times in 40 runs in the last 30 days: likely a flake, but check the error isn't from this change, then re-run it; looks like a timing flake", "flake": "timing"}]


def test_each_failure_is_one_short_row_with_the_rest_folded_below():
    body = render_comment(ITEMS, "o/r")
    rows = [line for line in body.splitlines() if line.startswith("| ") and "---" not in line][1:]
    assert len(rows) == 2 and "likely from this change |" in rows[0] and "default branch" not in rows[0]
    folded = body[body.index("<details>"):]
    assert "different error" in folded and "read the log" in folded and "timing flake" in folded


def test_the_folded_part_says_how_often_each_verdict_shown_has_held():
    folded = render_comment(ITEMS, "o/r").split("<details>", 1)[1]
    assert TRACK_RECORD["new"] in folded and TRACK_RECORD["known flaky"] in folded and TRACK_RECORD["model"] in folded
    assert TRACK_RECORD["outside failure"] not in folded


def test_a_long_list_stays_readable():
    many = [{"kind": "test", "name": f"t::{n}", "verdict": "new", "detail": "no earlier flakes: likely from this change"}
            for n in range(40)]
    body = render_comment(many, "o/r")
    assert body.count("| New |") == 25 and "and 15 more" in body
