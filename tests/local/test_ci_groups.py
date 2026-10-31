"""Failures carry their cause; CI Health groups them across tests and runs, and every surface can name the group."""
from datetime import timedelta

from ci_fake import T0
from stackvitals.ci.analyze import analyze
from stackvitals.ci.feedback import classify_run
from stackvitals.ci.testreports import parse_report

DNS = """java.util.concurrent.ExecutionException: java.net.UnknownHostException: Failed to resolve '{host}'
\tat io.netty.util.concurrent.DefaultPromise.get(DefaultPromise.java:340)
\tat io.netty.resolver.dns.DnsNameResolverTest.{test}(DnsNameResolverTest.java:1714)
Caused by: java.net.UnknownHostException: Failed to resolve '{host}'
\tat io.netty.resolver.dns.DnsResolveContext.finishResolve(DnsResolveContext.java:1138)
\tat io.netty.resolver.dns.DnsResolveContext.tryToFinishResolve(DnsResolveContext.java:1085)
"""


def junit(cases):
    body = "".join(f'<testcase classname="io.netty.resolver.dns.DnsNameResolverTest" name="{n}" time="{t}">'
                   f'<failure type="java.util.concurrent.ExecutionException" message="x"><![CDATA[{DNS.format(host=h, test=n)}]]>'
                   f'</failure></testcase>' if h else
                   f'<testcase classname="io.netty.resolver.dns.DnsNameResolverTest" name="{n}" time="{t}"/>'
                   for n, h, t in cases)
    return f'<testsuite tests="{len(cases)}">{body}</testsuite>'.encode()


def test_a_parsed_failure_keeps_its_cause_location_type_and_duration():
    out = parse_report("r.xml", junit([("testA", "a.netty.io", "1.5"), ("testB", "b.netty.io", "0.2"), ("testC", None, "0.1")]))
    a, b = out["failed"]
    assert a[0] == "io.netty.resolver.dns.DnsNameResolverTest::testA" and len(a) == 7
    assert a[3] == b[3]  # one cause for both tests
    assert a[1] != b[1]  # each test keeps its own key
    assert a[4] == "io.netty.resolver.dns.DnsResolveContext.finishResolve" and a[5] == "java.net.UnknownHostException"
    assert a[6] == 1500 and b[6] == 200


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def run(rid, at, c="failure", br="main", ev="push", pr=()):
    return {"t": "run", "id": rid, "att": 1, "wf": 1, "wfn": "CI", "path": ".github/workflows/ci.yml", "ev": ev, "br": br,
            "sha": f"s{rid}", "tree": f"t{rid}", "pr": list(pr), "c": c, "cr": iso(at), "st": iso(at), "up": iso(at)}


def report(rid, at_failed):
    return {"t": "tests", "run": rid, "att": 1, "art": rid, "name": "junit", "total": 20, "skipped": 0, "flaky": [], "slow": [],
            "failed": at_failed}


def test_groups_count_tests_runs_and_dates_and_old_records_still_read():
    now = T0 + timedelta(days=5)
    parsed = parse_report("r.xml", junit([("testA", "a.netty.io", "1"), ("testB", "b.netty.io", "1")]))["failed"]
    runs = [run(1, T0), run(2, T0 + timedelta(days=1)), run(3, T0 + timedelta(days=2))]
    tests = [report(1, parsed), report(2, parsed[:1]),
             report(3, [["pkg::old_test", "abc", "AssertionError: x"]])]  # a record written before causes existed
    result = analyze({"runs": runs, "jobs": [], "tests": tests}, now, 30, default_branch="main")
    groups = result["failure_groups"]
    assert len(groups) == 1
    g = groups[0]
    assert g["failures"] == 3 and g["tests"] == 2 and g["runs"] == 2 and g["type"] == "java.net.UnknownHostException"
    assert g["where"] == "io.netty.resolver.dns.DnsResolveContext.finishResolve" and g["first"] == iso(T0)
    assert g["last"] == iso(T0 + timedelta(days=1)) and g["examples"][0]["run"] == 2
    by_id = {t["id"]: t for t in result["tests"]}
    assert by_id["io.netty.resolver.dns.DnsNameResolverTest::testA"]["group"] == g["id"]
    assert "group" not in by_id["pkg::old_test"] or by_id["pkg::old_test"]["group"] is None


def test_a_failed_run_names_the_group_and_how_many_other_tests_share_it():
    now = T0 + timedelta(days=5)
    parsed = parse_report("r.xml", junit([("testA", "a.netty.io", "1"), ("testB", "b.netty.io", "1")]))["failed"]
    data = {"runs": [run(1, T0), run(2, T0 + timedelta(days=4), ev="pull_request", br="fix", pr=[7])], "jobs": [],
            "tests": [report(1, parsed), report(2, parsed[:1])]}
    result = analyze(data, now, 30, default_branch="main")
    items = classify_run(data, result, 2)
    assert items[0]["group"]["tests"] == 2 and items[0]["group"]["where"].endswith("finishResolve")
    assert "same failure in 2 tests" in items[0]["detail"]
