"""A pull request the team excludes (the `stackvitals: exclude` label or `/stackvitals exclude`) leaves the numbers in
Team Flow, Delivery, Alerts and Insights, and the pages say how many were left out; `include` brings it back."""
import json

from test_flow_wiring import NOW, Pages, node, remote, show

from stackvitals.core import decisions as dec
from stackvitals.core.workspace import run_job
from stackvitals.flow.action import flow_step


def state(*rows):
    return {f"pr:{n}": {"verb": verb, "kind": "pr", "id": str(n), "until": None, "by": "alice", "reason": ""} for n, verb in rows}


def test_label_and_decisions_decide_which_pull_requests_leave_the_numbers():
    prs = [{"n": 1, "lb": ["stackvitals: exclude"]}, {"n": 2, "lb": []}, {"n": 3, "lb": ["stackvitals: exclude"]}]
    assert dec.excluded_prs(state((2, "exclude"), (3, "include")), prs) == {1, 2}
    flow = {"open": [{"n": 1}, {"n": 4}], "closed": [{"n": 2}, {"n": 5}]}
    assert dec.drop_prs(flow, {1, 2}) == {"open": [{"n": 4}], "closed": [{"n": 5}], "excluded": 2}


def test_team_flow_leaves_out_an_excluded_pull_request_and_says_so(tmp_path):
    bare = remote(tmp_path)
    env = {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": bare.as_uri(),
           "GITHUB_EVENT_NAME": "schedule", "RUNNER_TEMP": str(tmp_path / "tmp")}
    prs = [node(1, requests=["carol"]), node(2, "MERGED", updated=50, merged=50, reviews=[(90, "bob")])]

    def seed(ws):
        dec.Store(ws.path).record([dec.Decision("exclude", "pr", "2", None, "release PR")], by="alice", source="test", now=NOW)
    run_job(env, [("Team Flow", lambda ws: flow_step(ws, env, NOW, make_gql=lambda tok: Pages(prs)))], NOW, prepare=seed)
    flow = json.loads(show(bare, "docs/flow.json"))
    assert flow["merged"] == 0 and flow["excluded"] == 1
    assert "1 pull request left out by the team" in show(bare, "docs/flow.html")
