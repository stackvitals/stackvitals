import io
import zipfile
from datetime import timedelta

import httpx
from ci_fake import T0, FakeGitHub, Run, job
from stackvitals.ci.api import ActionsAPI
from stackvitals.ci.collect import collect
from stackvitals.ci.store import DataStore

ART_NOW = T0 + timedelta(days=3)


def junit(*cases):
    body = "".join(f'<testcase classname="t" name="{n}" time="{secs}">' + (f'<failure message="{msg}"/>' if msg else "")
                   + "</testcase>" for n, secs, msg in cases)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("results.xml", f"<testsuite>{body}</testsuite>")
    return buf.getvalue()


def art_api_for(fake, **kw):
    return ActionsAPI("tok", "o/r", client=httpx.Client(transport=fake.transport()), sleep=lambda s: None, **kw)


def retried_run():
    return Run(1, T0, [("failure", [job(11, "test", "failure", T0, 60)]),
                       ("success", [job(12, "test", "success", T0 + timedelta(minutes=10), 60, attempt=2)])])


def test_test_reports_are_read_per_attempt_and_other_artifacts_are_ignored(tmp_path):
    arts = {1: [(101, "test-results", junit(("a", 1, "boom"), ("b", 2, None)), T0 + timedelta(minutes=2)),
                (102, "test-results", junit(("a", 1, None), ("b", 2, None)), T0 + timedelta(minutes=12)),
                (103, "coverage-html", b"PK-not-a-report", T0 + timedelta(minutes=12))]}
    fake = FakeGitHub([retried_run()], artifacts=arts)
    store = DataStore(tmp_path)
    collect(art_api_for(fake), store, ART_NOW, days=5, tests=True)
    reports = sorted(store.load()["tests"], key=lambda r: r["att"])
    assert [(r["att"], r["name"], [f[0] for f in r["failed"]]) for r in reports] == [
        (1, "test-results", ["t::a"]), (2, "test-results", [])]
    assert not any("/artifacts/103/" in c for c in fake.calls)


def test_reports_are_not_read_twice_and_tests_are_off_unless_asked(tmp_path):
    arts = {1: [(101, "junit", junit(("a", 1, None)), T0 + timedelta(minutes=2))]}
    fake = FakeGitHub([retried_run()], artifacts=arts)
    store = DataStore(tmp_path)
    collect(art_api_for(fake), store, ART_NOW, days=5)
    assert store.load()["tests"] == [] and not any("artifacts" in c for c in fake.calls)
    collect(art_api_for(fake), store, ART_NOW, days=5, tests=True, recheck_days=10)
    collect(art_api_for(fake), store, ART_NOW, days=5, tests=True, recheck_days=10)
    assert sum("/artifacts/101/zip" in c for c in fake.calls) == 1


def test_a_rerun_that_comes_later_has_its_test_report_read_too(tmp_path):
    # Sandbox finding: reports were read once per run, so attempts 2 and 3 of a later re-run were never read.
    first = Run(1, T0, [("failure", [job(11, "test", "failure", T0, 60)])])
    arts = {1: [(101, "test-results", junit(("a", 1, "boom")), T0 + timedelta(minutes=2))]}
    fake = FakeGitHub([first], artifacts=arts)
    store = DataStore(tmp_path)
    collect(art_api_for(fake), store, T0 + timedelta(hours=1), days=5, tests=True)
    fake.runs[1] = retried_run()
    arts[1].append((102, "test-results", junit(("a", 1, None)), T0 + timedelta(minutes=12)))
    collect(art_api_for(fake), store, T0 + timedelta(hours=2), days=5, tests=True)
    reports = sorted(store.load()["tests"], key=lambda r: r["att"])
    assert [(r["att"], [f[0] for f in r["failed"]]) for r in reports] == [(1, ["t::a"]), (2, [])]
