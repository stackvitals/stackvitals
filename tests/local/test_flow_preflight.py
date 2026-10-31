from datetime import datetime, timedelta, timezone

from mergescout.github.graphql import GraphQLResult
from stackvitals.flow.preflight import asks_from, categories, collect_asks, preflight
from stackvitals.flow.store import FlowStore

NOW = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)


def at(days):
    return (NOW - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_review_text_is_sorted_into_plain_categories():
    assert categories("Could you add a test for this edge case?") == {"tests"}
    assert categories("Please add a changelog entry and update the docs") == {"changelog", "docs"}
    assert categories("nit: rename this variable") == {"style"}
    assert categories("LGTM, thanks!") == set()


def pr_node(n, reviews=(), threads=()):
    return {"number": n, "reviews": {"nodes": [{"body": b, "state": s, "authorAssociation": a, "author": {"__typename": k, "login": w}}
                                               for b, s, a, k, w in reviews]},
            "reviewThreads": {"nodes": [{"path": path, "comments": {"nodes": [
                {"body": b, "authorAssociation": a, "author": {"__typename": "User", "login": w}} for b, a, w in comments]}}
                for path, comments in threads]}}


def test_only_maintainers_asks_count_and_threads_keep_their_folder():
    node = pr_node(7, reviews=[("Please add tests", "CHANGES_REQUESTED", "MEMBER", "User", "bob"),
                               ("add a changelog entry", "COMMENTED", "NONE", "User", "passerby"),
                               ("needs docs", "COMMENTED", "NONE", "Bot", "helper[bot]")],
                   threads=[("src/db/pool.py", [("typo here", "MEMBER", "bob"), ("I will add tests", "CONTRIBUTOR", "alice")])])
    asks = asks_from(node, author="alice", paths=["src/db/pool.py", "README.md"])
    assert sorted(asks) == [["style", "src/db"], ["tests", "(root)"], ["tests", "src/db"]]


class Batches:
    def __init__(self, nodes):
        self.nodes = {n["number"]: n for n in nodes}
        self.asked = []

    def query(self, query, variables=None, **kw):
        import re
        nums = [int(x) for x in re.findall(r"pullRequest\(number:(\d+)\)", query)]
        self.asked.append(nums)
        data = {"rateLimit": {"cost": 6, "remaining": 900, "resetAt": at(0)},
                "repository": {f"p{n}": self.nodes.get(n) for n in nums}}
        return GraphQLResult(data=data, cost=6, remaining=900, reset_at=at(0))


def closed_pr(n, paths, days=10, reviewed=True):
    ev = [["review", at(days + 1), "bob", "CHANGES_REQUESTED", "MEMBER", "User"]] if reviewed else []
    return {"t": "pr", "n": n, "st": "MERGED", "cr": at(days + 2), "mg": at(days), "cl": at(days), "au": "alice",
            "at": "User", "as": "NONE", "rq": [], "ev": ev, "cm": [], "paths": paths}


def test_asks_are_read_once_per_reviewed_pr_in_batches_and_resume_after_a_cap(tmp_path):
    store = FlowStore(tmp_path)
    prs = [closed_pr(n, ["src/db/a.py"]) for n in range(1, 6)] + [closed_pr(9, ["x.py"], reviewed=False)]
    gql = Batches([pr_node(n, reviews=[("add tests please", "CHANGES_REQUESTED", "MEMBER", "User", "bob")]) for n in range(1, 6)])
    first = collect_asks(gql, store, "o", "r", prs, batch=2, cap=3)
    assert first == {"read": 3, "left": 2} and all(len(b) <= 2 for b in gql.asked) and 9 not in sum(gql.asked, [])
    second = collect_asks(gql, store, "o", "r", prs, batch=2, cap=10)
    assert second == {"read": 2, "left": 0} and sorted(store.asks()) == [1, 2, 3, 4, 5]


def test_preflight_ranks_what_reviewers_ask_for_in_these_folders_with_counts():
    prs = [closed_pr(n, ["src/db/a.py"]) for n in range(1, 13)] + [closed_pr(n, ["docs/x.md"]) for n in range(20, 32)]
    asks = {n: [["tests", "src/db"]] for n in range(1, 10)} | {n: [["changelog", "src/db"]] for n in (10, 11)} | {12: []}
    asks |= {n: [["docs", "docs"]] for n in range(20, 32)}
    out = preflight(prs, asks, ["src/db/new.py"], NOW)
    assert out["scope"] == "src/db" and out["reviewed_prs"] == 12
    assert out["asks"][0] == {"ask": "tests", "share": 0.75, "prs": 9} and out["asks"][1]["ask"] == "changelog"
    thin = preflight(prs, asks, ["lib/new.py"], NOW)
    assert thin["scope"] == "whole repo" and thin["reviewed_prs"] == 24


def merged_pr(n, paths, lines=50, days=10):
    return {"t": "pr", "n": n, "st": "MERGED", "cr": at(days + 2), "mg": at(days), "cl": at(days), "au": "alice", "at": "User",
            "as": "MEMBER", "rq": [], "ev": [], "cm": [], "paths": paths, "add": lines, "del": 0}


def test_norms_say_what_merged_prs_here_usually_include_and_flag_gaps():
    from stackvitals.flow.preflight import gaps, norms
    prs = [merged_pr(n, ["src/db/a.py", "tests/test_a.py", "changes/1.md"], lines=40 + n) for n in range(1, 18)]
    prs += [merged_pr(n, ["src/db/b.py"], lines=60) for n in range(20, 23)]
    out = norms(prs, ["src/db/new.py"], NOW)
    assert out["scope"] == "src/db" and out["merged_prs"] == 20
    assert out["include"]["tests"] == 0.85 and out["include"]["changelog"] == 0.85 and out["size"]["p90_lines"] == 60
    found = gaps({"paths": ["src/db/new.py"], "add": 900, "del": 0}, out)
    assert [g["what"] for g in found] == ["tests", "changelog", "size"]
    assert gaps({"paths": ["src/db/new.py", "tests/test_new.py", "changes/2.md"], "add": 20, "del": 0}, out) == []


def test_build_adds_habits_asks_and_per_pr_gaps():
    from stackvitals.flow.build import build
    closed = [merged_pr(n, ["src/db/a.py", "tests/test_a.py"], lines=40) for n in range(1, 13)]
    waiting = {"t": "pr", "n": 99, "ti": "x", "draft": False, "st": "OPEN", "cr": at(2), "up": at(1), "mg": None, "cl": None,
               "au": "zed", "at": "User", "as": "NONE", "rq": [], "ev": [], "cm": [], "ci": "SUCCESS", "lc": at(2),
               "paths": ["src/db/new.py"], "add": 30, "del": 0}
    out = build({"open": [waiting], "closed": closed}, {}, NOW, owner="o", asks={n: [["tests", "src/db"]] for n in range(1, 13)})
    assert out["habits"]["include"]["tests"] == 1.0 and out["habits"]["asks"][0]["ask"] == "tests"
    assert out["queue"][0]["gaps"][0]["what"] == "tests"


def test_folder_habits_publish_what_the_cli_gives_each_busy_folder():
    from stackvitals.flow.preflight import folder_habits, norms, preflight
    prs = [merged_pr(n, ["src/db/a.py", "tests/test_a.py"], lines=10 * n) for n in range(1, 13)]
    prs += [merged_pr(n, ["lib/x.py", "CHANGELOG.md"], lines=30) for n in range(20, 34)]
    prs += [merged_pr(n, ["tools/t.py"]) for n in range(40, 45)]
    asks = {n: [["tests", "src/db"]] for n in range(1, 12)}
    out = folder_habits(prs, asks, NOW)
    # Busiest first; a folder under 10 merged PRs is left out (the CLI uses the whole repo there).
    assert [f["area"] for f in out] == ["(root)", "lib", "src/db", "tests"]
    for f in out:
        want = norms(prs, ["new.py" if f["area"] == "(root)" else f"{f['area']}/new.py"], NOW)
        assert want["scope"] == f["area"] and {k: f[k] for k in ("merged_prs", "include", "size")} == \
            {k: want[k] for k in ("merged_prs", "include", "size")}
    db = out[2]
    assert db["reviewed_prs"] == 11 and db["asks"] == preflight(prs, asks, ["src/db/new.py"], NOW)["asks"]
    # Asks are scoped only with 10+ reviewed PRs there, like the CLI; otherwise none are published for the folder.
    assert out[1]["asks"] == [] and out[1]["reviewed_prs"] == 0


def test_folder_habits_cap_the_folder_list_and_keep_root_files():
    from stackvitals.flow.preflight import folder_habits
    prs = [merged_pr(i * 20 + n, [f"pkg{i}/a/b.py"]) for i in range(5) for n in range(10)]
    prs += [merged_pr(500 + n, ["README.md"]) for n in range(11)]
    out = folder_habits(prs, {}, NOW, cap=3)
    assert [f["area"] for f in out] == ["(root)", "pkg0/a", "pkg1/a"] and out[0]["include"]["docs"] == 1.0


def test_build_publishes_per_folder_habits():
    from stackvitals.flow.build import build
    closed = [merged_pr(n, ["src/db/a.py"], lines=40) for n in range(1, 13)]
    out = build({"open": [], "closed": closed}, {}, NOW, owner="o")
    assert [f["area"] for f in out["habits"]["folders"]] == ["src/db"] and out["habits"]["folders"][0]["merged_prs"] == 12
