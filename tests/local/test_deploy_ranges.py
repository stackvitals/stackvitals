"""Which commits each deployment shipped: the commits between it and the production deployment before it, read once
with one batched query and kept; a PR belongs to the deployment whose range holds its merge commit (DevLake's rule),
so a deploy of an older commit or a rollback no longer takes the PRs merged before it."""
from types import SimpleNamespace

from stackvitals.core import delivery
from stackvitals.core.config import parse as parse_cfg
from stackvitals.flow import collect

# Mainline, newest first: c6 c5 c4 c3 c2 c1.
HISTORY = {"c6": ["c6", "c5", "c4", "c3", "c2", "c1"], "c4": ["c4", "c3", "c2", "c1"], "c2": ["c2", "c1"]}


class Gql:
    def __init__(self):
        self.queries = 0

    def query(self, q, variables):
        assert "rateLimit { cost remaining resetAt }" in q
        self.queries += 1
        repo = {}
        for i, sha in enumerate(collect.RANGE_OID.findall(q)):
            repo[f"d{i}"] = {"history": {"nodes": [{"oid": x} for x in HISTORY[sha]]}}
        return SimpleNamespace(data={"repository": repo})


def dep(sha, day, env="production"):
    return {"env": env, "sha": sha, "at": f"2026-10-{day:02d}T10:00:00Z", "done": f"2026-10-{day:02d}T10:00:00Z", "state": "SUCCESS"}


def test_ranges_are_read_once_for_each_pair_of_production_deployments():
    deps = [dep("c6", 20), dep("c5", 19, "Preview"), dep("c4", 15), dep("c2", 10)]
    gql = Gql()
    got = collect.deploy_ranges(gql, "o", "r", deps, {})
    assert got == {"c4..c6": {"shas": ["c6", "c5"], "complete": True}, "c2..c4": {"shas": ["c4", "c3"], "complete": True}}
    assert gql.queries == 1
    again = Gql()
    assert collect.deploy_ranges(again, "o", "r", deps, got) == got and again.queries == 0


def test_a_pr_goes_to_the_deployment_whose_range_holds_its_merge_commit():
    cfg = parse_cfg("")[0]
    repo = {"deployments": [dep("c6", 20), dep("c4", 15), dep("c2", 10)],
            "ranges": {"c4..c6": {"shas": ["c6", "c5"], "complete": True}, "c2..c4": {"shas": ["c4", "c3"], "complete": True}}}
    deps, _ = delivery.find_deployments(repo, {}, cfg)
    # c5 merged on the 12th but was deployed only on the 20th; the time rule would say the 15th.
    pr = {"n": 7, "mc": "c5", "mg": "2026-10-12T00:00:00Z"}
    assert delivery.deployment_of(pr, deps)["sha"] == "c6"
    # A merge commit outside every known range falls back to the time rule.
    assert delivery.deployment_of({"n": 8, "mc": "zz", "mg": "2026-10-12T00:00:00Z"}, deps)["sha"] == "c4"
