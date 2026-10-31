"""Guided fixes: the smallest fixing upgrade, how big a jump it is, and the command for the ecosystem."""
from stackvitals.deps.fixplan import bump, plan


def test_bumps_and_commands():
    assert bump("4.17.20", "4.17.21") == "patch" and bump("1.2.0", "1.4.0") == "minor" and bump("1.9.0", "2.0.0") == "major"
    assert bump("0.3.1", "0.4.0") == "major"
    assert plan({"ecosystem": "npm", "package": "lodash", "version": "4.17.20", "fixed": "4.17.21"}) == \
        {"to": "4.17.21", "bump": "patch", "command": "npm install lodash@4.17.21"}
    assert plan({"ecosystem": "Go", "package": "golang.org/x/net", "version": "v0.17.0", "fixed": "0.23.0"})["command"] == \
        "go get golang.org/x/net@v0.23.0"
    assert plan({"ecosystem": "npm", "package": "x", "version": "1", "fixed": None}) is None
    assert plan({"ecosystem": "npm", "package": "x", "version": "1", "fixed": "2", "malware": True}) is None
