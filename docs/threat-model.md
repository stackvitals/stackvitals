# Threat model

StackVitals runs inside your own GitHub Actions with your repo's tokens, reads text that strangers write (pull request
titles, test names, logs, issues, comments) and writes back to GitHub (comments, labels, issues, the data branch). This
page lists what could go wrong, what stops it, and the committed test that fails if the protection breaks
(`tests/test_flow_*.py`; a test below that no longer exists fails `test_the_threat_model_names_only_tests_that_exist`).
What leaves the repo is listed separately in [privacy.md](privacy.md); how to report a problem is in
[SECURITY.md](../SECURITY.md).

## Untrusted input

| Threat | What stops it | Test |
|---|---|---|
| A fork PR's test or job name pings people or plants a link in a comment, issue or chat message | Names are code-formatted, `@` and links are neutralised, chat payloads are escaped | `test_real_logs_keep_to_the_failing_step_and_comments_cannot_ping_or_link`, `test_a_flaky_test_name_never_becomes_a_chat_link_or_ping`, `test_preflight_note_cannot_ping_people_or_make_links` |
| A job or PR name injects markup into the pages | Every page escapes repo text | `test_dashboard_and_summary_escape_job_names_from_untrusted_workflows`, `test_pr_titles_from_strangers_are_escaped` |
| A test report is a zip or XML bomb | Size limits, in-memory reads, defusedxml | `test_hostile_xml_is_refused_without_crashing`, `test_oversized_artifacts_are_skipped_not_downloaded`, `test_every_report_format_reads_into_one_shape_and_hostile_xml_is_refused` |
| A failing log tells a model (triage, or an agent using the MCP server) what to do | CI text is fenced and labelled as data | `test_the_ai_prompt_fences_ci_text_so_an_agent_never_obeys_it` |
| A fork PR's test report claims a real test passed on retry, so it gets called known flaky, re-run or quarantined | Fork runs' flaky and coverage claims are dropped; their failures still show on their own PR | `test_a_fork_report_cannot_mark_a_test_flaky_or_set_coverage` |
| A pull request's own lockfile or manifest misleads or breaks the dependency check | The PR's code is never run, files are parsed with limits, the check never fails the PR | `test_the_pr_check_cannot_be_fooled_or_broken_by_the_prs_own_files` |

## Fork pull requests and `workflow_run`

| Threat | What stops it | Test |
|---|---|---|
| A fork PR's workflow runs with write tokens | StackVitals starts from `workflow_run` after CI, in the base repo's context, and reads the fork's results as data: it never checks out or runs the PR's code | `test_fork_runs_join_the_pr_that_was_open_on_that_branch_at_the_time`, `test_a_fork_pr_is_found_and_the_comment_is_edited_not_reposted` |
| A fork PR gets a deps comment or a write | The lockfile check comments only on same-repo PRs | `test_the_pr_check_reads_lockfile_changes_and_never_comments_on_forks` |

**Triggers.** The workflow `stackvitals ci init` writes starts on `workflow_run` (after your CI finishes), a schedule,
`workflow_dispatch`, a push that changes its settings or workflow file, `issues` and `issue_comment` (commands and app
requests, checked against the sender's permission), and `pull_request` only when a lockfile changes. It never uses
`pull_request_target`. On a fork's pull request GitHub gives that `pull_request` run a read-only token and no secrets,
and StackVitals reads the lockfiles through the API without checking out or running the PR's code. The Portal's
workflow starts on a schedule, `workflow_dispatch`, `issues` and `issue_comment` (only `/stackvitals approve` from
owners, members and collaborators starts a runner; the job checks both people's write access, refuses self-approval,
and runs only the request text the approval's code names).

| Threat | What stops it | Test |
|---|---|---|
| A workflow runs the base repo's token and secrets on a fork's code (`pull_request_target`) | No workflow StackVitals writes or ships uses that trigger | `test_no_workflow_uses_pull_request_target` |

## Who can change things

| Threat | What stops it | Test |
|---|---|---|
| Anyone opening an issue or commenting changes settings or decisions | The workflow starts only for owners, members and collaborators; the job checks write access for settings and triage access for decisions | `test_a_request_changes_settings_only_for_someone_with_write_access`, `test_a_comment_command_is_logged_and_reaches_the_quarantine_list` |
| A golden path writes to a repo its requester can't | The org App checks the requester's write access to the target repo first | `test_a_golden_path_never_writes_to_a_repo_the_requester_cannot_write_to` |

## Keys and tokens

| Threat | What stops it | Test |
|---|---|---|
| A tracker key is sent to a host an attacker names in settings | The Jira site must be `*.atlassian.net`, redirects aren't followed, keys go only to their service's own host. The one exception is the triage key: it goes to the https endpoint set in `[ci.triage] url` in the repo's own settings file, which only people with write access can change | `test_the_jira_key_can_only_go_to_an_atlassian_site_even_through_an_app_request`, `test_the_copilot_key_never_reaches_the_report_file_host` |
| A refused key's text ends up in a page or summary | Errors say what was refused, never the key | `test_a_refused_key_is_said_without_the_key_and_keeps_what_was_pulled` |
| A workflow runs code from a moved tag | Every action StackVitals' own workflows and the Action use is pinned to a commit (the Action itself is yours to pin; see below) | `test_every_action_is_pinned_to_a_commit` |
| A new upload to PyPI changes what the Action runs with your token and secrets | The Action installs from its `uv.lock`: exact versions with hashes, never the newest, and only the 11 packages it needs, not the 37 of a full install with the MCP server | `test_the_action_installs_its_locked_dependencies` |
| A compromised build tool changes a release before it is signed | The build job is read-only with a pinned build backend and no cache; a separate job, behind the `release` environment, signs and publishes | `test_releases_build_read_only_and_sign_in_a_separate_job` |

## The app in the browser

| Threat | What stops it | Test |
|---|---|---|
| The app's page runs code from elsewhere | Everything is bundled into the data branch; the page allows only its own scripts (`script-src 'self'`) and talks only to GitHub's API and raw files, other repos' Pages sites (`*.github.io`, to read a public repo's published data), Linear's API and the optional sign-in relay; images load only from itself and GitHub's avatar host (`avatars.githubusercontent.com`) | `test_the_app_ships_with_its_libraries_licences_and_no_remote_code` |
| A GitHub token pasted in the app outlives the visit | It stays in the tab's session storage and is gone when the tab closes, unless the person ticks "Remember on this device"; Sign out removes it. It goes only to `api.github.com`. On an `<owner>.github.io` Pages address, every Pages site of that owner shares one origin, so another of the owner's Pages sites opened in the same tab can read the tab's token ("Remember" is off there for the same reason) | |
| The sign-in relay keeps or leaks tokens | The relay is optional and stateless: it only swaps GitHub's one-time code (with PKCE and a state check) or a refresh token for a token and returns it; it stores nothing and serves only the app's own address | `nothing is logged`, `unknown origins, missing PKCE, foreign redirects and odd grants never reach GitHub` (worker/relay) |
| A connector secret saved from the app is seen on the way | The value is sealed in the browser (libsodium sealed box) with the repo's own Actions public key; only the sealed value reaches GitHub, and the app never reads a secret back | `a sealed secret opens with the repo's private key and holds the exact value` (web/test) |

## Private data on public pages

| Threat | What stops it | Test |
|---|---|---|
| A public repo's data branch keeps private tracker titles, links or sprint names | Titles, links and sprint names are dropped for public repos | `test_a_public_repo_never_keeps_tracker_titles_links_or_sprint_names` |
| A public portal shows private repos | Private repos are left out of every page and file | `test_private_repos_never_reach_a_public_page_and_forks_are_not_judged` |
| Code starts sending data to a new host without the privacy page saying so | Every outside host in the code must be on the privacy page | `test_the_privacy_page_names_every_outside_host_the_code_can_reach` |
| Dependency names leave a private repo | `[deps] outside_lookups = false` keeps every name in the repo | `test_with_outside_lookups_off_no_dependency_name_leaves_the_repo` |

## Losing or corrupting history

| Threat | What stops it | Test |
|---|---|---|
| Two runs overwrite each other's history | Pushes retry on top of the other run | `test_overlapping_runs_converge_without_losing_either_side` |
| A run dies half way and leaves partial data | Nothing is written until the commit; the next run catches up | `test_a_run_that_dies_before_its_commit_leaves_nothing_and_the_next_run_catches_up` |
| A write to Jira or Linear repeats when a push is retried | Write-back is planned before the commit and sent once after it | `test_write_back_sends_after_the_commit_once_and_never_floods_old_issues` |

## Not covered

- Your own workflow file: StackVitals can't stop someone with write access from editing it.
- The StackVitals Action reference in your workflow: `@v0` moves with each release. To fix exactly what runs, pin it to a
  release's commit SHA, as you would any action.
- GitHub itself, the runners and the actions it pins.
- What a model provider does with what triage sends it (off by default; [privacy.md](privacy.md)).
