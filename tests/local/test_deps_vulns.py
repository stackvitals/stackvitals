import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from stackvitals.deps import vulns

FIX = Path(__file__).parent / "fixtures" / "osv-scan.json"
ROOT = "C:/work/repo"
NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)


def test_every_ecosystem_in_the_real_report_becomes_rows_with_fixed_versions(tmp_path):
    # The recorded report's paths are put under this machine's own folder, so the test reads the same on any system.
    root = tmp_path.resolve()
    doc = json.loads(FIX.read_text(encoding="utf-8").replace(ROOT, root.as_posix()))
    rows = vulns.findings(doc, root)
    ecos = {r["ecosystem"] for r in rows}
    assert {"npm", "PyPI", "crates.io", "RubyGems", "Packagist"} <= ecos
    lodash = [r for r in rows if r["package"] == "lodash"]
    assert lodash and all(r["file"] == "web/package-lock.json" for r in lodash)
    assert all(r["fixed"] is None or vulns._key(r["fixed"]) > vulns._key("4.17.15") for r in lodash)
    assert any(r["fixed"] for r in lodash) and {r["severity"] for r in rows} <= {"critical", "high", "moderate", "low", "unrated"}
    # Each advisory group is one row, named by its GitHub id when there is one.
    assert all(r["id"].startswith(("GHSA-", "MAL-", "PYSEC-", "RUSTSEC-", "OSV-", "CVE-")) for r in rows)


def test_lockfiles_in_vendored_test_or_fixture_folders_are_left_out():
    assert vulns.scannable("web/package-lock.json") and vulns.scannable("composer.lock") and vulns.scannable("svc/Cargo.lock")
    assert vulns.scannable("requirements-dev.txt") and vulns.scannable("go.mod")
    assert not vulns.scannable("node_modules/x/package-lock.json") and not vulns.scannable("tests/fixtures/yarn.lock")
    assert not vulns.scannable("vendor/a/composer.lock") and not vulns.scannable("README.md")


def test_a_finding_keeps_its_first_seen_day_and_new_and_gone_are_told_apart():
    a = {"file": "f", "ecosystem": "npm", "package": "a", "version": "1", "id": "GHSA-1"}
    b = {**a, "package": "b", "id": "GHSA-2"}
    c = {**a, "package": "c", "id": "GHSA-3"}
    cur, new, gone = vulns.merge([{**a, "first_seen": "2026-10-01"}, {**b, "first_seen": "2026-10-02"}], [a, c], NOW)
    assert [f["first_seen"] for f in cur] == ["2026-10-01", "2026-10-23"]
    assert [f["package"] for f in new] == ["c"] and [(f["package"], f["closed"]) for f in gone] == [("b", "2026-10-23")]


def test_a_download_that_does_not_match_its_published_hash_is_refused(tmp_path, monkeypatch):
    class Bad:
        def get(self, url):
            class R:
                content = b"not the scanner"
                def raise_for_status(self):
                    return self
            return R()
    monkeypatch.setattr(vulns, "asset", lambda: "osv-scanner_linux_amd64")
    with pytest.raises(vulns.ScannerError, match="SHA-256"):
        vulns.ensure_scanner(tmp_path, client=Bad())
    assert not (tmp_path / f"osv-scanner-{vulns.SCANNER}" / "osv-scanner_linux_amd64").exists()


class FakeAPI:
    repo = "o/r"

    def __init__(self, *a, **k):
        self.files = {"package-lock.json": b"{}", "node_modules/x/package-lock.json": b"{}"}

    malware = []

    def _get(self, path, params=None):
        if path == "/advisories":
            return self.malware
        if path.endswith("/git/trees/main"):
            return {"tree": [{"type": "blob", "path": p, "sha": "s" + p, "size": 2} for p in self.files]}
        return {"default_branch": "main"}

    def file(self, path, ref):
        return self.files[path]


class WS:
    def __init__(self, path):
        self.path, self.repo, self.cache, self.notes = path, "o/r", {}, []


def test_the_step_publishes_findings_names_new_ones_and_skips_an_unchanged_repo(tmp_path, monkeypatch):
    seen = {}

    def fake(binary, folder, offline, timeout=600, **kw):
        seen["files"] = sorted(str(p.relative_to(folder)).replace("\\", "/") for p in folder.rglob("*") if p.is_file())
        seen["offline"] = offline
        return {"results": [{"source": {"path": str(folder / "package-lock.json")}, "packages": [{
            "package": {"name": "lodash", "version": "4.17.15", "ecosystem": "npm"},
            "vulnerabilities": [{"id": "GHSA-x", "summary": "Prototype pollution",
                                 "affected": [{"package": {"name": "lodash", "ecosystem": "npm"},
                                               "ranges": [{"events": [{"introduced": "0"}, {"fixed": "4.17.21"}]}]}]}],
            "groups": [{"ids": ["GHSA-x"], "aliases": ["CVE-1"], "max_severity": "7.4"}]}]}]}
    monkeypatch.setattr(vulns, "run_scanner", fake)
    ws = WS(tmp_path)
    out = vulns.vulns_step(ws, {"GITHUB_TOKEN": "t"}, NOW, make_api=FakeAPI, scanner=Path("osv"))
    assert out["open"] == 1 and out["new"] == 1 and seen["files"] == ["package-lock.json"] and seen["offline"] is False
    doc = json.loads((tmp_path / "docs" / "vulns.json").read_text(encoding="utf-8"))
    row = doc["open"][0]
    assert (row["package"], row["severity"], row["fixed"], row["first_seen"]) == ("lodash", "high", "4.17.21", "2026-10-23")
    assert "fixed in 4.17.21" in ws.notes[0]
    # Same lockfiles, an hour later: nothing to do.
    assert vulns.vulns_step(ws, {"GITHUB_TOKEN": "t"}, NOW.replace(hour=13), make_api=FakeAPI, scanner=Path("osv")) is None


def test_with_outside_lookups_off_the_scanner_runs_offline(tmp_path, monkeypatch):
    from stackvitals.core.config import parse
    flags = {}
    monkeypatch.setattr(vulns, "run_scanner", lambda b, f, offline, timeout=600, **kw: flags.update(offline=offline) or {"results": []})
    ws = WS(tmp_path)
    ws.cache["settings"] = parse("[deps]\noutside_lookups = false\n")[0]
    vulns.vulns_step(ws, {"GITHUB_TOKEN": "t"}, NOW, make_api=FakeAPI, scanner=Path("osv"))
    assert flags["offline"] is True


def test_a_pull_request_is_told_only_the_advisories_it_adds_and_removes(monkeypatch):
    def fake(binary, folder, offline, timeout=600, **kw):
        res = []
        for f in folder.rglob("*"):
            if f.is_file():
                text = f.read_text(encoding="utf-8")
                pkgs = [{"package": {"name": n, "version": v, "ecosystem": "npm"}, "vulnerabilities": [],
                         "groups": [{"ids": [i], "max_severity": "9.8"}]} for n, v, i in json.loads(text)]
                res.append({"source": {"path": str(f)}, "packages": pkgs})
        return {"results": res}
    monkeypatch.setattr(vulns, "run_scanner", fake)

    class API:
        def file(self, path, ref):
            data = {("web/package-lock.json", "head"): [["a", "2", "GHSA-old"], ["b", "1", "GHSA-new"]],
                    ("package-lock.json", "base"): [["a", "1", "GHSA-old"], ["c", "1", "GHSA-gone"]]}
            if (path, ref) not in data:
                raise RuntimeError("HTTP 404")
            return json.dumps(data[(path, ref)]).encode()
    out = vulns.pr_diff(API(), [("web/package-lock.json", "package-lock.json")], "base", "head", Path("osv"), False)
    # a's advisory was already there (another version), b's is new, c's went away; the renamed file lines up.
    assert [(f["package"], f["id"], f["file"]) for f in out["added"]] == [("b", "GHSA-new", "web/package-lock.json")]
    assert [f["package"] for f in out["removed"]] == ["c"] and out["added"][0]["severity"] == "critical"


def test_malware_github_publishes_is_flagged_on_the_next_run_without_a_rescan(tmp_path, monkeypatch):
    scans = []

    def fake(binary, folder, offline, timeout=600, **kw):
        scans.append(1)
        return {"results": [{"source": {"path": str(folder / "package-lock.json")}, "packages": [
            {"package": {"name": "chalk", "version": "5.6.1", "ecosystem": "npm"}, "vulnerabilities": [], "groups": []},
            {"package": {"name": "debug", "version": "4.4.1", "ecosystem": "npm"}, "vulnerabilities": [], "groups": []}]}]}
    monkeypatch.setattr(vulns, "run_scanner", fake)
    ws = WS(tmp_path)
    assert vulns.vulns_step(ws, {"GITHUB_TOKEN": "t"}, NOW, make_api=FakeAPI, scanner=Path("osv"))["open"] == 0
    FakeAPI.malware = [{"ghsa_id": "GHSA-chalk", "published_at": "2026-10-23T12:30:00Z", "summary": "Malware in chalk",
                        "vulnerabilities": [{"package": {"ecosystem": "npm", "name": "chalk"}, "vulnerable_version_range": "= 5.6.1"},
                                            {"package": {"ecosystem": "npm", "name": "debug"}, "vulnerable_version_range": "= 4.4.2"}]}]
    try:
        out = vulns.vulns_step(ws, {"GITHUB_TOKEN": "t"}, NOW.replace(hour=13), make_api=FakeAPI, scanner=Path("osv"))
    finally:
        FakeAPI.malware = []
    # Only the bad version matches; no second scan was needed to flag it.
    assert len(scans) == 1 and out["malware"] == 1 and out["new"] == 1
    row = json.loads((tmp_path / "docs" / "vulns.json").read_text(encoding="utf-8"))["open"][0]
    assert (row["package"], row["malware"], row["first_seen"]) == ("chalk", True, "2026-10-23")
    assert vulns.in_range("1.2.3", ">= 1.0, < 2") and not vulns.in_range("2.0.0", ">= 1.0, < 2") and vulns.in_range("0.1", ">= 0")


def test_a_lockfile_in_a_dot_folder_is_scanned_under_a_plain_name_and_reported_under_its_own():
    assert vulns._plain(".devcontainer/requirements.txt") == "_dot.devcontainer/requirements.txt"
    assert vulns._real("_dot.devcontainer/requirements.txt") == ".devcontainer/requirements.txt"
    assert vulns._real(vulns._plain("a/.b/.c/Cargo.lock")) == "a/.b/.c/Cargo.lock"


def test_a_github_malware_match_stays_open_while_the_package_is_in_the_lockfile(tmp_path, monkeypatch):
    # OSV doesn't list it yet and the feed's window has moved past it: the next full scan must not close it.
    out = {"results": [{"source": {"path": "package-lock.json"}, "packages": [
        {"package": {"name": "evil", "version": "1.0.0", "ecosystem": "npm"}, "vulnerabilities": [], "groups": []}]}]}
    monkeypatch.setattr(vulns, "run_scanner", lambda b, folder, offline, timeout=600, **kw: json.loads(
        json.dumps(out).replace('"package-lock.json"', json.dumps(str(folder / "package-lock.json")))))
    advisory = {"ghsa_id": "GHSA-mal", "published_at": "2026-10-23T11:30:00Z", "summary": "Malicious package",
                "vulnerabilities": [{"package": {"ecosystem": "npm", "name": "evil"}, "vulnerable_version_range": ">= 0"}]}

    class Feed(FakeAPI):
        malware = [advisory]
    ws = WS(tmp_path)
    first = vulns.vulns_step(ws, {"GITHUB_TOKEN": "t"}, NOW, make_api=Feed, scanner=Path("osv"))
    assert first["malware"] == 1
    later = vulns.vulns_step(ws, {"GITHUB_TOKEN": "t"}, NOW + timedelta(days=1), make_api=FakeAPI, scanner=Path("osv"))
    assert later is None or later["malware"] == 1
    doc = json.loads((tmp_path / "docs" / "vulns.json").read_text(encoding="utf-8"))
    assert [f["package"] for f in doc["open"]] == ["evil"] and doc["closed"] == []
