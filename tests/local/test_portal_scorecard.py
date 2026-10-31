from datetime import datetime, timezone

from stackvitals.portal.scorecard import DEFAULT_RULES, evaluate, load_rules

NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)
RULES = """
[[rule]]
id = "owners"
check = "owners_valid"
level = "bronze"

[[rule]]
id = "reviews-required"
check = "branch_rule"
rule = "pull_request"
level = "bronze"

[[rule]]
id = "ci-first-try"
check = "ci_first_try"
level = "silver"
peer = 50

[[rule]]
id = "security-policy"
check = "scorecard"
name = "Security-Policy"
min = 10
level = "gold"

[[exemption]]
repo = "acme/legacy"
rule = "reviews-required"
until = "2026-12-31"
reason = "being retired"
"""
BENCH = {"ci": {"groups": {"Go|1k-10k": {"repos": 300, "first_try_share": {"p10": 0.4, "p25": 0.6, "p50": 0.75, "p75": 0.85, "p90": 0.95}}}}}


def repo(**kw):
    base = {"name": "acme/api", "language": "Go", "stars": 2000, "owners": {"status": "valid"}, "rules": ["pull_request"],
            "modules": {"ci_first_try": "82%"}, "scorecard": {"Security-Policy": 10}}
    return {**base, **kw}


def test_levels_build_up_and_each_result_carries_its_evidence():
    rules, exemptions = load_rules(RULES)
    s = evaluate(repo(), rules, exemptions, NOW, BENCH)
    assert s["level"] == "gold" and [r["result"] for r in s["results"]] == ["pass"] * 4
    ci = next(r for r in s["results"] if r["id"] == "ci-first-try")
    assert "82%" in ci["evidence"] and "75%" in ci["evidence"] and "Go repos with 1k-10k stars" in ci["evidence"]


def test_a_failing_lower_rule_caps_the_level_and_missing_data_is_never_a_fail():
    rules, exemptions = load_rules(RULES)
    s = evaluate(repo(rules=[]), rules, exemptions, NOW, BENCH)
    assert s["level"] is None and next(r for r in s["results"] if r["id"] == "reviews-required")["result"] == "fail"
    no_ci = evaluate(repo(modules=None, scorecard=None), rules, exemptions, NOW, BENCH)
    assert no_ci["level"] == "bronze" and no_ci["not_available"] == 2
    assert {r["result"] for r in no_ci["results"] if r["level"] != "bronze"} == {"not available"}


def test_exemptions_count_until_their_end_date_and_say_why():
    rules, exemptions = load_rules(RULES)
    s = evaluate(repo(name="acme/legacy", rules=[]), rules, exemptions, NOW, BENCH)
    r = next(r for r in s["results"] if r["id"] == "reviews-required")
    assert r["result"] == "exempt" and "being retired" in r["evidence"] and s["level"] == "gold"
    later = evaluate(repo(name="acme/legacy", rules=[]), rules, exemptions, datetime(2027, 1, 2, tzinfo=timezone.utc), BENCH)
    assert later["level"] is None


def test_the_default_pack_loads_and_a_broken_rules_file_falls_back_to_it_with_a_note():
    rules, _ = load_rules(DEFAULT_RULES)
    assert {r["level"] for r in rules} == {"bronze", "silver", "gold"} and len(rules) >= 6
    from stackvitals.portal.scorecard import rules_or_default
    fallback, exemptions, notes = rules_or_default("[[rule]\nid = ")
    assert len(fallback) == len(rules) and exemptions == [] and "portal.toml" in notes[0]
    unknown, _, notes = rules_or_default('[[rule]]\nid = "x"\ncheck = "no_such_check"\nlevel = "bronze"\n')
    assert len(unknown) == len(rules) and "no_such_check" in notes[0]


def test_repo_files_come_from_the_community_profile_with_unknowns_kept_apart_from_missing():
    from test_portal_m1 import fake

    from stackvitals.portal.inventory import repo_files
    profile = {"files": {"readme": {"url": "x"}, "license": None, "contributing": {"url": "y"}, "code_of_conduct": None}}
    api = fake({"/repos/acme/web/community/profile": (200, profile)})("t", "acme/web")
    assert repo_files(api, {"name": "acme/web", "license": None}) == {"readme": True, "license": False, "contributing": True,
                                                                       "code_of_conduct": False, "org_defaults": []}
    # Private repos may refuse the profile: the readme is checked directly, the license comes from the repo, the rest is unknown.
    api = fake({"/repos/acme/api/readme": (200, {"name": "README.md"})})("t", "acme/api")
    assert repo_files(api, {"name": "acme/api", "license": "mit"}) == {"readme": True, "license": True, "contributing": None,
                                                                       "code_of_conduct": None}


def test_a_file_nobody_could_check_is_not_available_not_missing():
    rules, exemptions = load_rules('[[rule]]\nid = "c"\ncheck = "files"\nfiles = ["contributing"]\nlevel = "bronze"\n')
    s = evaluate({"name": "acme/api", "docs": {"readme": True, "contributing": None}}, rules, exemptions, NOW, None)
    assert s["results"][0]["result"] == "not available"


def test_openssf_scorecard_checks_are_read_for_public_repos_once_a_week():
    import httpx

    from stackvitals.portal.inventory import scorecard_checks
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"date": "2026-10-13", "checks": [{"name": "Security-Policy", "score": 10},
                                                                           {"name": "Pinned-Dependencies", "score": -1}]})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    got = scorecard_checks(client, "Acme/Web", None, NOW)
    assert got["checks"] == {"Security-Policy": 10, "Pinned-Dependencies": -1} and calls[0].endswith("/github.com/acme/web")
    assert scorecard_checks(client, "Acme/Web", got, NOW) is got and len(calls) == 1  # fetched this week already


def test_without_the_ci_module_portal_measures_first_try_green_itself_like_the_benchmark():
    # Real data (astral-sh): no repo ran CI Health, so every peer CI rule was "not available".
    from test_bench import run
    from test_portal_m1 import fake

    from stackvitals.portal.inventory import push_ci
    runs = [run(k, 300) for k in range(8)] + [run(9, 300, conclusion="failure")]
    api = fake({"/repos/acme/web/actions/runs": (200, {"workflow_runs": runs})})("t", "acme/web")
    ci = push_ci(api, "acme/web", datetime(2026, 10, 16, 12, tzinfo=timezone.utc))
    assert ci["pushes"] == 9 and round(ci["first_try_share"], 2) == 0.89
    rules, exemptions = load_rules(RULES)
    s = evaluate(repo(modules=None, ci=ci), rules, exemptions, NOW, BENCH)
    r = next(x for x in s["results"] if x["id"] == "ci-first-try")
    assert r["result"] == "pass" and "last 9 pushes" in r["evidence"]


def test_values_that_round_alike_show_a_decimal_and_gold_never_asks_for_perfect_ci():
    # Real data (astral-sh/setup-uv): "94%, needs 94%" failed; the top quarter of several groups is 100% first-try green.
    bench = {"ci": {"groups": {"Go|1k-10k": {"repos": 300, "first_try_share": {"p10": 0.4, "p25": 0.6, "p50": 0.9412,
                                                                                 "p75": 1.0, "p90": 1.0}}}}}
    rules, exemptions = load_rules('[[rule]]\nid = "ci"\ncheck = "ci_first_try"\npeer = 50\nlevel = "bronze"\n')
    r = evaluate(repo(modules={"ci_first_try": "93.75%"}), rules, exemptions, NOW, bench)["results"][0]
    assert r["result"] == "fail" and "93.8%" in r["evidence"] and "94.1%" in r["evidence"]
    defaults, _ = load_rules(DEFAULT_RULES)
    assert not [x for x in defaults if x["check"] == "ci_first_try" and x.get("peer", 0) > 50]


def test_a_repo_missing_from_openssf_says_so_plainly():
    rules, exemptions = load_rules(RULES)
    r = next(x for x in evaluate(repo(scorecard=None), rules, exemptions, NOW, BENCH)["results"] if x["id"] == "security-policy")
    assert r["result"] == "not available" and r["evidence"] == "OpenSSF has no Scorecard result for this repo"
