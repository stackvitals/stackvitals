"""Portal reads a repo's StackVitals results from its app.json in one request (a number, not badge text), and falls back
to the older files for repos that haven't run this version yet."""
import json

from stackvitals.portal import inventory
from stackvitals.portal.scorecard import _ci_first_try

APP = {"schema": 1, "facts": {"ci_first_try": 0.82, "open_prs": 5, "stale_prs": 1, "first_review_median_s": 7200,
                              "community_score": 71}}


def fake(files):
    calls = []

    def read(path):
        calls.append(path)
        return files.get(path, inventory.NA)
    return read, calls


def test_one_request_gives_every_fact_and_the_scorecard_uses_the_number(monkeypatch):
    read, calls = fake({"branch": {}, "docs/app.json": json.dumps(APP)})
    monkeypatch.setattr(inventory, "read", lambda api, path: read("branch"))
    monkeypatch.setattr(inventory, "read_file", lambda api, repo, path, ref: read(path))
    got = inventory.module_facts(None, "o/r")
    assert calls == ["branch", "docs/app.json"]
    assert got["ci_first_try"] == "82%" and got["ci_first_try_share"] == 0.82 and got["community_score"] == "71/100"
    assert got["flow"] == {"open": 5, "stale": 1, "first_review_median_s": 7200}
    result, evidence = _ci_first_try({"modules": got}, {"peer": 50}, None)
    assert "82%" in evidence


def test_repos_on_an_older_version_still_work(monkeypatch):
    files = {"branch": {}, "docs/badge.json": json.dumps({"schemaVersion": 1, "message": "75%"}),
             "docs/flow.json": json.dumps({"schema": 1, "open": 2, "stale": 0, "stages": {"pickup": {"median_s": 60}}})}
    read, calls = fake(files)
    monkeypatch.setattr(inventory, "read", lambda api, path: read("branch"))
    monkeypatch.setattr(inventory, "read_file", lambda api, repo, path, ref: read(path))
    got = inventory.module_facts(None, "o/r")
    assert got["ci_first_try"] == "75%" and got["flow"]["first_review_median_s"] == 60
