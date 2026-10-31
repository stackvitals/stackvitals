import json
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from mergescout.bench.shared import build, one_per_account, read_issue
from stackvitals.ci import share

NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)
STATS = {"pushes": 137, "median_s": 431, "p90_s": 1200, "fail_share": 0.1234, "first_try_share": 0.8461,
         "rerun_share": 0.0312, "workflows": 4}
SID = "0123456789abcdef"


def sid(i: int) -> str:
    return f"{i:016x}"


def body(doc: dict) -> str:
    # What GitHub's issue form writes for a json-rendered textarea.
    return f"### Figures\n\n```json\n{json.dumps(doc, indent=1)}\n```\n"


def test_figures_are_rounded_carry_no_name_unless_allowed_and_need_enough_pushes():
    doc = share.figures(STATS, "Python", 2500, SID, NOW)
    assert doc["pushes"] == 140 and doc["median_s"] == 420 and doc["first_try_share"] == 0.85
    assert doc["tier"] == "1k-10k" and doc["month"] == "2026-10" and "repo" not in doc and doc["id"] == SID
    assert set(doc) == set(share.FIELDS) and "stackvitals" not in doc["kind"]
    assert share.figures(STATS, "Python", 2500, SID, NOW, name="o/r")["repo"] == "o/r"
    assert share.figures({**STATS, "pushes": 12}, "Python", 2500, SID, NOW) is None


def test_the_share_id_is_random_kept_and_says_nothing_about_the_repo(tmp_path):
    first = share.share_id(tmp_path)
    assert len(first) == 16 and share.share_id(tmp_path) == first and share.share_id(tmp_path / "other") != first


def test_the_link_opens_the_labelled_issue_form_and_its_body_reads_back():
    doc = share.figures(STATS, "Go", 50, SID, NOW)
    url = share.link(doc)
    q = parse_qs(urlparse(url).query)
    assert url.startswith("https://github.com/stackvitals/stackvitals/issues/new?") and q["template"] == ["benchmark.yml"]
    assert read_issue({"body": body(json.loads(q["figures"][0]))}) == doc and len(url) < 4000


def test_bad_or_out_of_range_bodies_are_dropped_and_fast_ci_is_kept():
    good = share.figures(STATS, "Go", 50, SID, NOW)
    assert read_issue({"body": "hello"}) is None
    assert read_issue({"body": body({**good, "first_try_share": 1.7})}) is None
    assert read_issue({"body": body({**good, "extra": "x"})}) is None
    assert read_issue({"body": body({**good, "median_s": -5})}) is None
    assert read_issue({"body": body({**good, "month": "9999-99"})}) is None
    assert read_issue({"body": body({**good, "median_s": 0, "p90_s": 0})}) is not None


def test_groups_publish_only_with_ten_members_latest_month_per_id_wins():
    docs = [share.figures({**STATS, "median_s": 100 + i * 60}, "Go", 50, sid(i), NOW) for i in range(12)]
    old = share.figures({**STATS, "median_s": 9999}, "Go", 50, sid(0), datetime(2026, 9, 1, tzinfo=timezone.utc))
    docs += [share.figures(STATS, "Rust", 50, sid(100 + i), NOW) for i in range(4)]
    out = build(docs + [old])
    assert set(out["groups"]) == {"Go|100-1k", "Go|all", "all|100-1k", "all|all"}
    assert out["groups"]["Go|100-1k"]["repos"] == 12 and out["groups"]["all|all"]["repos"] == 16
    assert out["groups"]["Go|100-1k"]["median_s"]["p90"] < 9999  # the September figures were replaced
    assert out["private"] is True and "built_at" in out


def test_one_account_counts_once_and_cannot_take_over_another_repo_s_id():
    issue = lambda who, doc, at: {"user": {"login": who}, "created_at": at, "body": body(doc)}  # noqa: E731
    mine = share.figures(STATS, "Go", 50, sid(1), NOW)
    got = one_per_account([issue("a", mine, "2026-10-02"), issue("A", share.figures(STATS, "Go", 50, sid(2), NOW), "2026-10-03"),
                           issue("b", share.figures(STATS, "Go", 50, sid(3), NOW), "2026-10-01"),
                           issue("evil", {**mine, "median_s": 99990}, "2026-10-05"),
                           {"user": {"login": "c"}, "body": "no figures"}], now=NOW)
    assert sorted(d["id"] for d in got) == [sid(2), sid(3)]  # a's newer filing replaced its first; evil's copy is ignored
    assert one_per_account([issue("z", {**mine, "month": "2027-01"}, "2026-10-01")], now=NOW) == []


def test_the_ci_report_names_shared_peers_when_they_are_used():
    from stackvitals.ci.bench import SHARED_ARE, compare
    from stackvitals.ci.report import _bench
    docs = [share.figures({**STATS, "median_s": 100 + i * 60}, "Go", 50, sid(i), NOW) for i in range(12)]
    got = compare(STATS, build(docs), "Rust", 50, everyone="repos that shared their figures")
    assert got["group"] == "repos with 100-1k stars"
    head, lines = _bench({"benchmark": {**got, "peers": SHARED_ARE}})
    assert "chose to share their rounded CI figures" in head and "may not resemble" not in head and lines


def test_the_collector_reads_every_repo_and_skips_one_it_cannot_read(monkeypatch, tmp_path, capsys):
    # The private repo and the public home both hold figures; a repo still private to the token is skipped.
    import httpx
    from mergescout.bench import shared
    seen = []

    def fake(repo, token, client=None):
        seen.append(repo)
        if repo == "stackvitals/stackvitals":
            raise httpx.HTTPStatusError("404", request=httpx.Request("GET", "https://api.github.com"), response=httpx.Response(404))
        return []
    monkeypatch.setattr(shared, "fetch", fake)
    monkeypatch.setenv("GH_TOKEN", "x")
    out = tmp_path / "s.json"
    assert shared.main(["--repo", "kaushik-yadav/merge-scout", "--repo", "stackvitals/stackvitals", "--out", str(out)]) == 0
    assert seen == ["kaushik-yadav/merge-scout", "stackvitals/stackvitals"] and out.exists()
    assert "stackvitals/stackvitals: skipped" in capsys.readouterr().out
