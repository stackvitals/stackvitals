from datetime import datetime, timezone

from mergescout.signals.osv import _facts
from stackvitals.deps.action import accepted_packages, apply_policy
from stackvitals.deps.dossier import _osv_lines, affected_by

NOW = datetime(2026, 10, 23, tzinfo=timezone.utc)
OSV = {"affects": [{"id": "GHSA-old", "ranges": [["0", "1.2.0", True]], "severity": "HIGH", "disputed": False},
                   {"id": "GHSA-rc", "ranges": [["1.5.0", "2.0.0rc1"]], "severity": "MODERATE", "disputed": False},
                   {"id": "GHSA-dis", "ranges": [["0", None]], "severity": "CRITICAL", "disputed": True}],
       "open_severity": "HIGH", "ids": []}


def test_a_last_affected_bound_closes_the_span_instead_of_affecting_every_later_version():
    record = {"id": "GHSA-x", "affected": [{"package": {"ecosystem": "npm", "name": "left-pad"}, "ranges": [
        {"type": "SEMVER", "events": [{"introduced": "0"}, {"last_affected": "1.2.0"}]}]}]}
    assert _facts(record, {"npm:left-pad"})["ranges"] == {"npm:left-pad": [["0", "1.2.0", True]]}
    assert [a["id"] for a in affected_by(OSV, ["1.2.0"], disputed=False)] == ["GHSA-old"]
    assert affected_by(OSV, ["5.0.0"], disputed=False) == []
    line = next(x for x in _osv_lines(OSV, True, versions=["1.0.0"]) if "installed here" in x["text"])
    assert "affected up to 1.2.0, no fix named" in line["text"]


def test_a_pre_release_fix_is_judged_in_order_and_an_unparsable_version_never_is():
    assert affected_by(OSV, ["2.0.0"], disputed=False) == []
    assert [a["id"] for a in affected_by(OSV, ["2.0.0b1"], disputed=False)] == ["GHSA-rc"]
    assert affected_by(OSV, ["main"], disputed=True) == []


def test_the_severity_policy_judges_the_installed_version_and_honours_accept():
    d = {"verdict": "use", "reasons": [], "osv": OSV}
    policy = {"max_severity": "moderate"}
    assert apply_policy(d, policy, "left-pad", versions=["5.0.0"])["verdict"] == "use"
    assert apply_policy(d, policy, "left-pad", versions=["1.0.0"])["verdict"] == "investigate"
    assert apply_policy(d, policy, "left-pad", versions=["1.0.0"], accepted={"left-pad"})["verdict"] == "use"


def test_accepted_packages_come_from_the_data_branch_and_expire():
    import json

    class Api:
        def file(self, path, ref):
            assert ref == "stackvitals-data"
            return json.dumps({"package:a": {"kind": "package", "id": "a", "verb": "accept", "until": "2026-11-01"},
                               "package:b": {"kind": "package", "id": "b", "verb": "accept", "until": "2026-10-01"},
                               "test:x": {"kind": "test", "id": "x", "verb": "accept"}}).encode()

    class Broken:
        def file(self, path, ref):
            raise OSError("no data branch")
    assert accepted_packages(Api(), NOW) == {"a"} and accepted_packages(Broken(), NOW) == set()
