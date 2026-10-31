# Release checklist

Run this before tagging a release. Three kinds of defect block a release. Anything else goes in the changelog and
ships.

## 1. Security defects

**What counts:** a token or key reaching a host it shouldn't; private data reaching a public data branch or page; an
injection into a comment, issue, chat message or AI prompt (a ping, a link, markup or instructions from untrusted text).

**How it is checked:**
- `tests/test_flow_connectors.py`: `test_the_jira_key_can_only_go_to_an_atlassian_site_even_through_an_app_request`,
  `test_the_copilot_key_never_reaches_the_report_file_host`, `test_a_public_repo_never_keeps_tracker_titles_links_or_sprint_names`,
  `test_a_flaky_test_name_never_becomes_a_chat_link_or_ping`.
- `tests/test_flow_core.py`: `test_the_privacy_page_names_every_outside_host_the_code_can_reach`.
- `tests/test_flow_portal.py`: `test_private_repos_never_reach_a_public_page_and_forks_are_not_judged`.
- `tests/test_flow_ci.py`: `test_dashboard_and_summary_escape_job_names_from_untrusted_workflows`,
  `test_real_logs_keep_to_the_failing_step_and_comments_cannot_ping_or_link`,
  `test_the_ai_prompt_fences_ci_text_so_an_agent_never_obeys_it`.
- `tests/test_flow_deps.py`: `test_the_pr_check_cannot_be_fooled_or_broken_by_the_prs_own_files`.
- `tests/test_flow_decisions.py`: `test_a_request_changes_settings_only_for_someone_with_write_access`.
- The sandbox try run: the job summary, comments and data branch hold no secret.

**If one is found:** stop the release. Rotate any key or token that may have leaked. Remove leaked data from the data
branch and its history. Write a failing flow test first, then fix.

## 2. Data loss or broken recovery

**What counts:** history on the `stackvitals-data` branch lost or corrupted; a run that can't resume after running out
of budget, dying mid-run or racing another run.

**How it is checked:**
- `tests/test_flow_core.py`: `test_overlapping_runs_converge_without_losing_either_side`,
  `test_a_run_that_dies_before_its_commit_leaves_nothing_and_the_next_run_catches_up`,
  `test_a_failing_step_does_not_lose_the_other_steps_work_and_is_reported`,
  `test_the_job_keeps_house_retention_cap_counter_and_an_opt_in_squash`,
  `test_the_same_event_processed_twice_changes_nothing`.
- `tests/test_flow_ci.py`: `test_running_out_of_budget_keeps_what_was_collected_and_resumes`,
  `test_a_push_race_is_retried_on_top_of_the_other_run`.
- `tests/test_flow_connectors.py`: `test_a_capped_pull_carries_on_and_an_unexpected_answer_never_stops_the_job`.
- `tests/test_flow_crawl.py`: `test_kill_before_flush_loses_nothing_and_rerun_has_no_duplicates`.
- The sandbox try run: the data branch gains the new days and keeps every older one.

**If one is found:** stop the release. Reproduce it in a flow test, fix it, and check that the next run resumes where
the last one stopped.

## 3. Misleading high-impact advice

**What counts:** a verdict or advice that is wrong in a way that costs people, such as calling a real failure a flake
or letting it pass the verdict check; a claim on a page, in the README or in an MCP answer that its accuracy card
doesn't support.

**How it is checked:**
- `tests/test_flow_ci.py`: `test_a_job_is_known_flaky_only_with_three_flakes_in_the_failing_step_and_never_passes_the_check_by_itself`,
  `test_the_verdict_check_passes_only_once_ci_is_green`,
  `test_a_step_already_failing_on_the_default_branch_excuses_only_the_same_error`,
  `test_a_first_failure_that_fails_the_way_flaky_checks_do_asks_for_one_rerun_and_still_blocks`.
- `tests/test_flow_accuracy.py`: `test_the_accuracy_page_and_the_apps_table_match_the_cards`,
  `test_the_frozen_masking_labels_give_the_card_under_todays_safe_to_rerun_rule`,
  `test_the_registry_names_every_rule_a_card_rests_on`.
- `tests/test_flow_deps.py`: `test_dossier_verdicts_follow_hard_signals_and_say_when_evidence_is_thin`.
- `tests/test_flow_surfaces.py`: `test_the_action_the_cli_mcp_and_the_page_agree`.
- By hand: every number in the README and on the pages matches a card's result file.

**If one is found:** stop the release. Make the advice more cautious (block, or ask for a look) until the rule is fixed
and re-scored. Add the revision to `bench/accuracy/registry.json` and publish the loss on the card.

## Before tagging

- [ ] `pytest` passes (every test, `tests/local/` included).
- [ ] `pytest tests --ignore=tests/local` passes (what a fresh clone runs).
- [ ] A sandbox try run with the built-in `GITHUB_TOKEN`: point the `sandbox-try` branch at the commit to tag, run the
      sandbox's "StackVitals try" workflow with every module, and check every run it caused, the sandbox's own CI
      included.
- [ ] Docs regenerated, with no diff left:
  - `python bench/accuracy/summary.py` (docs/accuracy.md and the app's table);
  - `python -c "from stackvitals.core import schema; open('docs/settings.md', 'w', encoding='utf-8', newline='\n').write(schema.markdown())"`;
  - `python -c "from stackvitals.core import dataflow; open('docs/privacy.md', 'w', encoding='utf-8', newline='\n').write(dataflow.markdown())"`.
- [ ] Each rule changed since the last release has its card re-scored (the card's Reproduce steps) and a revision in
      `bench/accuracy/registry.json`.
- [ ] `CHANGELOG.md` has an entry for this version.

## Publishing

Pushing a version tag (`git tag v0.1.0 && git push origin v0.1.0`) runs `.github/workflows/release.yml`:

1. **build** makes the wheel and sdist with read-only rights and a pinned build backend.
2. **publish** (in the `release` environment) writes the SBOM, signs every file with Sigstore, adds a build
   provenance attestation and creates the GitHub release with all of them.
3. **pypi** (same environment, after `publish`) uploads the wheel and sdist from step 1 to PyPI by
   [trusted publishing](https://docs.pypi.org/trusted-publishers/): PyPI trusts this repo, `release.yml` and the
   `release` environment, so no PyPI token is stored. It runs only in the project's own repo, and only when the tag
   matches the package version.

Moving the floating `v0` tag afterwards (`git tag -f v0 v0.1.0 && git push -f origin v0`) doesn't start a release.

Then list the MCP server in the [MCP registry](https://github.com/modelcontextprotocol/registry) by hand, once the
package is on PyPI (the registry reads the `mcp-name` line in the README that PyPI shows):

```sh
mcp-publisher login github     # a browser sign-in as a member of the owner named in server.json
mcp-publisher publish          # from the repo root; reads server.json
```

Bump `version` in `server.json` (both places) with the package version before each listing.

