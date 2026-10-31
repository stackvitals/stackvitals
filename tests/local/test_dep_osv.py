from datetime import datetime, timezone

from mergescout.signals.osv import refresh_vulns

NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)


def rec(id_, pkg, eco, published, fixed=True, aliases=(), severity="MODERATE", withdrawn=None, modified="2026-10-01T00:00:00Z"):
    events = [{"introduced": "0"}] + ([{"fixed": "9.9.9"}] if fixed else [])
    r = {"id": id_, "aliases": list(aliases), "published": published, "modified": modified,
         "affected": [{"package": {"name": pkg, "ecosystem": eco}, "ranges": [{"type": "ECOSYSTEM", "events": events}]}],
         "database_specific": {"severity": severity}}
    if withdrawn:
        r["withdrawn"] = withdrawn
    return r


RECORDS = {
    "GHSA-1": rec("GHSA-1", "requests", "PyPI", "2025-06-09T00:00:00Z", aliases=["CVE-2024-1", "PYSEC-9"]),
    "PYSEC-9": rec("PYSEC-9", "requests", "PyPI", "2025-06-10T00:00:00Z", aliases=["CVE-2024-1", "GHSA-1"]),  # same flaw
    "GHSA-2": rec("GHSA-2", "requests", "PyPI", "2023-05-01T00:00:00Z", severity="HIGH"),
    "GHSA-3": rec("GHSA-3", "requests", "PyPI", "2026-09-01T00:00:00Z", fixed=False, severity="CRITICAL"),
    "GHSA-4": rec("GHSA-4", "requests", "PyPI", "2026-01-01T00:00:00Z", withdrawn="2026-02-01T00:00:00Z"),
    "MAL-2025-7": rec("MAL-2025-7", "event-stream", "npm", "2025-11-26T00:00:00Z", fixed=False, severity=None),
}
IDS = {("PyPI", "requests"): ["GHSA-1", "PYSEC-9", "GHSA-2", "GHSA-3", "GHSA-4"], ("npm", "event-stream"): ["MAL-2025-7"],
       ("npm", "lodash"): []}


def fake_post(url, body):
    assert url.endswith("/v1/querybatch")
    out = []
    for q in body["queries"]:
        ids = IDS.get((q["package"]["ecosystem"], q["package"]["name"]), [])
        out.append({"vulns": [{"id": i, "modified": RECORDS[i]["modified"]} for i in ids]} if ids else {})
    return {"results": out}


def test_package_vulnerability_history_merges_aliases_and_counts_what_matters():
    fetched = []

    def get(url):
        fetched.append(url.rsplit("/", 1)[1])
        return RECORDS[url.rsplit("/", 1)[1]]
    state = refresh_vulns([("pypi", "requests"), ("npm", "event-stream"), ("npm", "lodash")], {}, NOW, fake_post, get)
    r = state["packages"]["pypi:requests"]
    # GHSA-1 and PYSEC-9 are one flaw; GHSA-4 was withdrawn.
    assert (r["advisories"], r["last_2y"], r["unfixed"], r["malware"]) == (3, 2, 1, False)
    assert r["severity"] == {"MODERATE": 1, "HIGH": 1, "CRITICAL": 1} and r["latest"] == "2026-09-01"
    assert state["packages"]["npm:event-stream"]["malware"] is True
    assert state["packages"]["npm:lodash"]["advisories"] == 0
    assert sorted(fetched) == sorted(RECORDS)


def test_unchanged_records_are_not_fetched_again():
    first = refresh_vulns([("pypi", "requests")], {}, NOW, fake_post, lambda url: RECORDS[url.rsplit("/", 1)[1]])
    fetched = []

    def get(url):
        fetched.append(url)
        return RECORDS[url.rsplit("/", 1)[1]]
    second = refresh_vulns([("pypi", "requests")], first, NOW, fake_post, get)
    assert fetched == [] and second["packages"]["pypi:requests"]["advisories"] == 3


def test_the_cache_keeps_the_query_answers_modified_time_not_the_records_own_spelling():
    # Live: the batch answer and the record wrote the same time with different precision, so everything was fetched again.
    def get(url):
        r = dict(RECORDS[url.rsplit("/", 1)[1]])
        r["modified"] = r["modified"].replace("Z", ".123456789Z")
        return r
    first = refresh_vulns([("pypi", "requests")], {}, NOW, fake_post, get)
    fetched = []
    refresh_vulns([("pypi", "requests")], first, NOW, fake_post, lambda url: fetched.append(url) or get(url))
    assert fetched == []


def test_a_dropped_connection_loses_one_advisory_not_the_run():
    import http.client

    def get(url):
        if url.endswith("GHSA-2"):
            raise http.client.RemoteDisconnected("closed")  # seen live on api.osv.dev
        return RECORDS[url.rsplit("/", 1)[1]]
    state = refresh_vulns([("pypi", "requests")], {}, NOW, fake_post, get)
    assert state["packages"]["pypi:requests"]["advisories"] == 2 and "GHSA-2" not in state["records"]


def test_the_daily_snapshot_refreshes_vulnerability_history_from_yesterdays_file(tmp_path, monkeypatch):
    import json

    import mergescout.signals.osv as osv
    from mergescout.snapshot.__main__ import write_vulns
    (tmp_path / "deps-map.json").write_text(json.dumps({"packages": {"pypi:requests": {"repo": "psf/requests"}}}), encoding="utf-8")
    (tmp_path / "deps-osv.json").write_text(json.dumps({"records": {"GHSA-1": {"modified": "x"}}}), encoding="utf-8")
    seen = {}

    def fake(packages, previous, now, **kw):
        seen.update(packages=packages, previous=previous)
        return {"built_at": "t", "records": {}, "packages": {"pypi:requests": {"advisories": 3}}}
    monkeypatch.setattr(osv, "refresh_vulns", fake)
    said = []
    write_vulns(tmp_path, NOW, said.append)
    assert seen["packages"] == [("pypi", "requests")] and seen["previous"]["records"] == {"GHSA-1": {"modified": "x"}}
    assert json.loads((tmp_path / "deps-osv.json").read_text(encoding="utf-8"))["packages"]["pypi:requests"]["advisories"] == 3
    assert any("vulnerability history" in s for s in said)


def test_a_first_run_fetches_at_most_a_cap_and_says_the_history_is_still_loading():
    fetched = []

    def get(url):
        fetched.append(url)
        return RECORDS[url.rsplit("/", 1)[1]]
    state = refresh_vulns([("pypi", "requests")], {}, NOW, fake_post, get, max_fetch=2)
    assert len(fetched) == 2 and state["complete"] is False
    state = refresh_vulns([("pypi", "requests")], state, NOW, fake_post, get, max_fetch=10)
    assert state["complete"] is True and state["packages"]["pypi:requests"]["advisories"] == 3


def test_a_malware_record_is_not_an_unfixed_advisory_and_its_own_id_is_kept():
    # Real data: axios's malware record (MAL- aliased by a GHSA) counted as "1 advisory has no fixed version".
    records = {"GHSA-m": rec("GHSA-m", "axios", "npm", "2026-03-31T00:00:00Z", fixed=False, aliases=["MAL-2026-1"]),
               "MAL-2026-1": rec("MAL-2026-1", "axios", "npm", "2026-03-31T00:00:00Z", fixed=False, aliases=["GHSA-m"])}

    def post(url, body):
        return {"results": [{"vulns": [{"id": i, "modified": records[i]["modified"]} for i in records]}]}
    state = refresh_vulns([("npm", "axios")], {}, NOW, post, lambda url: records[url.rsplit("/", 1)[1]])
    s = state["packages"]["npm:axios"]
    assert s["malware"] and s["unfixed"] == 0 and s["malware_ids"] == ["MAL-2026-1"]


def test_last_affected_bounds_and_disputed_advisories_are_not_open_ones():
    # Real data (pyjwt): GHSA-gvp8 affects 2.11.0..2.13.0 ("last_affected", no "fixed") while 2.15.1 is out, and
    # PYSEC-2025-183 is a CVE "disputed by the supplier"; both were counted as unfixed.
    bounded = rec("GHSA-b", "pyjwt", "PyPI", "2026-09-30T00:00:00Z", fixed=False)
    bounded["affected"][0]["ranges"][0]["events"] = [{"introduced": "2.11.0"}, {"last_affected": "2.13.0"}]
    disputed = rec("PYSEC-d", "pyjwt", "PyPI", "2025-07-31T00:00:00Z", fixed=False)
    disputed["details"] = "pyjwt v2.10.1 has weak encryption. NOTE: this is disputed by the Supplier."
    records = {"GHSA-b": bounded, "PYSEC-d": disputed}

    def post(url, body):
        return {"results": [{"vulns": [{"id": i, "modified": records[i]["modified"]} for i in records]}]}
    s = refresh_vulns([("pypi", "pyjwt")], {}, NOW, post, lambda url: records[url.rsplit("/", 1)[1]])["packages"]["pypi:pyjwt"]
    assert s["unfixed"] == 0 and s["last_affected"] == ["2.13.0"] and s["disputed"] == 1 and s["advisories"] == 2


def test_a_malware_record_names_the_bad_versions_or_says_every_version():
    # Hand-check: "a published version was malicious" didn't say which, so users couldn't tell if theirs was one.
    hijack = rec("MAL-2026-5", "react-hook-form", "npm", "2026-09-30T00:00:00Z", fixed=False, severity=None)
    # Real MAL-2026-2853: no range, only the hijacked versions; an open range means every version.
    del hijack["affected"][0]["ranges"]
    hijack["affected"][0]["versions"] = ["7.73.0", "7.72.1"]
    squat = rec("MAL-2026-6", "ubuntu", "npm", "2026-08-01T00:00:00Z", fixed=False, severity=None)
    records = {"MAL-2026-5": hijack, "MAL-2026-6": squat}
    ids = {("npm", "react-hook-form"): ["MAL-2026-5"], ("npm", "ubuntu"): ["MAL-2026-6"]}

    def post(url, body):
        return {"results": [{"vulns": [{"id": i, "modified": records[i]["modified"]}
                                       for i in ids.get((q["package"]["ecosystem"], q["package"]["name"]), [])]}
                            for q in body["queries"]]}
    got = refresh_vulns([("npm", "react-hook-form"), ("npm", "ubuntu")], {}, NOW, post, lambda url: records[url.rsplit("/", 1)[1]])
    assert got["packages"]["npm:react-hook-form"]["malware_versions"] == ["7.72.1", "7.73.0"]
    assert got["packages"]["npm:ubuntu"]["malware_versions"] == ["all"]
    # Malware records cached before the versions were kept are read once more.
    old = {"records": {i: {k: v for k, v in r.items() if k != "bad"} for i, r in got["records"].items()}}
    again = refresh_vulns([("npm", "react-hook-form")], old, NOW, post, lambda url: records[url.rsplit("/", 1)[1]])
    assert again["packages"]["npm:react-hook-form"]["malware_versions"] == ["7.72.1", "7.73.0"]


def test_advisories_of_the_last_90_days_are_counted_once_per_flaw():
    got = refresh_vulns([("pypi", "requests")], {}, NOW, fake_post, lambda url: RECORDS[url.rsplit("/", 1)[1]])
    # GHSA-3 (2026-09-01) is the only flaw first published within 90 days of 2026-10-18.
    assert got["packages"]["pypi:requests"]["last_90d"] == 1
