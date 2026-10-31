"""`stackvitals ci validate`: a report read the way the Action reads it, then checked for what quietly breaks features."""
from datetime import datetime, timezone

from stackvitals.ci import validate

NOW = datetime(2026, 10, 29, tzinfo=timezone.utc)


def test_a_good_junit_report_passes():
    xml = (b'<testsuite name="s" tests="2" timestamp="2026-10-29T00:00:00"><testcase classname="a.B" name="t1" time="0.2"/>'
           b'<testcase classname="a.B" name="t2" time="0.1"><failure message="boom">trace</failure></testcase></testsuite>')
    r = validate.check("r.xml", xml, NOW)
    assert r["ok"] and r["tests"] == 2 and r["failed"] == 1 and r["problems"] == []


def test_problems_are_named():
    xml = (b'<testsuite name="s" tests="5" timestamp="2026-09-01T00:00:00"><testcase name="t1" time="0"/>'
           b'<testcase time="0"/></testsuite>')
    r = validate.check("r.xml", xml, NOW)
    texts = " | ".join(t for _l, t in r["problems"])
    assert not r["ok"] and "no name" in texts and "0 seconds" in texts and "tests=\"5\"" in texts and "2026-09-01" in texts
    assert "neither a file nor a class" in texts


def test_unknown_or_empty_files_are_errors(tmp_path, capsys):
    assert validate.check("x.txt", b"hello")["ok"] is False
    assert validate.check("e.xml", b"<testsuite/>")["problems"][0][1].startswith("no tests")
    (tmp_path / "ok.xml").write_bytes(b'<testsuite><testcase classname="a" name="b" time="1"/></testsuite>')
    assert validate.main([str(tmp_path / "*.xml")]) == 0 and "1 of 1 report(s)" in capsys.readouterr().out
