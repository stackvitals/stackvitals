from datetime import datetime, timezone

from mergescout.signals.osv import _facts, _summary

NOW = datetime(2026, 10, 18, tzinfo=timezone.utc)


def record(id_, events, aliases=()):
    return {"id": id_, "aliases": list(aliases), "published": "2026-01-01T00:00:00Z", "modified": "2026-02-01T00:00:00Z",
            "affected": [{"package": {"name": "x", "ecosystem": "PyPI"}, "ranges": [{"type": "ECOSYSTEM", "events": events}]}],
            "database_specific": {"severity": "HIGH"}}


def test_each_advisory_keeps_its_affected_ranges_with_the_fixing_version():
    f = _facts(record("GHSA-a", [{"introduced": "0"}, {"fixed": "1.2.3"}, {"introduced": "2.0.0"}, {"fixed": "2.0.5"}]),
               {"pypi:x"})
    assert f["ranges"]["pypi:x"] == [["0", "1.2.3"], ["2.0.0", "2.0.5"]]
    out = _summary("pypi:x", [f, _facts(record("GHSA-b", [{"introduced": "1.0"}]), {"pypi:x"})], NOW)
    assert {"id": "GHSA-a", "ranges": [["0", "1.2.3"], ["2.0.0", "2.0.5"]], "severity": "HIGH", "disputed": False} in out["affects"]
    assert {"id": "GHSA-b", "ranges": [["1.0", None]], "severity": "HIGH", "disputed": False} in out["affects"]


def test_the_dossier_names_advisories_that_still_affect_the_version_being_installed():
    from stackvitals.deps.dossier import _osv_lines
    osv = {"advisories": 2, "ids": [], "affects": [{"id": "GHSA-a", "ranges": [["0", "1.2.3"], ["2.0.0", "2.0.5"]]},
                                                   {"id": "GHSA-b", "ranges": [["2.1.0", None]]}]}
    hits = [x for x in _osv_lines(osv, True, versions=["2.0.1"]) if x["signal"] == "alarm"]
    assert len(hits) == 1 and "2.0.1" in hits[0]["text"] and "GHSA-a" in hits[0]["text"] and "fixed in 2.0.5" in hits[0]["text"]
    assert not [x for x in _osv_lines(osv, True, versions=["2.0.5"]) if "affected" in x["text"]]
    open_one = [x for x in _osv_lines(osv, True, versions=["2.3.0"]) if x["signal"] == "alarm"]
    assert "GHSA-b" in open_one[0]["text"] and "no fixed version" in open_one[0]["text"]
    # Without a version being installed (the CLI's package check), nothing is said about versions.
    assert not [x for x in _osv_lines(osv, True) if "affected by" in x["text"]]
