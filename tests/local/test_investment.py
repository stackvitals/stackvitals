"""Investment mix: where the merged work goes (feature, fix, maintenance, security, docs), decided from the repo's own
label rules, the linked Jira or Linear issue type, common labels, Conventional Commit titles or the files touched."""
from datetime import datetime, timezone

from stackvitals.core.investment import classify, mix

NOW = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)


def pr(n, title="Change things", labels=(), paths=("src/app.py",), merged="2026-10-05T10:00:00Z", au="amy", at="User"):
    return {"n": n, "ti": title, "lb": list(labels), "paths": list(paths), "mg": merged, "au": au, "at": at}


def test_each_pull_request_gets_a_category_and_the_reason():
    assert classify(pr(1, labels=["type: bug"])) == ("fix", "label type: bug")
    assert classify(pr(2, labels=["kind/feature"])) == ("feature", "label kind/feature")
    assert classify(pr(3, title="feat(api): add search")) == ("feature", "title feat:")
    assert classify(pr(4, title="Update guide", paths=["docs/guide.md", "README.md"])) == ("docs", "only docs files")
    assert classify(pr(5, title="Bump CI", paths=[".github/workflows/ci.yml", "package-lock.json"])) == \
        ("maintenance", "only CI or dependency files")
    assert classify(pr(6)) == ("other", "no label, issue type, changelog fragment, title or file pattern")


def test_the_order_puts_the_repos_rules_first_and_security_before_other_labels():
    rules = {"maintenance": ["Area: Platform"]}
    assert classify(pr(1, labels=["bug", "area: platform"]), rules) == ("maintenance", "label area: platform (this repo's rule)")
    assert classify(pr(2, title="fix: escape input", labels=["bug", "security"])) == ("security", "label security")
    # A linked Jira or Linear issue's type beats common labels and titles, not the repo's own rules or security.
    assert classify(pr(3, title="chore: tidy", labels=["enhancement"]), None, "BUG") == ("fix", "issue type bug")
    assert classify(pr(4, title="chore: tidy"), None, "TASK") == ("maintenance", "title chore:")


def test_the_mix_counts_people_and_agents_by_month_and_keeps_update_bots_apart():
    prs = [pr(1, labels=["bug"], merged="2026-09-02T10:00:00Z"), pr(2, title="feat: x", merged="2026-10-03T10:00:00Z"),
           pr(3, title="feat: y", merged="2026-10-04T10:00:00Z", au="Copilot", at="Bot"),
           pr(4, title="chore(deps): bump x", merged="2026-10-05T10:00:00Z", au="dependabot[bot]", at="Bot"),
           pr(5, labels=["docs"], merged="2026-03-30T10:00:00Z"),  # before the 6 months
           pr(6, labels=["bug"], merged=None)]
    out = mix(prs, NOW)
    assert out["since"] == "2026-05" and out["n"] == 3 and out["bots"] == 1
    assert out["months"] == [{"month": "2026-09", "n": 1, "counts": {"feature": 0, "fix": 1, "maintenance": 0, "security": 0, "docs": 0, "other": 0}},
                             {"month": "2026-10", "n": 2, "counts": {"feature": 2, "fix": 0, "maintenance": 0, "security": 0, "docs": 0, "other": 0}}]
    assert out["counts"]["feature"] == 2 and out["shares"]["fix"] == 0.3333
    assert out["decided_by"] == {"title": 2, "label": 1} and out["examples"]["feature"] == [2, 3]
    assert mix([pr(4, au="dependabot[bot]", at="Bot")], NOW) is None


def test_tracker_issue_types_are_used_when_jira_or_linear_is_connected():
    out = mix([pr(7, title="WEB-12 checkout"), pr(8, title="WEB-13 export")], NOW, tracker_types={7: "BUG", 8: "REQUIREMENT"})
    assert out["counts"]["fix"] == 1 and out["counts"]["feature"] == 1 and out["decided_by"] == {"issue": 2}


def test_label_prefixes_and_emoji_are_read_past():
    assert classify(pr(1, labels=["🐛 bug"]))[0] == "fix" and classify(pr(2, labels=["T-feature"]))[0] == "feature"
    assert classify(pr(3, labels=["Type: Documentation"]))[0] == "docs" and classify(pr(4, labels=["priority: high"]))[0] == "other"


def test_the_repo_sorts_its_own_labels_in_its_settings():
    from stackvitals.core import schema
    from stackvitals.core.config import parse
    cfg, notes = parse('[investment.labels]\nfeature = ["kind/feature"]\nmaintenance = ["area: platform"]\n')
    assert notes == [] and cfg["investment"]["labels"] == {"feature": ["kind/feature"], "maintenance": ["area: platform"]}
    cfg, notes = parse('[investment.labels]\nfun = ["x"]\nfix = "bug"\n')
    assert cfg["investment"]["labels"] == {} and len(notes) == 2 and "investment.labels.fun" in notes[0]
    assert parse("")[0]["investment"]["labels"] == {}
    s = next(s for s in schema.SETTINGS if s.key == "investment.labels")
    assert s.kind == "teams" and s.module == "delivery"


def test_the_app_can_write_the_label_rules_into_the_settings_file():
    from stackvitals.core import tomledit
    from stackvitals.core.config import parse
    text = tomledit.apply('[delivery]\nproduction = ["prod"]\n', {"investment.labels": {"feature": ["kind/feature"], "docs": ["area: docs"]}})
    assert parse(text)[0]["investment"]["labels"] == {"feature": ["kind/feature"], "docs": ["area: docs"]}
    assert 'production = ["prod"]' in text


def test_a_pr_linked_to_several_issues_takes_the_most_telling_type():
    from stackvitals.core.investment import tracker_types
    issues = [{"key": "WEB-1", "type": "TASK"}, {"key": "WEB-2", "type": "BUG"}, {"key": "WEB-3", "type": "REQUIREMENT"}]
    prs = [pr(1, title="WEB-1 WEB-2 tidy"), pr(2, title="WEB-3 search"), pr(3, title="no link")]
    assert tracker_types(prs, issues) == {1: "BUG", 2: "REQUIREMENT"}


def test_the_delivery_page_carries_the_investment_mix():
    import sys
    sys.path.insert(0, "tests/local")
    from test_core_delivery import NOW as DNOW
    from test_core_delivery_surfaces import sample

    from stackvitals.core.config import parse
    from stackvitals.core.delivery import build
    flow, repo = sample()
    flow["closed"][0]["lb"] = ["area: platform"]
    cfg = parse('[investment.labels]\nmaintenance = ["area: platform"]\n')[0]
    out = build(flow, repo, {"runs": [], "jobs": []}, [], DNOW, 90, cfg)
    inv = out["investment"]
    assert inv["counts"]["maintenance"] >= 1 and inv["decided_by"]["label"] >= 1 and inv["n"] == sum(inv["counts"].values())


def test_the_printable_delivery_pages_show_where_the_work_went():
    from stackvitals.core import delivery_report
    inv = mix([pr(1, labels=["bug"], merged="2026-09-02T10:00:00Z"), pr(2, title="feat: x", merged="2026-10-03T10:00:00Z"),
               pr(3, title="feat: y", merged="2026-10-04T10:00:00Z")], NOW)
    import sys
    sys.path.insert(0, "tests/local")
    from test_core_delivery import NOW as DNOW
    from test_core_delivery_surfaces import sample

    from stackvitals.core.config import parse
    from stackvitals.core.delivery import build
    flow, repo = sample()
    out = build(flow, repo, {"runs": [], "jobs": []}, [], DNOW, 90, parse("")[0])
    out["investment"] = inv
    page = delivery_report.render_html(out, "o/r")
    assert "<h2>Where the work went</h2>" in page and "feature 67%" in page
    assert "<tr><td>2026-09</td><td>0</td><td>1</td><td>0</td><td>0</td><td>0</td><td>0</td><td>1</td></tr>" in page
    md = delivery_report.render_markdown(out, "o/r")
    assert "Where the work went (3 merged PRs since 2026-05): feature 67%, fix 33%." in md


# Real data (pip, pytest, aiohttp, xdsl; 2026-10-21): 61-89% of merged PRs had no label or Conventional Commit title.
# They carry changelog fragments (news/, changelog/, CHANGES/), component prefixes and plain leading verbs.
def test_changelog_fragments_prefixes_and_leading_verbs_sort_most_real_prs():
    assert classify(pr(1, title="Fix broken pipe", paths=["src/pip/x.py", "news/11608.bugfix.rst"])) == ("fix", "changelog fragment bugfix")
    assert classify(pr(2, title="Add a space", paths=["src/a.py", "changelog/14430.improvement.rst"])) == \
        ("feature", "changelog fragment improvement")
    assert classify(pr(3, title="Don't re-await main_task", paths=["aiohttp/web.py", "CHANGES/12493.bugfix"]))[0] == "fix"
    assert classify(pr(4, title="Remove pytest_plugin", paths=["aiohttp/p.py", "CHANGES/10762.breaking.rst"]))[0] == "maintenance"
    assert classify(pr(5, title="Update docs", paths=["src/a.py", "news/1.doc.rst"]))[0] == "docs"
    assert classify(pr(6, title="bug: (core) Fix Region.erase assertion condition")) == ("fix", "title bug:")
    assert classify(pr(7, title="dialects: (llvm) add ShuffleVectorOp with backend converter")) == ("feature", "title verb add")
    assert classify(pr(8, title="[3.14] Fix AppKey repr tests for collections.abc typing")) == ("fix", "title verb fix")
    assert classify(pr(9, title="testing: (convert-arith-to-riscv) use custom syntax in input [NFC]")) == ("maintenance", "title testing:")
    assert classify(pr(10, title="Speed up resolver", paths=["tests/test_resolver.py", "tests/conftest.py"])) == \
        ("maintenance", "only test files")
    assert classify(pr(11, title='Revert "Remove __pycache__ when package is removed"')) == ("fix", "title verb revert")
    assert classify(pr(12, title="Release/26.1.2")) == ("maintenance", "title release")
    assert classify(pr(13, title="backend: all used regs within region is a set"))[0] == "other"


def test_more_real_titles_sort_while_ambiguous_ones_stay_unsorted():
    # Real titles from pytest, dask, cosmos and guidellm (2026-10-21).
    assert classify(pr(1, title="[refactor] Use match case in ``_get_auto_indent``"))[0] == "maintenance"
    assert classify(pr(2, title="[v0.7 CLI Refactor] Rework BackendArgs to be the authoritative config location"))[0] == "maintenance"
    assert classify(pr(3, title="Don't lose worker startup exception when its process exit is observed first")) == \
        ("fix", "title verb don't")
    assert classify(pr(4, title="Restore type hints broken by lazy imports in cosmos/__init__.py"))[0] == "fix"
    assert classify(pr(5, title="Defer TaskInstance import in cluster policy to fix sentry init crash")) == ("fix", "title mentions a fix")
    assert classify(pr(6, title="Feat/multi turn tools responses"))[0] == "feature"
    assert classify(pr(7, title="Make synthetic_text output_tokens optional and improve CLI errors"))[0] == "other"


def test_a_release_pr_is_maintenance_even_though_it_gathers_every_fragment():
    # Real data (pip "Release 26.2"): a release PR removes all the news fragments, so the fragments can't sort it.
    gathered = ["news/1.bugfix.rst", "news/2.feature.rst", "NEWS.rst", "src/pip/__init__.py"]
    assert classify(pr(1, title="Release 26.2", paths=gathered)) == ("maintenance", "title release")
    assert classify(pr(2, title="Prepare release 1.4.0", paths=gathered))[0] == "maintenance"
    assert classify(pr(3, title="v2.3.1", paths=gathered))[0] == "maintenance"
    assert classify(pr(4, title="Releases page: show dates", paths=["src/a.py", "news/3.feature.rst"]))[0] == "feature"
