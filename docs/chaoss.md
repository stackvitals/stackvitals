# StackVitals and CHAOSS

[CHAOSS](https://chaoss.community) defines open source community health metrics. Each row below is a CHAOSS metric StackVitals answers, the code that computes it, and where ours differs and why. The list is built from `stackvitals/community/chaoss.py`, and a test checks every function it names exists.

| CHAOSS metric | Computed by | How StackVitals differs |
|---|---|---|
| [Time to First Response](https://chaoss.community/kb/metric-time-to-first-response/) | `community.analyze.first_answer` | Only answers from the project count (maintainers, people who triage, regular responders, or a close), not the first comment from anyone; issues still waiting stay in the median (Kaplan-Meier) instead of dropping out. On labelled public issues, 46% of the first comments other tools count are drive-bys (bench/accuracy/community). |
| [Issue Response Time](https://chaoss.community/kb/metric-issue-response-time/) | `community.analyze.first_answer` | The same rule as the first response above, for issues. |
| [Newcomer Experience](https://chaoss.community/kb/metric-newcomer-experience/) | `community.analyze.answers_by_tenure` | Measured, not surveyed: how fast first-time contributors are answered against people who contributed before. |
| [New Contributors](https://chaoss.community/kb/metric-new-contributors/) | `community.analyze.funnel` | Bots, AI agents and accounts opening 20 or more items in a day are left out; the funnel also says how many came back within 90 days (CHAOSS has no single retention metric; Inactive Contributors is the nearest). |
| [Contributor Absence Factor](https://chaoss.community/kb/metric-contributor-absence-factor/) | `community.analyze.dependency` | The same definition (the fewest people behind half of the merged work, formerly Bus Factor) over 180 days, with bots and AI agents left out and similar public repos' middle half shown instead of a rank. |
| [Elephant Factor](https://chaoss.community/kb/metric-elephant-factor/) | `community.analyze.elephant` | Organisations from the company on people's public profiles; people without one are counted as unknown and shown, never guessed. The factor is over the work with a known organisation, and none is claimed when most is unknown. |
| [Organizational Diversity](https://chaoss.community/kb/metric-organizational-diversity/) | `community.analyze.elephant` | The share of merged work by organisation, unknown shown. |
| [Project Popularity](https://chaoss.community/kb/metric-project-popularity/) | `community.analyze.star_trend` | Weekly stars kept over time and placed among similar repos, so a launch spike reads as one. |
| [Clones](https://chaoss.community/kb/metric-clones/) | `community.analyze.traffic_summary` | Kept past GitHub's 14 days when a traffic token is set. |
| [Change Request Acceptance Ratio](https://chaoss.community/kb/metric-change-request-acceptance-ratio/) | `flow.analyze.analyze` | Outsiders' pull requests only (insiders merge their own), with its sample size and range. |
| [Change Request Review Duration](https://chaoss.community/kb/metric-change-request-review-duration/) | `flow.analyze.stages` | Split into waiting for a first review and the review itself, counted from when the PR was ready, not opened. |
| [Change Requests Duration](https://chaoss.community/kb/metric-change-requests-duration/) | `core.delivery.phases` | LinearB's four phases (coding, pickup, review, deploy), with review split into its time to approve and time to merge, from first commit to deployment. |
| [Release Frequency](https://chaoss.community/kb/metric-release-frequency/) | `core.delivery.dora` | Counted as DORA's deployment frequency from the source the repo really ships with (deployments, deploy workflows or releases), with the source shown. |
| [Time to Close](https://chaoss.community/kb/metric-time-to-close/) | `connectors.tracker.lead_times` | From Jira or Linear when connected: created to done, by issue type. |
| [Labor Investment](https://chaoss.community/kb/metric-labor-investment/) | `core.investment.mix` | Where merged work went each month (feature, fix, maintenance, security, docs), with how each PR was sorted. |
| [Test Coverage](https://chaoss.community/kb/metric-test-coverage/) | `ci.analyze._coverage` | From the coverage reports CI already uploads, with the change on each pull request. |
| [Upstream Code Dependencies](https://chaoss.community/kb/metric-upstream-code-dependencies/) | `deps.supply.sbom` | From GitHub's dependency graph, with upgrade evidence from public repos for each package. |
| [SPDX Document](https://chaoss.community/kb/metric-spdx-document/) | `deps.supply.parse_spdx` | Read from the SPDX SBOM GitHub generates; StackVitals doesn't write one. |
| [Code of Conduct for a Project](https://chaoss.community/kb/metric-code-of-conduct-for-a-project/) | `portal.inventory.repo_files` | Present or missing, per repo in the Portal catalog. |
| [Bot Activity](https://chaoss.community/kb/metric-bot-activity/) | `core.actors.kind_of` | Bots and AI agents are found in every module and counted apart from people, never mixed into people's numbers. |

20 of CHAOSS's 89 metrics. Most of the rest are about events, governance documents and surveys, which no repo's history can measure; the community page shows a repo's stated policies (governance, funding, response times) beside its numbers instead.
