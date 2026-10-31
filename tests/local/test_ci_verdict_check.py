"""The opt-in "StackVitals verdict" check: it passes when a pull request's newest code is green and fails otherwise,
known flakes included (they are re-run), so a team can require one check across workflows and merge queues."""
from stackvitals.ci.feedback import verdict_payload


def item(verdict, name="CI / tests"):
    return {"verdict": verdict, "kind": "job", "name": name}


def test_only_green_passes_and_known_flakes_ask_for_a_re_run():
    assert verdict_payload([], True)["conclusion"] == "success"
    ok = verdict_payload([item("known flaky"), item("known flaky", "CI / lint")], False)
    assert ok["conclusion"] == "failure" and "re-run" in ok["output"]["title"]
    bad = verdict_payload([item("known flaky"), item("new", "CI / build")], False)
    assert bad["conclusion"] == "failure" and "CI / build" in bad["output"]["summary"]
    assert verdict_payload([item("failing on main")], False)["conclusion"] == "failure"
    assert bad["name"] == "StackVitals verdict"
