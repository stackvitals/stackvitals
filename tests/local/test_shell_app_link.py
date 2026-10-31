"""Every printable page links to the same section in the app, from history pages too."""
from stackvitals import shell


def test_each_page_opens_its_section_in_the_app():
    assert "href='index.html#/prs'>Open in the app</a>" in shell.nav("flow.html", {"flow.html", "index.html"})
    assert "href='index.html#/ci'>Open in the app</a>" in shell.nav("ci.html", {"ci.html", "index.html"})
    assert "href='../index.html#/ci'>Open in the app</a>" in shell.nav(None, {"ci.html", "index.html"}, root="../", app_route="ci")
    assert "href='index.html#/'>Open in the app</a>" in shell.nav(None, {"index.html"})


def test_a_history_page_opens_its_item_in_the_app():
    from stackvitals.ci.report import render_detail
    item = {"state": "flaky", "flake_events": 2, "runs": 9, "workflow": ".github/workflows/ci.yml", "job": "test"}
    page = render_detail("job", "ignored", item, [], {"window_days": 30, "weekly": []}, "o/r", {"index.html"})
    assert "href='../index.html#/ci/job/ci.yml%20%2F%20test'>Open in the app</a>" in page
    page = render_detail("test", "tests.a::b c", {**item, "workflow": None}, [], {"window_days": 30, "weekly": []}, "o/r", {"index.html"})
    assert "#/ci/test/tests.a%3A%3Ab%20c'" in page


def test_the_whole_page_carries_it():
    html = shell.page("Team Flow", "o/r", "flow.html", "", "<p>x</p>", {"flow.html", "index.html"})
    assert "index.html#/prs" in html
