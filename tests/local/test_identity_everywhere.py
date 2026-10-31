"""The repo's [identity] settings reach Team Flow, Community and the summary tables, not just Delivery: an old login is
merged into the current one and a login declared a bot stops counting as a human reviewer."""
import json
import subprocess

from test_flow_wiring import NOW, Pages, node, remote, show

from stackvitals.core.config import parse
from stackvitals.core.workspace import run_job
from stackvitals.flow.action import flow_step

SETTINGS = '[identity]\nbots = ["bob"]\n[identity.aliases]\nalice = "alice-new"\n'


def test_flow_and_the_summary_table_use_the_identity_settings(tmp_path):
    bare = remote(tmp_path)
    env = {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": bare.as_uri(),
           "GITHUB_EVENT_NAME": "schedule", "RUNNER_TEMP": str(tmp_path / "tmp")}
    prs = [node(1, requests=["carol"]), node(2, "MERGED", updated=50, merged=50, reviews=[(90, "bob")])]
    out = run_job(env, [("Team Flow", lambda ws: flow_step(ws, env, NOW, make_gql=lambda tok: Pages(prs)))], NOW,
                  prepare=lambda ws: ws.cache.update(settings=parse(SETTINGS)[0]))
    assert out["errors"] == {}
    rows = [json.loads(line) for line in show(bare, "summary/prs.jsonl").splitlines()]
    assert {r["author"] for r in rows} == {"alice-new"}
    flow = json.loads(show(bare, "docs/flow.json"))
    assert flow["stages"]["pickup"]["n"] == 0  # bob is a bot now, so PR 2 had no human review
    raw = subprocess.run(["git", "show", "stackvitals-data:flow/open.json"], cwd=bare, capture_output=True, text=True).stdout
    assert json.loads(raw)[0]["au"] == "alice"  # the stored history keeps what GitHub said


def test_community_leaves_out_a_login_the_repo_calls_a_bot(tmp_path):
    from test_community_action import NOW as C_NOW
    from test_community_action import Fake, env_for, rest

    from stackvitals.community.action import community_step
    bare = remote(tmp_path)
    env = env_for(tmp_path, bare)

    def run(toml):
        return run_job(env, [("Community", lambda ws: community_step(ws, env, C_NOW, make_gql=lambda tok: Fake(),
                                                                       make_api=rest(), flow_ran=False))],
                       C_NOW, prepare=lambda ws: ws.cache.update(settings=parse(toml)[0]))["results"]["Community"]
    assert run("")["waiting"] == 2  # PR 1 by "fresh" and issue 5 by "newbie" wait for a first answer
    assert run('[identity]\nbots = ["newbie"]\n')["waiting"] == 1
