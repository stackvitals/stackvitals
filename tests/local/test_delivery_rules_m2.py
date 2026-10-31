"""Middleware's delivery settings, done our way: every merge as a deployment (chosen, never guessed), fix pull requests
that name what they fix, and the incident sources a team picks, with reverts of docs or bots left out."""
from stackvitals.core import delivery
from stackvitals.core.config import parse


def pr(n, mg, ti="feat: x", head="feature", paths=("src/a.py",), au="ana", mc=None, cr=None):
    return {"n": n, "mg": mg, "cr": cr or mg, "ti": ti, "head": head, "paths": list(paths), "au": au, "mc": mc or f"{n:040x}",
            "base": "main"}


def test_merges_count_as_deployments_only_when_chosen():
    prs = [pr(1, "2026-10-01T00:00:00Z"), pr(2, "2026-10-02T00:00:00Z")]
    repo = {"default_branch": "main"}
    assert delivery.find_deployments(repo, {}, parse("")[0], prs) == ([], None)
    deps, source = delivery.find_deployments(repo, {}, parse('[delivery]\nsource = "merges"\n')[0], prs)
    assert source == "merges" and [d["id"] for d in deps] == ["merge:1", "merge:2"]


def test_a_fix_pr_that_names_the_broken_pr_blames_the_deployment_that_shipped_it():
    cfg = parse('[delivery]\nfix_patterns = ["^fix.*#([0-9]+)", "^hotfix/([0-9]+)-"]\n')[0]
    assert cfg["delivery"]["fix_patterns"]
    prs = [pr(10, "2026-10-01T00:00:00Z"), pr(11, "2026-10-03T00:00:00Z"),
           pr(12, "2026-10-05T00:00:00Z", ti="fix: crash from #10"), pr(13, "2026-10-06T00:00:00Z", head="hotfix/11-null")]
    deps = [{"id": "d1", "sha": prs[0]["mc"], "finished": "2026-10-01T01:00:00Z"},
            {"id": "d2", "sha": prs[1]["mc"], "finished": "2026-10-03T01:00:00Z"},
            {"id": "d3", "sha": "x", "finished": "2026-10-05T06:00:00Z"}]
    incs = delivery.find_incidents(prs, [], deps, cfg)
    assert [(i["source"], i["fixes"], i["fix_chain_deployment"]) for i in incs] == [("fix", 10, "d1"), ("fix", 11, "d2")]


def test_bad_fix_patterns_and_unknown_sources_are_refused():
    cfg, notes = parse('[delivery]\nfix_patterns = ["(unclosed"]\nincident_sources = ["issues", "tweets"]\n')
    assert cfg["delivery"]["fix_patterns"] == [] and cfg["delivery"]["incident_sources"] == [] and len(notes) == 2
    assert parse('[delivery]\nfix_patterns = ["^fix: no group"]\n')[0]["delivery"]["fix_patterns"] == []


def test_chosen_sources_and_ignored_reverts():
    prs = [pr(1, "2026-10-01T00:00:00Z", paths=("docs/a.md",)), pr(2, "2026-10-02T00:00:00Z", ti='Revert "feat: x" (#1)'),
           pr(3, "2026-10-03T00:00:00Z", au="dependabot[bot]"), pr(4, "2026-10-04T00:00:00Z", ti="Revert #3"),
           pr(5, "2026-10-05T00:00:00Z", paths=("src/b.py",)), pr(6, "2026-10-06T00:00:00Z", ti="Revert #5")]
    issues = [{"n": 9, "cr": "2026-10-07T00:00:00Z", "cl": None, "lb": ["incident"]}]
    cfg = parse('[delivery]\nignore_reverts_of = ["docs/**", "dependabot[bot]"]\n')[0]
    assert [i["number"] for i in delivery.find_incidents(prs, issues, [], cfg)] == [6, 9]
    only = parse('[delivery]\nincident_sources = ["issues"]\n')[0]
    got, said = delivery.incidents_for(prs, issues, [], only, None)
    assert [i["number"] for i in got] == [9] and said == "issues"
