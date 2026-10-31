"""Deployment history: a repo with many preview deployments kept only its newest 100 of any environment, so most
production deployments were lost (nodejs.org: 14 of 114 in 90 days, found in the DevLake side-by-side). Now pages
go back to the window, and each run adds to what earlier runs saved."""
from datetime import datetime, timezone
from types import SimpleNamespace

from stackvitals.flow import collect

NOW = datetime(2026, 10, 28, tzinfo=timezone.utc)


def dep(day: int, env: str = "Preview", sha: str = "a") -> dict:
    at = f"2026-{10 - day // 28:02d}-{28 - day % 28:02d}T12:00:00Z"
    return {"environment": env, "createdAt": at, "commitOid": sha, "latestStatus": {"state": "SUCCESS", "createdAt": at}}


class Gql:
    """Answers the repo query with the newest page and each later page in turn, like GitHub."""
    def __init__(self, nodes: list[dict], size: int = 100):
        self.pages = [nodes[i:i + size] for i in range(0, len(nodes), size)] or [[]]
        self.calls = 0

    def query(self, q, variables):
        assert "rateLimit { cost remaining resetAt }" in q
        i = int(variables.get("after") or 0)
        self.calls += 1
        block = {"nodes": self.pages[i], "pageInfo": {"hasNextPage": i + 1 < len(self.pages), "endCursor": str(i + 1)}}
        if "after" in variables:
            return SimpleNamespace(data={"repository": {"deployments": block}})
        return SimpleNamespace(data={"repository": {"defaultBranchRef": {"name": "main"}, "deployments": block,
                                                    "releases": {"nodes": []}}})


def test_pages_back_to_the_window_so_production_among_previews_is_kept():
    nodes = [dep(d, "Production" if d % 9 == 0 else "Preview", str(k)) for d in range(0, 84) for k in range(4)]
    info = collect.repo_info(Gql(nodes), "o", "r", since="2026-08-01T00:00:00Z")
    prod = [d for d in info["deployments"] if d["env"] == "Production"]
    assert len(prod) == 4 * len([d for d in range(0, 84) if d % 9 == 0])


def test_stops_at_the_window_and_at_what_was_saved():
    nodes = [dep(d) for d in range(0, 84) for _ in range(4)]
    gql = Gql(nodes)
    collect.repo_info(gql, "o", "r", since="2026-10-20T00:00:00Z")
    assert gql.calls == 1
    saved = {"deployments": [{"env": "Preview", "at": "2026-10-10T12:00:00Z", "sha": "a", "state": "SUCCESS",
                              "done": "2026-10-10T12:00:00Z"}], "deployments_from": "2026-01-01T00:00:00Z"}
    gql = Gql(nodes)
    collect.repo_info(gql, "o", "r", since="2026-01-01T00:00:00Z", saved=saved)
    assert gql.calls <= 2


def test_a_save_from_before_paging_is_filled_back_to_the_window():
    nodes = [dep(d, sha=str(k)) for d in range(0, 84) for k in range(4)]
    saved = {"deployments": [{"env": "Preview", "at": "2026-10-28T12:00:00Z", "sha": "0", "state": "SUCCESS"}]}
    gql = Gql(nodes)
    info = collect.repo_info(gql, "o", "r", since="2026-08-01T00:00:00Z", saved=saved)
    assert gql.calls == 4 and len(info["deployments"]) == 336
    assert info["deployments_from"] == "2026-08-01T00:00:00Z"


def test_merge_keeps_earlier_runs_and_updates_a_changed_status():
    old = [{"env": "production", "at": "2026-06-01T00:00:00Z", "sha": "x", "state": "SUCCESS", "done": "2026-06-01T00:00:00Z"},
           {"env": "production", "at": "2026-10-27T00:00:00Z", "sha": "y", "state": "SUCCESS", "done": "2026-10-27T00:00:00Z"}]
    new = [{"env": "production", "at": "2026-10-27T00:00:00Z", "sha": "y", "state": "INACTIVE", "done": "2026-10-28T00:00:00Z"}]
    got = collect.merge_history(old, new, keep_since="2025-10-01T00:00:00Z")
    assert [(d["sha"], d["state"]) for d in got] == [("y", "INACTIVE"), ("x", "SUCCESS")]
    assert collect.merge_history(old, new, keep_since="2026-07-01T00:00:00Z") == new


def test_releases_from_earlier_runs_are_kept_past_the_newest_100():
    old = [{"tag": "v1.0.0", "at": "2026-05-01T00:00:00Z", "pre": False, "sha": "s1"}]
    new = [{"tag": "v1.0.1", "at": "2026-10-01T00:00:00Z", "pre": False, "sha": "s2"}]
    got = collect.merge_history(old, new, "2025-11-01T00:00:00Z", ("tag",))
    assert [r["tag"] for r in got] == ["v1.0.1", "v1.0.0"]
