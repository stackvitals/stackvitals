"""Ignoring one advisory with a reason and an end date, in the osv-scanner.toml OSV-Scanner itself reads."""
from datetime import datetime, timezone

from stackvitals.deps.vulns import apply_ignores, ignores

NOW = datetime(2026, 10, 29, tzinfo=timezone.utc)
TOML = """
[[IgnoredVulns]]
id = "GHSA-aaaa-bbbb-cccc"
ignoreUntil = 2026-12-31
reason = "Only in the build tooling, never shipped"

[[IgnoredVulns]]
id = "CVE-2025-1"
ignoreUntil = 2026-01-01
reason = "Expired"

[[IgnoredVulns]]
id = "GO-2026-7"
"""


def test_active_ignores_mark_findings_by_id_or_alias_and_expired_ones_reopen():
    got = ignores(TOML, NOW)
    assert got == {"GHSA-aaaa-bbbb-cccc": {"until": "2026-12-31", "reason": "Only in the build tooling, never shipped"},
                   "GO-2026-7": {"until": None, "reason": ""}}
    rows = [{"id": "GHSA-zzzz", "aliases": ["GHSA-aaaa-bbbb-cccc"]}, {"id": "CVE-2025-1", "aliases": []}, {"id": "GO-2026-7"}]
    apply_ignores(rows, got)
    assert [bool(r.get("ignored")) for r in rows] == [True, False, True]
    assert ignores("not [toml", NOW) == {} and ignores(None, NOW) == {}


def test_open_findings_become_sarif_and_ignored_ones_stay_out():
    from stackvitals.deps.vulns import sarif
    rows = [{"id": "GHSA-1", "package": "lodash", "version": "4.17.20", "ecosystem": "npm", "severity": "high",
             "fixed": "4.17.21", "file": "package-lock.json", "malware": False},
            {"id": "GHSA-2", "package": "x", "version": "1", "ecosystem": "npm", "severity": "low", "file": "a/package-lock.json",
             "malware": False, "ignored": {"until": None, "reason": "dev only"}}]
    doc = sarif(rows)
    run = doc["runs"][0]
    assert doc["version"] == "2.1.0" and [r["ruleId"] for r in run["results"]] == ["GHSA-1"]
    assert run["results"][0]["level"] == "error" and run["results"][0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == "package-lock.json"
    assert run["tool"]["driver"]["rules"][0]["help"]["text"] == "Upgrade lodash to 4.17.21."


def test_govulncheck_reach_lands_on_each_go_finding():
    from stackvitals.deps.vulns import apply_reach
    rows = [{"id": "GO-2026-1", "aliases": ["CVE-1"], "ecosystem": "Go"}, {"id": "GHSA-x", "aliases": ["CVE-2"], "ecosystem": "Go"},
            {"id": "GHSA-y", "aliases": [], "ecosystem": "npm"}]
    reach = {"findings": [{"id": "GO-2026-1", "aliases": [], "reach": "called", "path": ["main.main", "lib.Parse"]},
                          {"id": "GO-2026-2", "aliases": ["CVE-2"], "reach": "required", "path": []}]}
    apply_reach(rows, reach)
    assert rows[0]["reach"] == {"level": "called", "path": ["main.main", "lib.Parse"]}
    assert rows[1]["reach"]["level"] == "required" and "reach" not in rows[2]
