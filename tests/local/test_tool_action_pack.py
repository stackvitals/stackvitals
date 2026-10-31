from mergescout.tool.action_pack import build_action_pack
from mergescout.tool.queries import Snapshot
from mergescout.tool.refs import parse_ref
from tool_data import ISSUE, REPO, make_snapshot

WALLED = {**REPO, "walls_json": '[{"wall": "cla", "blocking": true, "evidence": "Sign the CLA here"},'
                                ' {"wall": "ai_policy", "blocking": false, "evidence": "Disclose AI use in the PR"}]',
          "labels_json": '[{"label": "good first issue", "enough": true, "median_fix_lines": 24, "median_fix_files": 2}]'}


def test_pack_warns_when_the_issue_is_taken(tmp_path):
    snap = Snapshot(make_snapshot(tmp_path / "s.sqlite"))
    pack = build_action_pack(snap, parse_ref("octo/widgets#7"), {"available": False, "reasons": ["open PR"],
                                                                 "source": "github graphql"})
    assert pack["next_steps"][0].startswith("Stop: this issue is not free right now (open PR)")
