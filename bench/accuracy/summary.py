"""One page of every accuracy card's headline numbers, built from the cards' result files so the page can't drift from
them: docs/accuracy.md and the app's About page (web/src/pages/accuracy-data.js; rebuild the app after it changes).

    python bench/accuracy/summary.py          # write both
    python bench/accuracy/summary.py --check  # fail if either is out of date (a flow test runs this)
"""
import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
from fair import by_repo  # noqa: E402
DOC = ROOT / "docs" / "accuracy.md"
APP = ROOT / "web" / "src" / "pages" / "accuracy-data.js"
# How often each CI verdict held, for the pull request comment and the MCP answers (ci/track.py reads it).
TRACK = ROOT / "src" / "stackvitals" / "ci" / "track_record.json"
RULES = ROOT / "docs" / "rules.md"
FILES = {"nulls": "uncertainty/nulls-results.json", "nulls2": "uncertainty/nulls-2week-results.json", "nulls2b": "uncertainty/nulls-2week-before-results.json", "shrink": "uncertainty/shrinkage-results.json",
         "ai": "ai/replicate-results.json", "flaky": "flaky/card.json", "masking": "flaky/masking-results.json",
         "sources": "dora/sources-results.json", "linkage": "dora/linkage-results.json", "spread": "dora/spread-results.json",
         "labels": "community/labels-results.json", "responses": "community/responses-results.json",
         "agents": "agents/results.json", "linkage_more": "dora/linkage-more-results.json", "sens": "label-sensitivity.json", "cross": "adjudicator-crosscheck.json",
         "ag_flaky": "flaky/agreement-gemini-flaky.json", "ag_main": "community/agreement-gemini-main.json",
         "ag_val": "community/agreement-gemini-validation.json", "ag_dora": "dora/agreement-gemini-sources.json", "ag_dora_more": "dora/agreement-gemini-sources-more.json", "dl_cfg": "dora/devlake-configured-results.json", "sources_more": "dora/sources-more-results.json", "middleware": "middleware/results.json",
         "dl_cfg_more": "dora/devlake-configured-more-results.json", "natural": "flaky/natural-results.json",
         "already": "flaky/already-results.json", "maybe": "flaky/maybe-results.json", "outside": "flaky/outside-results.json",
         "triage": "agents/triage-results.json", "heldout": "flaky/heldout-results.json", "registry": "registry.json",
         "safe_rule": "flaky/safe-rule-results.json",
         "agents2": "agents/results2.json", "pr_details": "flaky/pr-details-results.json",
         "ai_detect": "ai/detection-results.json", "ai_adopt": "ai/adoption-results.json",
         "triage_rule": "community/triage-results.json",
         "incidents": "dora/incidents-results.json", "replay": "replay/replay-results.json", "panel": "audit-results.json", "panel6": "panel-results.json"}
REPO = "https://github.com/stackvitals/stackvitals/tree/main/bench/accuracy"
LABELS = "Claude and Gemini 3.5 Flash-Lite, disagreements adjudicated blind by Claude; no person audited"


def joined(parts: list[tuple[int, int]]) -> dict:
    """Several samples' (right, n) as one share with its Wilson range."""
    from stackvitals.core.stats import wilson
    k, n = sum(a for a, _b in parts), sum(b for _a, b in parts)
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "share": k / n, "low": lo, "high": hi}


def ptext(p: float) -> str:
    return "p < 0.001" if p < 0.001 else f"p = {p:.3f}"


def agree(d: dict) -> str:
    return f"{pct(d['agree'])} agree (kappa {d['kappa']:.2f})"


def band(s: dict, key: str, fmt=None) -> str:
    """One headline number on Claude's labels, Gemini's and the adjudicated ones."""
    f = fmt or pct
    return f"Claude's labels {f(s['claude'][key])}, Gemini's {f(s['gemini'][key])}, adjudicated {f(s['adjudicated'][key])}"


def pct(x: float) -> str:
    return f"{x * 100:.1f}%".replace(".0%", "%")


def rng(d: dict) -> str:
    return f"{d['low'] * 100:.0f}-{d['high'] * 100:.0f}%"


def clus(b: dict) -> str:
    # Items cluster by repo: the range with each repo counted once, and the share without the biggest repo.
    w = b["without_biggest"]
    return (f"by repo: {b['repos']} repos, {b['repo_wilson_low'] * 100:.0f}-{b['repo_wilson_high'] * 100:.0f}% counting each "
            f"once; {pct(b['biggest']['share'])} from {b['biggest']['repo']}, without it {w['k']} of {w['n']}")


def pts(x: float) -> str:
    return f"{x * 100:+.1f} points"


def cards(r: dict) -> list[dict]:
    fl, mk, so, lv, rs = r["flaky"], r["masking"], r["sources"], r["labels"]["validation"], r["responses"]
    # Both revert samples together: every link checked against the commit graph.
    li = {k: {w: r["linkage"]["containment"][k][w] + r["linkage_more"]["containment"][k][w] for w in ("right", "wrong")}
          for k in ("fix_chain", "never_shipped", "time_order")}
    # The responder rule as StackVitals runs it since Phase 17: regular responders and people who triage, held out.
    ai, rule = r["ai"]["agent_vs_people"], r["triage_rule"]["validation"]["both"]
    by3 = r["shrink"]["by_sample_size"]["3"]
    ag, pe, a2 = r["agents"]["arms"], r["agents"]["peers"], r["agents2"]["arms"]
    nf, caught = r["nulls"]["null_flag_rate"], r["nulls"]["caught_when_slower_by_rule"]["10x"]
    plain, cost = fl["plain_retry_rule"], mk["harmless_called_safe"]["new_rule"]
    sr = r["safe_rule"]["fresh"]["adjudicated"]
    sens, x = r["sens"], r["cross"]
    paired = r["agents"]["paired_tests"]["agent_vs_stackvitals_alone"]
    nat = r["natural"]
    al, al_same = r["already"]["by_labeller"]["adjudicated"], r["already"]["same_error"]["by_labeller"]["adjudicated"]
    so2 = r["sources_more"]
    mw = r["middleware"]["repos"].values()
    # Middleware's history counts as short when its oldest pull request is 30+ days into the 90-day window.
    short = (datetime.fromisoformat(r["middleware"]["run"]["window_from"]) + timedelta(days=30)).date().isoformat()
    # Both deployment-source samples together (the second was drawn after the rule was fixed).
    src = {k: joined([(round(x["source_right"][k]["share"] * x["repos"]), x["repos"]) for x in (so, so2)])
           for k in ("stackvitals", "devlake", "merges")}
    dlc = joined([(x["devlake_configured"]["right"], x["repos"]) for x in (r["dl_cfg"], r["dl_cfg_more"])])
    flagged_hist = nat["by_sample"]["flagged"]
    decided = flagged_hist.get("not caused", 0) + flagged_hist.get("caused", 0)
    definite = lambda a: a["agree"] / (a["n"] - a["unclear"])  # noqa: E731
    counts = {}
    for v in nat["verdicts"].values():
        counts[v["verdict"]] = counts.get(v["verdict"], 0) + 1
    base = counts.get("not caused", 0) / nat["determined"]
    return [
        {"id": "uncertainty", "title": "Weekly changes and ranges", "folder": "uncertainty", "labeller": "none (replayed history)",
         "claim": "A change is flagged only when it is unlikely to be ordinary week-to-week variation. The digest checks many numbers at "
                  "once, so it uses false-alarm control (Benjamini-Hochberg) rather than one cut-off per number: on this replay the two "
                  "behave alike, but a fixed cut-off flags more often as numbers are added and this doesn't. The 26 repos are the "
                  "independent units; shuffling their weeks tests the no-change case, it doesn't add repos.",
         "rows": [["Shuffled weeks that flag anything (nothing changed)", pct(nf["false_alarm_control"]),
                   f"every difference: {pct(nf['any_difference'])}; each number at p < 0.1: {pct(nf['p_below_0.1'])}; at p < 0.05: {pct(nf['p_below_0.05'])}"],
                  ["10x slowdowns caught in the same scans (first week)", pct(caught["false_alarm_control"]),
                   f"p < 0.1: {pct(caught['p_below_0.1'])}; p < 0.05: {pct(caught['p_below_0.05'])}; detection is the weak side"],
                  ["10x slowdowns lasting two weeks, caught in the second", pct(r["nulls2"]["caught_when_slower_by_rule"]["10x"]["false_alarm_control"]),
                   f"the 14-day checks; {pct(r['nulls2b']['caught_when_slower_by_rule']['10x']['false_alarm_control'])} with weekly checks only"],
                  ["Small repos' first-try share pulled toward peers (3 pushes seen)", f"{pct(by3['squared_error_cut'])} less squared error",
                   f"a 95% range for later pushes held {pct(by3['predictive_coverage_pit'])} of them"]],
         "weak": "A small repo's week can't tell even a large slowdown from noise; the page says so instead of guessing."},
        {"id": "ai", "title": "AI-assisted pull requests, like with like", "folder": "ai",
         "labeller": "crawl markers; the marking itself checked on 400 PRs labelled by Claude and Gemini",
         "claim": "Agents' pull requests are compared with people's from the same repo, month and size.",
         "rows": [["Agents' PRs merged by someone else, against people's: unadjusted", pts(ai["unadjusted_gap_merged_by_someone_else"]), ""],
                  ["The same, same repo, month and size", pts(ai["same_repo_month_size_merged_by_someone_else"]["gap"]),
                   f"{ai['same_repo_month_size_merged_by_someone_else']['low'] * 100:+.1f} to {ai['same_repo_month_size_merged_by_someone_else']['high'] * 100:+.1f}; "
                   "can't be told from no difference"],
                  ["Shuffled AI labels (nothing to find)", pts(r["ai"]["negative_control"]["mean_gap"]),
                   f"{r['ai']['negative_control']['placebos']} shuffles"],
                  ["Marked PRs that state AI involvement (precision)", pct(r["ai_detect"]["rule"]["all"]["precision"]["share"]),
                   f"{rng(r['ai_detect']['rule']['all']['precision'])}, {r['ai_detect']['rule']['all']['precision']['n']} PRs; "
                   f"{clus(r['ai_detect']['rule']['all']['precision']['by_repo'])}"],
                  ["Stated AI involvement that is marked (recall, a floor)", pct(r["ai_detect"]["rule"]["all"]["recall_weighted"]),
                   f"held out {pct(r['ai_detect']['rule']['held_out']['recall_weighted'])}; weighted to the crawl"],
                  ["People's merge rate after a repo adopts agents (pre-registered)",
                   pts(r["ai_adopt"]["outcomes"]["merge_rate"]["overall"]),
                   f"{r['ai_adopt']['outcomes']['merge_rate']['overall_range'][0] * 100:+.1f} to "
                   f"{r['ai_adopt']['outcomes']['merge_rate']['overall_range'][1] * 100:+.1f}; throughput: not credible, adopters were already growing"]],
         "weak": "Markers find about 79% of stated AI involvement (66% held out) and none that goes unsaid, so \"AI-marked\" is a floor; matching can't see what a PR was for."},
        {"id": "flaky", "title": "Flaky CI", "folder": "flaky", "labeller": LABELS,
         "claim": "A job is flaky when the same code failed and passed; no failure is called safe to re-run: a likely flake needs history, a flake's sign in its log and no changed file named, and still waits for a green re-run.",
         "rows": [["Flagged flakes that were real flakes (event precision)", pct(fl["event_precision"]["share"]),
                   f"{rng(fl['event_precision'])}, {fl['event_precision']['n']} events; {band(sens['flaky'], 'event_precision')}; "
                   f"{clus(fl['event_precision']['by_repo'])}"],
                  ["Flagged flakes GitHub's own history confirms weren't the change (no labeller)",
                   f"{flagged_hist.get('not caused', 0)} of {sum(flagged_hist.values())}",
                   "a floor, not a precision: every flagged flake passed on identical code, so history can confirm one but never refute it; "
                   "all 112 flagged jobs, where precision uses the 108 the labels could decide"],
                  ["The plain \"passed on retry\" rule on the same repos", pct(plain["precision"]),
                   f"{rng(plain['precision_range'])}; ours {pts(plain['ours_minus_it']['value'])} "
                   f"({plain['ours_minus_it']['low'] * 100:+.1f} to {plain['ours_minus_it']['high'] * 100:+.1f}, "
                   f"{'significant' if plain['ours_minus_it']['significant'] else 'not significant'}); scored on the retries it can see; "
                   f"the retries only it flags were real {pct(plain['left_out_events_right']['share'])} of the time"],
                  ["\"Known flaky\" failures the change caused, old rule", pct(mk["old_rule"]["share"]),
                   f"{mk['old_rule']['caused_by_change']} of {mk['old_rule']['n']}, {rng(mk['old_rule'])}"],
                  ["The same, 2026-10-22 rule (3+ flakes, one in the failing step), held out",
                   f"{r['heldout']['adjudicated']['masking']['caused']} of "
                   f"{r['heldout']['adjudicated']['masking']['caused'] + r['heldout']['adjudicated']['masking']['not_caused']}",
                   f"{r['heldout']['adjudicated']['masking']['caused_low'] * 100:.0f}-"
                   f"{r['heldout']['adjudicated']['masking']['caused_high'] * 100:.0f}%, "
                   f"{r['heldout']['adjudicated']['masking']['jobs']} jobs in {r['heldout']['adjudicated']['masking']['repos']} repos; "
                   f"{clus(r['heldout']['adjudicated']['by_repo']['masking'])}; "
                   f"the 5% bar failed, so the rule was tightened (next row) "
                   f"(on the tuning sample: {mk['new_rule']['caused_by_change']} of {mk['new_rule']['n']}, all one job)"],
                  ["Stricter rule (history, a flake's sign in the log, no changed file named), pre-registered, fresh held out",
                   f"{sr['kept']['caused']} of {sr['kept']['caused'] + sr['kept']['not_caused']}",
                   f"{sr['kept']['caused_low'] * 100:.0f}-{sr['kept']['caused_high'] * 100:.0f}%, {sr['kept']['jobs']} jobs in "
                   f"{sr['kept']['repos']} repos; it kept {sr['kept']['n']} of {sr['calls_by_history']} calls history made "
                   f"({pct(sr['kept']['coverage'])}); the 5% bar is unproven, so it reads \"likely flaky\", never safe; "
                   f"\"maybe yours\" (a changed file named): {sr['maybe_yours']['caused']} of "
                   f"{sr['maybe_yours']['caused'] + sr['maybe_yours']['not_caused']} the change's"],
                  ["End-to-end replay: \"known flaky\" calls a re-run turned green that the change had caused",
                   f"{r['replay']['known_flaky_green_but_caused']['adjudicated_by_claude']['k']} of "
                   f"{r['replay']['known_flaky_green_but_caused']['adjudicated_by_claude']['n']} to "
                   f"{r['replay']['known_flaky_green_but_caused']['adjudicated_by_gemini']['k']} of "
                   f"{r['replay']['known_flaky_green_but_caused']['adjudicated_by_gemini']['n']}",
                   f"the labellers disagree: {rng(r['replay']['known_flaky_green_but_caused']['adjudicated_by_claude'])} adjudicated by "
                   f"Claude (its 3 are a pull-request label check), {rng(r['replay']['known_flaky_green_but_caused']['adjudicated_by_gemini'])} "
                   f"by Gemini; Claude's labels alone {r['replay']['known_flaky_green_but_caused']['first_claude']['k']} of "
                   f"{r['replay']['known_flaky_green_but_caused']['first_claude']['n']}, Gemini's "
                   f"{r['replay']['known_flaky_green_but_caused']['second_gemini']['k']} of {r['replay']['known_flaky_green_but_caused']['second_gemini']['n']}; "
                   f"people's labels pending. {r['replay']['failed_jobs']:,} failed pull-request jobs replayed as of each attempt in "
                   f"{r['replay']['repos']} repos; known flakes are re-run, never passed"],
                  ["Calls that blamed the change but went green on a re-run (random draw, 3 per run at most)",
                   f"{r['replay']['blamed_green_caused']['adjudicated_by_claude']['k']} of "
                   f"{r['replay']['blamed_green_caused']['adjudicated_by_claude']['n']} to "
                   f"{r['replay']['blamed_green_caused']['adjudicated_by_gemini']['k']} of "
                   f"{r['replay']['blamed_green_caused']['adjudicated_by_gemini']['n']} were the change",
                   f"{rng(r['replay']['blamed_green_caused']['adjudicated_by_claude'])} to "
                   f"{rng(r['replay']['blamed_green_caused']['adjudicated_by_gemini'])}: a green re-run doesn't prove the change clean "
                   f"either way, so the verdict check, by design, never passes red CI"],
                  ["Harmless failures the 2026-10-22 rule called known flaky (on its tuning sample)", f"{cost['called_safe']} of {cost['n']}",
                   f"{pct(cost['share'])}, {rng(cost)}; the rest cost a look"],
                  ["\"Already failing on main\" (same step, same error) failures the change caused",
                   f"{al_same['caused']} of {al_same['caused'] + al_same['not_caused']}",
                   f"0-{al_same['caused_high'] * 100:.0f}%, {r['already']['same_error']['repos']} repos; the step alone: "
                   f"{al['caused']} of {al['caused'] + al['not_caused']}, so the error must match; the verdict check still blocks"],
                  ["\"Maybe flaky\" first failures (they look like flakes) the change caused",
                   f"{r['maybe']['never_flaked']['matched']['caused']} of {r['maybe']['never_flaked']['matched']['caused'] + r['maybe']['never_flaked']['matched']['not_caused']}",
                   f"0-{r['maybe']['never_flaked']['matched']['caused_high'] * 100:.0f}%; never-flaked failures overall: "
                   f"{r['maybe']['never_flaked']['all']['caused']} of {r['maybe']['never_flaked']['all']['caused'] + r['maybe']['never_flaked']['all']['not_caused']}; "
                   "signs written on these logs; asks for one re-run, still blocks"],
                  ["\"PR details\" failures (a check on the PR's title, description or labels) that were the change's code",
                   f"{r['pr_details']['caused_by_change']} of {r['pr_details']['fired']}",
                   f"{r['pr_details']['caused_low'] * 100:.0f}-{r['pr_details']['caused_high'] * 100:.0f}%, "
                   f"{r['pr_details']['fired_repos']} repos; {r['pr_details']['verdict_before'].get('known flaky', 0)} "
                   f"had been called known flaky, so a re-run that fails again was advised; still blocks; "
                   f"{clus(r['pr_details']['by_repo'])}: preliminary"],
                  ["Never-flaked failures that were intermittent (misses)", pct(fl["miss_rate"]["share"]),
                   f"{rng(fl['miss_rate'])}; {band(sens['flaky'], 'miss_rate')}"],
                  ["Labellers on \"caused by the change\"", agree(r["ag_flaky"]["fields"]["caused_by_change"]),
                   f"cause: {agree(r['ag_flaky']['fields']['cause'])}"],
                  ["Labellers against GitHub's history, where it decides", f"Claude {pct(definite(nat['labellers_against_model_free']['claude']))}",
                   f"Gemini {pct(definite(nat['labellers_against_model_free']['gemini']))} of their definite answers on {nat['determined']} failures; "
                   f"always answering \"not caused\" would score {pct(base)}"]],
         "weak": "14-day reads miss rare flakes; status precision (re-running pinned commits) isn't measured yet; Rust jobs "
                 f"were real flakes {pct(fl['by_language']['rust']['event_precision']['share'])} of the time."},
        {"id": "dora", "title": "Deployments and failures", "folder": "dora", "labeller": LABELS,
         "claim": "Deployments come from the source that matches how a repo ships; a revert blames the deployment that shipped what it undid.",
         "rows": [["Repos whose deployment source is right: StackVitals", f"{src['stackvitals']['k']} of {src['stackvitals']['n']}",
                   f"{rng(src['stackvitals'])}; the first 25 led to one fix of the rule, the later 35 are held out: "
                   f"{pct(so2['source_right']['stackvitals']['share'])}; {band(sens['dora'], 'stackvitals')} on the first"],
                  ["The same with no setup: DevLake's default pattern / every merge", f"{pct(src['devlake']['share'])} / {pct(src['merges']['share'])}",
                   f"paired on the same repos: {so['source_right_tests']['devlake']['only_a'] + so2['source_right_tests']['devlake']['only_a']} to "
                   f"{so['source_right_tests']['devlake']['only_b'] + so2['source_right_tests']['devlake']['only_b']} against DevLake's default"],
                  ["DevLake with a pattern a user would write (deploy, release, publish or push-image)", pct(dlc["share"]),
                   f"{rng(dlc)}; paired: {r['dl_cfg']['against_stackvitals']['only_a'] + r['dl_cfg_more']['against_stackvitals']['only_a']} to "
                   f"{r['dl_cfg']['against_stackvitals']['only_b'] + r['dl_cfg_more']['against_stackvitals']['only_b']}; it also counts docs-site builds"],
                  ["Lead time per pull request, on the same pull requests as Middleware", f"{sum(x['prs']['within_10pct'] for x in mw)} of {sum(x['prs']['both'] for x in mw)} within 10%",
                   f"{len(mw)} repos, 90 days, no labeller; the rest were rebased long after they were written (Middleware starts at the rebase); "
                   f"Middleware returned about a month where 90 days were asked on {sum(x['middleware_oldest_pr_created'] > short for x in mw)} of {len(mw)} repos"],
                  ["Reverts where time order blamed a release lacking the change", f"{li['time_order']['wrong']} of {li['time_order']['wrong'] + li['time_order']['right']}",
                   f"fix chain right on {li['fix_chain']['right'] + li['never_shipped']['right']} of "
                   f"{li['fix_chain']['right'] + li['fix_chain']['wrong'] + li['never_shipped']['right'] + li['never_shipped']['wrong']}; "
                   f"{r['linkage']['reverts'] + r['linkage_more']['reverts']} reverts in {r['linkage']['repos_with_reverts'] + r['linkage_more']['repos_with_reverts']} repos, checked with the commit graph (no labeller); "
                   f"time order wrong {clus(by_repo([(x['repo'], x['time_order_check'] == 'wrong') for x in r['linkage']['links'] + r['linkage_more']['links'] if x.get('time_order_check') in ('right', 'wrong')]))}"],
                  ["Regression reports naming the release that broke: the last release before the report was it",
                   f"{r['incidents']['all']['last_before']['right']} of {r['incidents']['all']['n']}",
                   f"{rng(r['incidents']['all']['last_before'])}; the version the report names: "
                   f"{r['incidents']['all']['named']['right']} of {r['incidents']['all']['n']} (not significant, so DORA's rule stays); "
                   f"{r['incidents']['decided'] - r['incidents']['none']} of {r['incidents']['labelled']} reports said which release"],
                  ["Repos whose deployment tier changes with the definition", pct(r["spread"]["tier_changes_share"]), f"{r['spread']['repos']:,} crawled repos"],
                  ["Labellers on whether a workflow ships", agree(r["ag_dora"]["fields"]["ships"]),
                   f"on each repo's full set of sources: {agree(r['ag_dora']['fields']['sources'])}; held-out repos: "
                   f"{agree(r['ag_dora_more']['fields']['ships'])} and {agree(r['ag_dora_more']['fields']['sources'])}"]],
         "weak": "Shipping workflows with plain names (docker, pypi, CD) are missed: workflow recall 60% on the held-out repos; releases from maintenance branches with backports defeat both linkage rules."},
        {"id": "community", "title": "First responses", "folder": "community", "labeller": LABELS,
         "claim": "A first response is the project's (a maintainer, a regular responder or someone who triages), and issues still waiting stay in the median.",
         "rows": [["Non-maintainer first comments that are drive-bys (issue-metrics counts them)", pct(lv["drive_by_counted_by_issue_metrics"]["share"]),
                   f"{rng(lv['drive_by_counted_by_issue_metrics'])}, held-out repos"],
                  ["Project answers the roles-only rule missed / regular responders and triagers catch", f"{pct(lv['project_answers_missed_by_roles_only']['share'])} / {pct(rule['project_answers_caught']['share'])}",
                   f"drive-bys among what they add: {pct(rule['drive_by_among_counted']['share'])}; "
                   f"regular responders alone, by labeller: {band(sens['community'], 'drive_bys_among_what_they_add')}"],
                  ["Repos where an answered-only median hides that most issues wait", pct(rs["most_waiting_but_answered_median_shown"] / rs["repos"]),
                   f"{rs['repos']:,} crawled repos"],
                  ["Labellers on the kind of comment (held-out set)", agree(r["ag_val"]["fields"]["kind"]),
                   f"first set: {agree(r['ag_main']['fields']['kind'])}; drive-bys counted by issue-metrics: "
                   f"{band(sens['community'], 'drive_bys_counted_by_issue_metrics')}"]],
         "weak": "About 43% of occasional contributors' project answers still go uncounted; the rule errs toward \"waiting\"."},
        {"id": "agents", "title": "Against a general AI agent", "folder": "agents", "labeller": "Claude (the flaky card's first labels)",
         "claim": "The same questions, answered by an agent with live GitHub access, with and without StackVitals. On single failures "
                  "the agent is as accurate either way; what StackVitals adds is answers with nobody asking (the PR comment and "
                  "verdict) and comparisons with similar repos without GitHub calls.",
         "rows": [["Failure questions right: agent / agent with StackVitals / StackVitals alone",
                   f"{ag['a']['items_right']} / {ag['b']['items_right']} / {r['agents']['stackvitals_alone']['items_right']} of {ag['a']['items']}",
                   f"a live agent reading the log needs nothing from StackVitals here; agent against StackVitals alone: "
                   f"{paired['only_a']} to {paired['only_b']} (McNemar {ptext(paired['p'])})"],
                  ["Labelled flaky jobs found (both agents)", f"{ag['a']['flaky_jobs_found']} of {ag['a']['flaky_jobs_labelled']}",
                   f"GitHub calls: {ag['a']['github_calls']} without, {ag['b']['github_calls']} with StackVitals"],
                  ["Comparing with similar public repos: repos it rests on", f"{min(pe['a']['peer_repos_checked'])}-{max(pe['a']['peer_repos_checked'])} vs "
                   f"{min(pe['b']['peer_repos_checked'])}-{max(pe['b']['peer_repos_checked'])}",
                   f"{pe['a']['github_calls']} calls for the live agent, {pe['b']['github_calls']} with StackVitals"],
                  *[[f"{r['agents2']['items']} more failures in {r['agents2']['repos']} repos, {name}: agent / with StackVitals",
                     f"{a2[f'a-{m}']['without_pr_details']['right']} / {a2[f'b-{m}']['without_pr_details']['right']} of "
                     f"{a2[f'a-{m}']['without_pr_details']['items']}",
                     f"McNemar {ptext(r['agents2']['paired'][f'a-{m}_vs_b-{m}']['p'])}; GitHub calls per failure "
                     f"{a2[f'a-{m}']['calls_per_item']} without, {a2[f'b-{m}']['calls_per_item']} with; "
                     f"{a2[f'a-{m}']['pr_details_items']['items']} checks on the PR itself scored apart"]
                    for m, name in (("sonnet", "Sonnet"), ("haiku", "Haiku (half of them)"))],
                  ["Same failures, no agent: StackVitals alone / with opt-in model triage",
                   f"{r['agents2']['stackvitals_alone_without_pr_details']['right']} / "
                   f"{r['agents2']['stackvitals_with_triage_without_pr_details']['right']} of "
                   f"{r['agents2']['stackvitals_alone_without_pr_details']['items']}",
                   "what the PR comment and verdict check say with nobody asking; an agent reading the log does better"]],
         "weak": "Questions beyond GitHub's 90-day log retention, where kept history matters most, are not asked yet."}]


def _doc(cs: list[dict], r: dict) -> str:
    # "k of n it decided (m asked)": items with no majority are disagreement too, so the asked count is shown.
    panel = lambda kind: (f"{r['panel6']['kinds'][kind]['all_six_majority']['k']} of the "  # noqa: E731
                          f"{r['panel6']['kinds'][kind]['all_six_majority']['n']} it decided "
                          f"({r['panel6']['kinds'][kind]['items']} asked)")
    out = ["# How accurate StackVitals is", "",
           "The rules behind StackVitals' verdicts and headline numbers were each checked against public data and, where a",
           "judgement was needed, against labelled examples. Each card in `bench/accuracy/` holds the method, the",
           "sample, the labels (links only), the competing rules scored beside ours, and what the check can't show. This",
           "page is built from those cards' result files by `bench/accuracy/summary.py`; the exact statistical settings are in",
           "[methods.md](methods.md).", "",
           "**How the labels were made.**",
           "- Two model families labelled each sample blind, from the same codebook and evidence: Claude, then Gemini 3.5",
           "  Flash-Lite.",
           "- Each disagreement was settled by a third reading that saw the two labels without knowing whose they were.",
           "- That third reading was Claude's. Gemini, adjudicating a sample of the same disputes, agreed with it on "
           f"{r['cross']['same_ruling']} of {r['cross']['packets']}.",
           f"- Each adjudicator mostly sided with its own family: Claude's {r['cross']['claude_adjudicator_sided_with_claude']} times, "
           f"Gemini's {r['cross']['gemini_adjudicator_sided_with_gemini']} times.",
           "- So each card shows its headline on each labeller's labels as well as the adjudicated ones.",
           "- A second check: six models from three families (OpenAI gpt-5.4-mini and gpt-5-mini, Google gemini-3.8-flash and "
           "gemini-3.5-flash, Anthropic Claude Sonnet and Haiku) each answered the same plain-language questions alone, on "
           f"{r['panel6']['items']} labelled items (the CI and reply items drawn first from those the first two labellers "
           "disagreed on). Where a majority formed, it matched the labels on CI causes "
           f"{panel('ci')}, the release behind a bug {panel('incident')}, how releases reach users {panel('deploy')}, "
           f"but issue replies only {panel('comment')}: "
           "it called most replies the labels call drive-bys or project answers helpful answers from other users, so the "
           "Community card's reply labels are the least settled. On the replay's disputed items it reached no majority "
           f"on {r['panel6']['kinds']['replay']['six_model_majority_sides_with'].get('no majority', 0)} of "
           f"{r['panel6']['kinds']['replay']['items']}.",
           "- No person has audited the labels yet.", "",
           "**How sure.** A rule is an *early observation* when its check rests on few cases; its numbers are a direction,",
           "not a settled rate: " + "; ".join(f"`{x['id']}` ({x['strength_why']})" for x in r["registry"]["rules"]
                                            if x.get("strength") == "early observation") + ". A rule's *bar* is the accuracy it had to reach before it shipped; for the flaky-test rules it is that at most 5% "
           "of the failures it calls flaky were really caused by the change (*masking*: a real failure hidden as a flake). "
           "A rule whose bar *failed* is kept "
           "only where failing costs nothing it promised: " + "; ".join(f"`{x['id']}` ({x['strength_why']})" for x in r["registry"]["rules"]
                                                           if x.get("strength") == "bar failed") + ". The rest are validated: checked against their bar, on held-out data where the rule has one ([rules.md](rules.md) "
           "says which).", "",
           "**Reproduce a number.** `python bench/accuracy/reproduce.py list` names the command behind every result file;",
           "`reproduce.py check <card>` re-scores it and says whether the numbers match. Scoring reads the evidence each",
           "card was labelled from (the `.work` folders: CI histories, crawl records, logs), which is too large and holds",
           "too much third-party text for the repo; `reproduce.py pack` builds it into one archive (about 600 MB before",
           "compression), shared on request. The final labels are committed beside each card, with links to the public items.", ""]
    for c in cs:
        out += [f"## {c['title']}", "", c["claim"], "", "| | Result | |", "|---|---|---|"]
        out += [f"| {a} | **{b}** | {n} |" for a, b, n in c["rows"]]
        out += ["", f"Weak spot: {c['weak']} Labels: {c['labeller']}. Card: [bench/accuracy/{c['folder']}]"
                f"(../bench/accuracy/{c['folder']}/README.md).", ""]
    out += ["## Rule changes", "", "Every rule a number rests on, with each revision and why, is in "
            "[registry.json](../bench/accuracy/registry.json).", ""]
    for rule in r["registry"]["rules"]:
        for v in rule.get("revisions") or []:
            out.append(f"- {v['date']}, `{rule['id']}`: before, {v['from']}; {v['why']}; after, {v['effect']}.")
    return "\n".join(out) + "\n"


def _app(cs: list[dict]) -> str:
    data = [{k: c[k] for k in ("id", "title", "claim", "rows", "weak", "labeller")} | {"link": f"{REPO}/{c['folder']}"} for c in cs]
    return ("// Built by bench/accuracy/summary.py from the accuracy cards' results; don't edit by hand.\n"
            f"export const CARDS = {json.dumps(data, indent=1, ensure_ascii=False)};\n")


def track_record(r: dict) -> dict:
    """One line per verdict: how often it held on the labelled public CI failures."""
    mk, out, maybe = r["masking"], r["outside"]["not_caused_by_change"], r["maybe"]
    same = r["already"]["same_error"]["by_labeller"]["adjudicated"]
    never, tr = maybe["never_flaked"]["all"], r["triage"]
    h = r["heldout"]["adjudicated"]
    held, hb = h["masking"], h["by_repo"]["masking"]
    clear = lambda x: (x["caused"], x["caused"] + x["not_caused"])  # noqa: E731
    sr, tune = r["safe_rule"]["fresh"]["adjudicated"], r["safe_rule"]["tuning"]
    mys = [sr["maybe_yours"], tune["heldout_read"]["maybe_yours"], tune["masking_check"]["any_earlier_flake"]["maybe_yours"]]
    my_k, my_n = sum(m["caused"] for m in mys), sum(m["caused"] + m["not_caused"] for m in mys)
    out_k = out["n"] - round(out["n"] * (1 - out["share"]))
    same_k, same_n = same["caused"] + h["already_failing"]["same_error"]["caused"], \
        same["caused"] + same["not_caused"] + clear(h["already_failing"]["same_error"])[1]
    maybe_k, maybe_n = maybe["never_flaked"]["matched"]["caused"] + h["maybe_flaky"]["caused"], \
        maybe["never_flaked"]["matched"]["caused"] + maybe["never_flaked"]["matched"]["not_caused"] + clear(h["maybe_flaky"])[1]
    # Each line adds the held-out read (heldout.py) to the sample the rule was tuned on.
    return {
        # The stricter rule (pre-registered 2026-10-28) on its fresh read; history alone on the first held-out read.
        "known flaky": f"fresh held-out read: {sr['kept']['caused']} of {sr['kept']['caused'] + sr['kept']['not_caused']} "
                       f"calls the change's own ({sr['kept']['caused_low'] * 100:.0f}-{sr['kept']['caused_high'] * 100:.0f}%), too few "
                       f"to show it is safe (history alone: {held['caused']} of {held['caused'] + held['not_caused']}), so check the "
                       "error, then re-run it",
        "maybe yours": f"the error named a file the pull request changed: the change's own {my_k - sr['maybe_yours']['caused']} of "
                       f"{my_n - sr['maybe_yours']['caused'] - sr['maybe_yours']['not_caused']} clear times on the data the rule was "
                       f"written from, {sr['maybe_yours']['caused']} of {sr['maybe_yours']['caused'] + sr['maybe_yours']['not_caused']} fresh",
        "outside failure": f"{out_k + h['outside']['not_caused']} of {out['n'] + clear(h['outside'])[1]} labelled matches in "
                           f"{r['outside']['by_repo']['repos'] + h['by_repo']['outside']['repos']} repo samples were not the change",
        "already failing": f"same step and same error: {same_k} of {same_n} labelled were the change",
        "maybe flaky": f"{maybe_k} of {maybe_n} labelled matches were the change; still re-run once to tell",
        "PR details": f"{r['pr_details']['caused_by_change']} of {r['pr_details']['fired']} labelled matches (in "
                      f"{r['pr_details']['fired_repos']} repos) were the change's code",
        "flaked before": f"jobs that had flaked before, but too rarely: the change caused {mk['old_rule']['caused_by_change']} of "
                         f"{mk['old_rule']['n']} under the old rule",
        "new": f"never-flaked failures: the change caused {never['caused']} of {never['caused'] + never['not_caused']} labelled ones",
        "model": f"asked about {tr.get('model:right', 0) + tr.get('model:wrong', 0)} undecided failures, right on "
                 f"{tr.get('model:right', 0)}; advice only",
    }


def _rules(registry: dict) -> str:
    """docs/rules.md: every rule a verdict or number rests on, from the registry: what it is, what it was tuned and
    checked on, its bar, its result and every change to it."""
    lines = ["# Rule reference", "",
             "Every rule a StackVitals verdict or number rests on, from `bench/accuracy/registry.json`: what it does, the data "
             "it was tuned on and checked on, the bar it had to meet (set before the check where a date says so), its result "
             "and each change since. The card linked under each rule has the method and the labels. Generated; a test keeps "
             "it in step.", ""]
    for rule in registry["rules"]:
        lines += [f"## `{rule['id']}` (version {rule['version']})", "", rule["rule"], "",
                  f"- **Card:** [bench/accuracy/{rule['card']}](../bench/accuracy/{rule['card']}/README.md)",
                  f"- **Tuned on:** {rule['tuned_on']}", f"- **Checked on:** {rule['held_out']}",
                  f"- **Bar:** {rule['pass_bar']}" + (f" (set {rule['bar_set']})" if rule.get("bar_set") else ""),
                  f"- **Result:** {rule['result']}",
                  f"- **How sure:** {rule.get('strength', 'validated')}"
                  + (f" ({rule['strength_why']})" if rule.get("strength_why") else "")]
        for v in rule.get("revisions") or []:
            lines.append(f"- **Changed {v['date']}:** was {v['from']}; why: {v['why']}; effect: {v['effect']}")
        for d in rule.get("dropped") or []:
            if isinstance(d, str):
                lines.append(f"- **Tried and dropped:** {d}")
            else:
                why = f"; why: {d['why']}" if d.get("why") else ""
                lines.append(f"- **Tried and dropped:** {d.get('rule') or d.get('what')}{why}")
        lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    r = {k: json.loads((HERE / v).read_text(encoding="utf-8")) for k, v in FILES.items()}
    cs = cards(r)
    want = {DOC: _doc(cs, r), APP: _app(cs), TRACK: json.dumps(track_record(r), indent=1, sort_keys=True) + "\n",
            RULES: _rules(r["registry"])}
    if args.check:
        stale = [str(p.relative_to(ROOT)) for p, text in want.items() if not p.exists() or p.read_text(encoding="utf-8") != text]
        if stale:
            print(f"out of date: {', '.join(stale)}; run python bench/accuracy/summary.py", file=sys.stderr)
            return 1
        return 0
    for p, text in want.items():
        p.write_text(text, encoding="utf-8")
    print("\n".join(str(p.relative_to(ROOT)) for p in want))
    return 0


if __name__ == "__main__":
    sys.exit(main())
