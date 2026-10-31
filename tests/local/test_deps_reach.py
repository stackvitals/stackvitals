import json

from stackvitals.deps.reach import read_govulncheck

STREAM = "\n".join(json.dumps(x) for x in [
    {"config": {"scanner_name": "govulncheck", "scanner_version": "v1.1.4"}},
    {"progress": {"message": "Scanning your code..."}},
    {"osv": {"id": "GO-2024-0001", "aliases": ["CVE-2024-1", "GHSA-aaaa"], "summary": "Bad parse in x/net"}},
    {"osv": {"id": "GO-2024-0002", "aliases": ["CVE-2024-2"], "summary": "Leak in y"}},
    {"osv": {"id": "GO-2024-0003", "aliases": [], "summary": "Only required"}},
    # Module level, then package level, then the function the app calls (the trace starts at the vulnerable symbol).
    {"finding": {"osv": "GO-2024-0001", "fixed_version": "v0.23.0", "trace": [{"module": "golang.org/x/net", "version": "v0.20.0"}]}},
    {"finding": {"osv": "GO-2024-0001", "fixed_version": "v0.23.0", "trace": [
        {"module": "golang.org/x/net", "version": "v0.20.0", "package": "golang.org/x/net/html", "function": "Parse"},
        {"module": "example.com/app", "package": "example.com/app/web", "function": "render"},
        {"module": "example.com/app", "package": "example.com/app", "function": "main"}]}},
    {"finding": {"osv": "GO-2024-0002", "fixed_version": "v1.4.0", "trace": [
        {"module": "example.com/y", "version": "v1.3.0", "package": "example.com/y/z"}]}},
    {"finding": {"osv": "GO-2024-0003", "trace": [{"module": "example.com/q", "version": "v2.0.0"}]}},
])


def test_each_advisory_says_how_far_it_reaches_into_the_code():
    got = {f["id"]: f for f in read_govulncheck(STREAM)["findings"]}
    assert got["GO-2024-0001"]["reach"] == "called" and got["GO-2024-0001"]["fixed"] == "v0.23.0"
    assert got["GO-2024-0001"]["path"] == ["main", "web.render", "html.Parse"]
    assert got["GO-2024-0001"]["aliases"] == ["CVE-2024-1", "GHSA-aaaa"]
    assert got["GO-2024-0002"]["reach"] == "imported" and got["GO-2024-0003"]["reach"] == "required"
    assert got["GO-2024-0003"]["fixed"] is None


def test_the_summary_counts_by_reach_and_odd_lines_are_skipped():
    out = read_govulncheck(STREAM + "\nnot json\n{\"finding\": 3}\n")
    assert out["counts"] == {"called": 1, "imported": 1, "required": 1}
    assert out["scanner"] == "govulncheck v1.1.4"
    assert read_govulncheck("")["findings"] == []
