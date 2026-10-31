"""Code survival: of the lines a squash-merged PR added, how many git blame still gives to it 30 and 90 days later,
people's PRs against agents'."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace

from stackvitals.flow import survival

NOW = datetime(2026, 10, 29, tzinfo=timezone.utc)
MC = "a" * 40


def pr(n, days_ago, mc=MC, add=10, paths=("src/a.py",), agent=False):
    return {"n": n, "mg": _ago(days_ago), "mc": mc, "add": add, "paths": list(paths), "agent": agent}


def _ago(days):
    from datetime import timedelta
    return (NOW - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


class Gql:
    def __init__(self, parents=1, kept_lines=6):
        self.parents, self.kept = parents, kept_lines

    def query(self, q, variables):
        assert "rateLimit { cost remaining resetAt }" in q and 'blame(path: "src/a.py")' in q
        ranges = [{"startingLine": 1, "endingLine": self.kept, "commit": {"oid": MC}},
                  {"startingLine": self.kept + 1, "endingLine": 50, "commit": {"oid": "b" * 40}}]
        return SimpleNamespace(data={"repository": {"m": {"parents": {"totalCount": self.parents}},
                                                    "h": {"target": {"f0": {"ranges": ranges}}}}})


def test_each_pr_is_measured_once_at_30_and_once_at_90_days(tmp_path):
    prs = [pr(1, 35), pr(2, 95), pr(3, 10), pr(4, 140)]
    saved = survival.collect(Gql(), tmp_path, "o", "r", prs, NOW)
    assert saved == {"1": {"30": {"kept": 6, "added": 10, "files": 1, "all_files": True}},
                     "2": {"90": {"kept": 6, "added": 10, "files": 1, "all_files": True}}}
    assert survival.due(prs, saved, NOW) == []
    assert json.loads((tmp_path / "survival.json").read_text()) == saved


def test_a_pr_merged_with_a_merge_commit_is_skipped_not_counted_as_rewritten(tmp_path):
    saved = survival.collect(Gql(parents=2), tmp_path, "o", "r", [pr(1, 35)], NOW)
    assert saved == {"1": {"30": {"skipped": True}}}


def test_summary_splits_people_and_agents():
    prs = [pr(1, 35), pr(2, 40, agent=True)]
    saved = {"1": {"30": {"kept": 9, "added": 10, "all_files": True}}, "2": {"30": {"kept": 4, "added": 10, "all_files": True}}}
    got = survival.summary(saved, prs, lambda p: "agent" if p["agent"] else "person")
    assert got == {"30": {"people": {"prs": 1, "share": 0.9}, "agents": {"prs": 1, "share": 0.4}}}
