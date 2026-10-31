from datetime import datetime, timezone

from stackvitals.deps.dossier import dossier
from stackvitals.deps.evidence import index_evidence

NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)


def cell(pkg, bump, prs=120, repos=50, merged=100, closed=8, ci_known=110, ci_failed=9, expected=8.0, extra=6, reverted=0, eco="pypi"):
    return {"ecosystem": eco, "package": pkg, "bump": bump, "prs": prs, "repos": repos, "merged": merged,
            "closed_unmerged": closed, "ci_known": ci_known, "ci_failed": ci_failed, "expected_failed": expected,
            "extra_commits": extra, "reverted": reverted, "eco_inferred": False}


def mapped(pkg, repo, link="verified", eco="pypi", last="2026-09-01", releases=6, **kw):
    return {"ecosystem": eco, "package": pkg, "version": "2.0.0", "repo": repo, "link": link, "licenses": ["MIT"], "advisories": [],
            "deprecated": False, "status": None, "releases_12m": releases, "last_release": last, "first_release": "2015-01-01", **kw}


def quarters(rates, hours, tops=(0.4, 0.4, 0.4, 0.4)):
    names = ["2025Q4", "2026Q1", "2026Q2", "2026Q3"]
    return [{"quarter": q, "outside_opened": 30, "outside_decided": 25, "outside_merge_rate": r, "first_response_hours": h,
             "merges": 40, "top_merger_share": t} for q, r, h, t in zip(names, rates, hours, tops)]


def evidence(cells=(), packages=(), trends=None, osv=None):
    return index_evidence({"cells": list(cells), "built_at": "2026-10-18T09:55:00Z"},
                          {"packages": {f"{p['ecosystem']}:{p['package']}": p for p in packages}, "built_at": "2026-10-18T09:55:00Z"},
                          {"repos": trends or {}, "built_at": "2026-10-18T09:55:00Z"},
                          {"packages": osv or {}, "complete": True, "built_at": "2026-10-18T09:55:00Z"})


def texts(d):
    return " | ".join(line["text"] for line in d["lines"])


def test_a_healthy_package_is_use_with_its_evidence_and_counts():
    ev = evidence([cell("requests", "minor"), cell("requests", "patch", prs=300, repos=120, ci_failed=20, expected=19.0)],
                  [mapped("requests", "psf/requests")],
                  {"psf/requests": {"stars": 50000, "quarters": quarters([0.7, 0.72, 0.68, 0.7], [20, 18, 22, 19]),
                                    "direction": {"outside_merge_rate": "steady", "first_response_hours": "steady"}, "peers": {}}},
                  {"pypi:requests": {"advisories": 9, "last_2y": 2, "unfixed": 0, "latest": "2026-06-09", "severity": {"MODERATE": 2},
                                     "malware": False, "ids": ["GHSA-9hjg-9r4m-mvj7"]}})
    d = dossier("pypi", "Requests", ev, NOW)
    assert d["verdict"] == "use" and d["package"] == "requests" and d["repo"] == "psf/requests"
    t = texts(d)
    assert "120 PRs" in t and "50 repos" in t and "signed" in t and "9 advisories" in t
    assert "safe" not in t.lower()


def test_a_malware_record_or_unfixed_advisory_means_investigate():
    ev = evidence([cell("event-stream", "patch", eco="npm")], [mapped("event-stream", "dominictarr/event-stream", eco="npm")],
                  osv={"npm:event-stream": {"advisories": 1, "last_2y": 0, "unfixed": 1, "latest": "2018-11-26", "severity": {},
                                            "malware": True, "ids": ["MAL-2025-7"]}})
    d = dossier("npm", "event-stream", ev, NOW)
    assert d["verdict"] == "investigate" and "malware" in d["reasons"][0] and "MAL-2025-7" in d["reasons"][0]


def test_a_young_package_whose_repo_does_not_name_it_back_means_monitor_but_no_repo_at_all_means_investigate():
    # Real data: typescript's root manifest is "@typescript/repo"; a monorepo or generated package is not proof of harm.
    ev = evidence([cell("left-pad", "patch", eco="npm")], [mapped("left-pad", "evil/fork", link="claimed_unconfirmed", eco="npm",
                                                                  first_release="2025-06-01")])
    d = dossier("npm", "left-pad", ev, NOW)
    assert d["verdict"] == "monitor" and "evil/fork" in d["reasons"][0]
    ev = evidence([cell("ghost", "patch", eco="npm")], [mapped("ghost", None, link=None, eco="npm", first_release="2026-05-01")])
    assert dossier("npm", "ghost", ev, NOW)["verdict"] == "investigate"


def test_upgrades_failing_well_above_these_repos_usual_mean_monitor():
    ev = evidence([cell("django", "minor", prs=60, repos=25, ci_known=60, ci_failed=24, expected=5.0, reverted=2)],
                  [mapped("django", "django/django")])
    d = dossier("pypi", "django", ev, NOW)
    assert d["verdict"] == "monitor"
    assert "failed CI in 40% of 60" in d["reasons"][0] and "usually 8%" in d["reasons"][0]


def test_a_maintainer_team_pulling_back_means_monitor():
    ev = evidence([cell("lib", "patch")], [mapped("lib", "acme/lib")],
                  {"acme/lib": {"stars": 3000, "quarters": quarters([0.8, 0.7, 0.4, 0.2], [10, 20, 60, 200], (0.5, 0.6, 1.0, 1.0)),
                                "direction": {"outside_merge_rate": "falling", "first_response_hours": "slower"},
                                "peers": {"first_response_hours": {"place": "slower than most similar repos", "peers": 40}}}})
    d = dossier("pypi", "lib", ev, NOW)
    assert d["verdict"] == "monitor" and any("falling" in r or "80%" in r or "0.8" in r for r in d["reasons"])
    assert "one person" in texts(d)


def test_thin_history_says_so_and_gives_no_verdict():
    # Real data: 925 of 2,266 packages had little history; calling them "monitor" made the verdict mean nothing.
    ev = evidence([cell("tiny", "patch", prs=5, repos=3)], [mapped("tiny", "me/tiny")])
    d = dossier("pypi", "tiny", ev, NOW)
    assert d["verdict"] is None and "not enough" in texts(d).lower() and "5 PRs from 3 repos" in texts(d)


def test_a_package_outside_the_evidence_set_gets_no_verdict():
    d = dossier("npm", "never-heard-of-it", evidence(), NOW)
    assert d["verdict"] is None and "not in the evidence set" in texts(d)


def test_no_release_for_two_years_is_noted():
    ev = evidence([cell("old", "patch")], [mapped("old", "me/old", last="2024-01-01", releases=0)])
    d = dossier("pypi", "old", ev, NOW)
    assert d["verdict"] == "monitor" and "no release since 2024-01-01" in texts(d)


def test_one_merger_and_a_low_peer_place_are_facts_not_warnings():
    # Real data: 866 packages were "monitor" only because one lead merges (requests: 93%), and big libraries merge
    # fewer drive-by PRs than small repos; only a worsening trend warns.
    ev = evidence([cell("requests", "minor")], [mapped("requests", "psf/requests")],
                  {"psf/requests": {"stars": 50000, "quarters": quarters([0.5, 0.5, 0.5, 0.5], [20, 20, 20, 20], (0.9, 0.9, 0.9, 0.93)),
                                    "direction": {"outside_merge_rate": "steady", "first_response_hours": "steady"},
                                    "peers": {"outside_merge_rate": {"place": "merges outside PRs less than most similar repos", "peers": 302}}}})
    d = dossier("pypi", "requests", ev, NOW)
    assert d["verdict"] == "use" and "one person" in texts(d) and "302 similar repos" in texts(d)


def test_a_steady_but_tiny_merge_rate_is_not_a_good_sign():
    ev = evidence([cell("lodash", "minor", eco="npm")], [mapped("lodash", "lodash/lodash", eco="npm")],
                  {"lodash/lodash": {"stars": 60000, "quarters": quarters([0.0, 0.02, 0.0, 0.0], [22, 22, 22, 22]),
                                     "direction": {"outside_merge_rate": "steady", "first_response_hours": "steady"}, "peers": {}}})
    lines = dossier("npm", "lodash", ev, NOW)["lines"]
    merged = next(x for x in lines if "Outside PRs merged" in x["text"])
    assert merged["signal"] != "good" and "0%" in merged["text"]


def test_upgrades_without_a_known_size_are_labelled_so():
    ev = evidence([cell("lodash", "unknown", eco="npm")], [mapped("lodash", "lodash/lodash", eco="npm")])
    assert "size unknown" in texts(dossier("npm", "lodash", ev, NOW)).lower()


def test_an_old_package_without_a_linked_repo_is_monitor_a_new_one_is_investigate():
    # Real data: protobuf, beautifulsoup4 and docutils link no source repo on deps.dev (some live off GitHub).
    ev = evidence([cell("protobuf", "minor")], [mapped("protobuf", None, link=None, first_release="2008-07-07")])
    assert dossier("pypi", "protobuf", ev, NOW)["verdict"] == "monitor"
    ev = evidence([cell("brand-new", "minor")], [mapped("brand-new", None, link=None, first_release="2026-03-01")])
    assert dossier("pypi", "brand-new", ev, NOW)["verdict"] == "investigate"


def test_use_reasons_lead_with_history_not_with_the_absence_of_advisories():
    ev = evidence([cell("requests", "minor")], [mapped("requests", "psf/requests")],
                  osv={"pypi:requests": {"advisories": 0, "last_2y": 0, "unfixed": 0, "latest": None, "severity": {},
                                         "malware": False, "ids": []}})
    d = dossier("pypi", "requests", ev, NOW)
    assert d["verdict"] == "use" and d["reasons"][0].startswith("Minor upgrades")


def test_a_bounded_advisory_is_open_only_while_the_newest_version_is_inside_the_bound():
    osv = {"pypi:pyjwt": {"advisories": 2, "last_2y": 2, "unfixed": 0, "last_affected": ["2.13.0"], "disputed": 1, "latest": "2026-09-30",
                          "severity": {}, "malware": False, "ids": []}}
    newer = evidence([cell("pyjwt", "minor")], [{**mapped("pyjwt", "jpadilla/pyjwt"), "version": "2.15.1"}], osv=osv)
    assert dossier("pypi", "pyjwt", newer, NOW)["verdict"] != "investigate"
    inside = evidence([cell("pyjwt", "minor")], [{**mapped("pyjwt", "jpadilla/pyjwt"), "version": "2.13.0"}], osv=osv)
    d = dossier("pypi", "pyjwt", inside, NOW)
    assert d["verdict"] == "investigate" and "2.13.0" in d["reasons"][0]


def owners_evidence(events, current, since="2026-08-01"):
    ev = evidence([cell("axios", "minor", eco="npm")], [mapped("axios", "axios/axios", eco="npm")])
    ev["owners"] = {"npm:axios": {"current": current, "since": since, "events": events}}
    return ev


def test_a_release_published_outside_trusted_ci_is_an_alarm_and_a_new_maintainer_a_warning():
    current = {"version": "1.7.1", "publisher": "newperson", "trusted": False, "maintainers": ["jasonsaayman", "newperson"]}
    ev = owners_evidence([{"kind": "trusted_lost", "date": "2026-10-10", "version": "1.7.1"},
                          {"kind": "maintainer_added", "date": "2026-10-10", "who": ["newperson"]}], current)
    d = dossier("npm", "axios", ev, NOW)
    assert d["verdict"] == "investigate" and "2026-10-10" in d["reasons"][0] and "trusted" in d["reasons"][0]
    assert any("newperson" in x["text"] and x["signal"] == "warn" for x in d["lines"])


def test_old_owner_changes_and_current_owners_are_facts():
    current = {"version": "1.7.0", "publisher": "GitHub Actions", "trusted": True, "maintainers": ["jasonsaayman"]}
    ev = owners_evidence([{"kind": "maintainer_added", "date": "2026-03-01", "who": ["jasonsaayman"]}], current, since="2026-01-01")
    d = dossier("npm", "axios", ev, NOW)
    assert d["verdict"] == "use" and "trusted CI publishing" in " ".join(x["text"] for x in d["lines"])


def test_closed_upgrades_warn_from_40_percent_the_share_that_predicted_later_closes():
    # Backtest (crawl sample): flagged at 30% -> later closes 1.3x others; at 40% -> 3.0x.
    ev = evidence([cell("lib", "minor", prs=100, closed=35, merged=65)], [mapped("lib", "acme/lib")])
    assert dossier("pypi", "lib", ev, NOW)["verdict"] == "use"
    ev = evidence([cell("lib", "minor", prs=100, closed=45, merged=55)], [mapped("lib", "acme/lib")])
    assert dossier("pypi", "lib", ev, NOW)["verdict"] == "monitor"


def test_upgrade_sizes_combined_count_when_no_single_size_is_enough():
    # Real data: httpx had 33 upgrade PRs from 23 repos, split across sizes so no cell reached 30, and got no verdict.
    ev = evidence([cell("httpx", "minor", prs=18, repos=15, merged=14, closed=2, ci_known=0, ci_failed=0, expected=0),
                   cell("httpx", "patch", prs=15, repos=12, merged=13, closed=1, ci_known=0, ci_failed=0, expected=0)],
                  [mapped("httpx", "encode/httpx", link="claimed_checked")])
    d = dossier("pypi", "httpx", ev, NOW)
    assert d["verdict"] == "use" and "sizes combined" in d["reasons"][0] and "33 PRs" in d["reasons"][0]


def test_one_advisory_reads_in_the_singular():
    ev = evidence([cell("x", "minor")], [mapped("x", "a/x")],
                  osv={"pypi:x": {"advisories": 1, "last_2y": 0, "unfixed": 0, "latest": "2022-04-28", "severity": {}, "malware": False,
                                  "ids": []}})
    assert "1 advisory in total" in texts(dossier("pypi", "x", ev, NOW))


# Second hand-check (20 dossiers, fresh evidence): 7 verdicts too harsh, 1 too soft.
def test_an_unconfirmed_link_on_an_established_package_is_a_fact_not_a_warning():
    # swiper, postcss-lab-function: the manifest lives in a subfolder; only young packages warn.
    old = evidence([cell("swiper", "minor", eco="npm")], [mapped("swiper", "nolimits4web/swiper", link="claimed_unconfirmed", eco="npm")])
    assert dossier("npm", "swiper", old, NOW)["verdict"] == "use"
    young = evidence([cell("newpkg", "minor", eco="npm")],
                     [mapped("newpkg", "big/popular", link="claimed_unconfirmed", eco="npm", first_release="2026-04-01")])
    assert dossier("npm", "newpkg", young, NOW)["verdict"] == "monitor"


def test_a_low_upgrade_merge_rate_is_not_marked_good():
    ev = evidence([cell("gradio", "minor", prs=100, merged=27, closed=20)], [mapped("gradio", "gradio-app/gradio")])
    line = next(x for x in dossier("pypi", "gradio", ev, NOW)["lines"] if x["source"] == "ledger")
    assert line["signal"] == "info" and "27%" in line["text"]


def test_evidence_from_a_guessed_ecosystem_is_shown_but_does_not_decide():
    # ubuntu: Docker image bumps in a JavaScript repo were counted as the npm package.
    ev = evidence([{**cell("ubuntu", "major", prs=80, ci_known=60, ci_failed=40, expected=5.0, eco="npm"), "eco_inferred": True}],
                  [mapped("ubuntu", "someone/ubuntu", eco="npm")])
    d = dossier("npm", "ubuntu", ev, NOW)
    line = next(x for x in d["lines"] if x["source"] == "ledger")
    assert line["signal"] == "info" and "guessed" in line["text"] and d["verdict"] is None


def test_a_quarter_where_most_outside_prs_are_still_open_is_a_warning_and_lines_show_counts():
    # dask: 71 of 89 outside PRs from last quarter still open, while the merge rate among decided ones looked steady.
    q = quarters([0.6, 0.6, 0.62, 0.6], [10, 10, 10, 10])
    q[-1] = {**q[-1], "outside_opened": 89, "outside_decided": 18}
    ev = evidence([cell("dask", "minor")], [mapped("dask", "dask/dask")],
                  {"dask/dask": {"stars": 12000, "quarters": q, "direction": {"outside_merge_rate": "steady", "first_response_hours": "steady"},
                                 "peers": {"first_response_hours": {"place": "faster than most similar repos", "peers": 199}}}})
    d = dossier("pypi", "dask", ev, NOW)
    assert d["verdict"] == "monitor" and "71 of 89" in d["reasons"][0]
    t = texts(d)
    assert "18 decided" in t and "First maintainer answers against 199 similar repos" in t


def test_a_crawled_repo_with_too_few_outside_prs_says_so():
    q = [{**x, "outside_merge_rate": None, "first_response_hours": None, "top_merger_share": None} for x in quarters([0] * 4, [0] * 4)]
    ev = evidence([cell("pbkdf2", "minor", eco="npm")], [mapped("pbkdf2", "browserify/pbkdf2", eco="npm")],
                  {"browserify/pbkdf2": {"stars": 200, "quarters": q, "direction": {"outside_merge_rate": None, "first_response_hours": None},
                                         "peers": {}}})
    assert "too few outside PRs" in texts(dossier("npm", "pbkdf2", ev, NOW))


def test_a_malware_line_names_the_bad_versions_and_whether_the_current_one_is_among_them():
    osv = lambda bad: {"npm:rhf": {"advisories": 1, "last_2y": 1, "unfixed": 0, "latest": "2026-09-30", "severity": {},  # noqa: E731
                                   "malware": True, "malware_ids": ["MAL-2026-5"], "malware_versions": bad, "ids": []}}
    ev = evidence([cell("rhf", "patch", eco="npm")], [mapped("rhf", "a/rhf", eco="npm", version="7.74.0")], osv=osv(["7.73.0"]))
    d = dossier("npm", "rhf", ev, NOW)
    assert d["verdict"] == "investigate" and "7.73.0" in d["reasons"][0] and "7.74.0 is not one of them" in d["reasons"][0]
    ev = evidence([cell("rhf", "patch", eco="npm")], [mapped("rhf", "a/rhf", eco="npm", version="7.74.0")], osv=osv(["all"]))
    assert "every published version" in dossier("npm", "rhf", ev, NOW)["reasons"][0]


def test_a_deprecated_package_shows_the_registrys_reason():
    ev = evidence([cell("old", "patch", eco="npm")], [mapped("old", "a/old", eco="npm", deprecated=True,
                                                             deprecated_reason="Use new-pkg instead")])
    d = dossier("npm", "old", ev, NOW)
    assert d["verdict"] == "investigate" and 'deprecated: "Use new-pkg instead"' in d["reasons"][0]


def trend_of(rates, opened=30, decided=25, direction="falling"):
    qs = [{"quarter": q, "outside_opened": opened, "outside_decided": decided, "outside_merge_rate": r, "first_response_hours": 20,
           "merges": 40, "top_merger_share": 0.4} for q, r in zip(["2025Q4", "2026Q1", "2026Q2", "2026Q3"], rates)]
    return {"a/lib": {"stars": 900, "quarters": qs, "direction": {"outside_merge_rate": direction}, "peers": {}}}


def test_a_small_fall_in_merge_rate_is_noise_but_a_big_one_warns_even_on_few_prs():
    # Real data: litesvm "fell" 77% -> 71% (noise); pytest-benchmark fell 100% -> 29% on 7 decided PRs (fair to monitor).
    base = lambda trend: evidence([cell("lib", "minor", eco="npm")], [mapped("lib", "a/lib", eco="npm")], trend,  # noqa: E731
                                  {"npm:lib": {"advisories": 0, "malware": False, "ids": []}})
    assert dossier("npm", "lib", base(trend_of([0.77, 0.75, 0.72, 0.71])), NOW)["verdict"] == "use"
    d = dossier("npm", "lib", base(trend_of([1.0, 0.8, 0.5, 0.29], opened=9, decided=7)), NOW)
    assert d["verdict"] == "monitor" and "(7 decided)" in d["reasons"][0]


def test_still_open_outside_prs_warn_only_past_what_most_repos_see():
    # Real data: across 705 repos, half have 23%+ of last quarter's outside PRs still open and 1 in 10 has 71%+.
    t = trend_of([0.5, 0.5, 0.5, 0.5], opened=86, decided=39, direction="steady")  # mitmproxy: 47 of 86
    ev = evidence([cell("lib", "minor", eco="npm")], [mapped("lib", "a/lib", eco="npm")], t, {"npm:lib": {"advisories": 0, "ids": []}})
    assert "still open" not in texts(dossier("npm", "lib", ev, NOW))


def test_a_burst_of_recent_advisories_means_monitor():
    # Hand-check: adm-zip had 6 advisories in September 2026, all fixed; "use" was too soft.
    osv = {"npm:lib": {"advisories": 9, "last_2y": 8, "last_90d": 6, "unfixed": 0, "latest": "2026-09-29", "severity": {},
                       "malware": False, "ids": []}}
    ev = evidence([cell("lib", "minor", eco="npm")], [mapped("lib", "a/lib", eco="npm")], osv=osv)
    d = dossier("npm", "lib", ev, NOW)
    assert d["verdict"] == "monitor" and "6 advisories in the last 90 days" in d["reasons"][0]


def test_a_deprecation_reason_ending_in_a_full_stop_gets_no_second_one():
    ev = evidence([], [mapped("old", "a/old", eco="npm", deprecated=True, deprecated_reason="Install @docsy/theme instead.")])
    assert 'deprecated: "Install @docsy/theme instead."' in texts(dossier("npm", "old", ev, NOW)) and '.".' not in texts(
        dossier("npm", "old", ev, NOW))


def test_history_with_nothing_good_in_it_gives_no_verdict_rather_than_use_without_reasons():
    # Real data: gradio's only history was 27% of upgrades merged (shown as info), and it got "use" with no reasons.
    ev = evidence([cell("lib", "minor", prs=30, repos=16, merged=8, closed=5, eco="npm")], [mapped("lib", "a/lib", eco="npm")],
                  osv={"npm:lib": {"advisories": 0, "ids": []}})
    d = dossier("npm", "lib", ev, NOW)
    assert d["verdict"] is None and d["reasons"] and "nothing clearly good or bad" in d["reasons"][0]


def test_still_open_needs_20_outside_prs_since_late_quarter_prs_swing_small_counts():
    # Real data: 23 packages of one repo were flagged on "10 of 12 still open"; at 20+ PRs the top 10% still starts at 70%.
    t = trend_of([0.5, 0.5, 0.5, 0.5], opened=12, decided=2, direction="steady")
    ev = evidence([cell("lib", "minor", eco="npm")], [mapped("lib", "a/lib", eco="npm")], t, {"npm:lib": {"advisories": 0, "ids": []}})
    assert "still open" not in texts(dossier("npm", "lib", ev, NOW))


def test_in_a_pr_the_malware_line_judges_the_version_being_installed():
    # Review: the PR pinned the bad version while the line said "the current version 7.74.0 is not one of them".
    osv = {"npm:rhf": {"advisories": 1, "malware": True, "malware_ids": ["MAL-2026-5"], "malware_versions": ["7.73.0"], "ids": []}}
    ev = evidence([cell("rhf", "patch", eco="npm")], [mapped("rhf", "a/rhf", eco="npm", version="7.74.0")], osv=osv)
    d = dossier("npm", "rhf", ev, NOW, versions=["7.73.0"])
    assert "the version installed here (7.73.0) is one of them" in d["reasons"][0]
