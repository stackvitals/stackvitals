"""PR rules as code: [[rules]] in the settings file, each a `when` (author kind, paths, size, change risk, labels, a
first-time author) and a `then` (a label, reviewers, one comment), applied once per pull request with the suite's own
signals; a dry-run rule only reports, and every rule can be replayed on past pull requests before it acts."""
from stackvitals.core.config import parse
from stackvitals.flow import rules

TOML = """
[[rules]]
name = "Agent changes to payments"
when = { author = "agent", paths = ["payments/"] }
then = { label = "needs-second-review", reviewers = ["amy", "@acme/payments"], comment = "An agent changed payments code." }

[[rules]]
name = "Big risky change"
when = { lines_over = 400, risk = "high" }
then = { label = "risky" }
dry_run = true
"""


def pr(n, paths, au="dev", at="User", lines=50, labels=(), head="feature"):
    return {"n": n, "paths": paths, "au": au, "at": at, "add": lines, "del": 0, "lb": list(labels), "head": head, "draft": False}


def test_rules_are_read_from_the_settings_file_and_bad_ones_are_named():
    cfg, notes = parse(TOML)
    assert [r["name"] for r in cfg["rules"]] == ["Agent changes to payments", "Big risky change"]
    assert cfg["rules"][1]["dry_run"] is True and cfg["rules"][0]["then"]["reviewers"] == ["amy", "@acme/payments"]
    _cfg, notes = parse('[[rules]]\nname = "x"\nwhen = { author = "robot" }\nthen = { label = "y" }\n'
                        '[[rules]]\nname = "z"\nwhen = { paths = ["a/"] }\nthen = {}\n')
    assert len(notes) == 2 and all("rules" in n for n in notes)


def test_a_matching_pr_gets_each_action_once_and_dry_run_rules_only_report():
    cfg = parse(TOML)[0]
    open_prs = [pr(1, ["payments/charge.py"], au="Copilot", at="Bot", head="copilot/x"), pr(2, ["docs/a.md"]),
                pr(3, ["core/big.py"], lines=900)]
    ctx = {"risk": {3: "high"}}
    acts, state, report = rules.plan(open_prs, cfg["rules"], ctx, {})
    kinds = sorted((a["kind"], a["n"]) for a in acts)
    assert kinds == [("comment", 1), ("label", 1), ("review", 1)]
    review = next(a for a in acts if a["kind"] == "review")
    assert review["body"] == {"reviewers": ["amy"], "team_reviewers": ["payments"]}
    assert report == {"Agent changes to payments": [1], "Big risky change": [3]}
    again, _state, _r = rules.plan(open_prs, cfg["rules"], ctx, state)
    assert again == []  # each rule acts on a pull request once


def test_a_rule_already_satisfied_adds_nothing():
    cfg = parse(TOML)[0]
    done = pr(1, ["payments/charge.py"], au="Copilot", at="Bot", labels=["needs-second-review"])
    acts, _s, _r = rules.plan([done], cfg["rules"][:1], {}, {"rules_done": ["Agent changes to payments:1:review",
                                                                          "Agent changes to payments:1:comment"]})
    assert acts == []


def test_first_time_authors_and_labels_can_be_conditions():
    cfg = parse('[[rules]]\nname = "Welcome"\nwhen = { first_time = true }\nthen = { label = "first-time" }\n'
                '[[rules]]\nname = "Security"\nwhen = { labels = ["security"] }\nthen = { reviewers = ["sec-lead"] }\n')[0]
    prs = [pr(1, ["a.py"], au="newbie"), pr(2, ["b.py"], au="amy", labels=["security"])]
    acts, _s, report = rules.plan(prs, cfg["rules"], {"first_time": {"newbie"}}, {})
    assert report == {"Welcome": [1], "Security": [2]} and len(acts) == 2


def test_a_rule_is_replayed_on_past_pull_requests_before_it_acts():
    cfg = parse(TOML)[0]
    past = [pr(i, ["payments/x.py"] if i % 4 == 0 else ["web/y.ts"], au="Copilot" if i % 2 == 0 else "dev",
               at="Bot" if i % 2 == 0 else "User") for i in range(1, 41)]
    got = rules.replay(cfg["rules"], past, {})
    first = got["Agent changes to payments"]
    assert first["matched"] == 10 and first["of"] == 40 and first["examples"][:3] == [4, 8, 12]
