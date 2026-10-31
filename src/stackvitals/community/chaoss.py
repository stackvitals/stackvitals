"""StackVitals' numbers beside the CHAOSS metrics they answer (chaoss.community, 89 metrics read 2026-10-23): which
function computes each, and where ours differs and why. docs/chaoss.md is built from this list, and a test checks every
function named here exists, so the page can't point at code that is gone."""

KB = "https://chaoss.community/kb/metric-"

# CHAOSS metric, its page slug, our function, how ours differs (empty when the definitions agree)
MAPPING = [
    ("Time to First Response", "time-to-first-response", "stackvitals.community.analyze.first_answer",
     "Only answers from the project count (maintainers, people who triage, regular responders, or a close), not the "
     "first comment from anyone; issues still waiting stay in the median (Kaplan-Meier) instead of dropping out. On "
     "labelled public issues, 46% of the first comments other tools count are drive-bys (bench/accuracy/community)."),
    ("Issue Response Time", "issue-response-time", "stackvitals.community.analyze.first_answer",
     "The same rule as the first response above, for issues."),
    ("Newcomer Experience", "newcomer-experience", "stackvitals.community.analyze.answers_by_tenure",
     "Measured, not surveyed: how fast first-time contributors are answered against people who contributed before."),
    ("New Contributors", "new-contributors", "stackvitals.community.analyze.funnel",
     "Bots, AI agents and accounts opening 20 or more items in a day are left out; the funnel also says how many came "
     "back within 90 days (CHAOSS has no single retention metric; Inactive Contributors is the nearest)."),
    ("Contributor Absence Factor", "contributor-absence-factor", "stackvitals.community.analyze.dependency",
     "The same definition (the fewest people behind half of the merged work, formerly Bus Factor) over 180 days, with "
     "bots and AI agents left out and similar public repos' middle half shown instead of a rank."),
    ("Elephant Factor", "elephant-factor", "stackvitals.community.analyze.elephant",
     "Organisations from the company on people's public profiles; people without one are counted as unknown and shown, "
     "never guessed. The factor is over the work with a known organisation, and none is claimed when most is unknown."),
    ("Organizational Diversity", "organizational-diversity", "stackvitals.community.analyze.elephant",
     "The share of merged work by organisation, unknown shown."),
    ("Project Popularity", "project-popularity", "stackvitals.community.analyze.star_trend",
     "Weekly stars kept over time and placed among similar repos, so a launch spike reads as one."),
    ("Clones", "clones", "stackvitals.community.analyze.traffic_summary",
     "Kept past GitHub's 14 days when a traffic token is set."),
    ("Change Request Acceptance Ratio", "change-request-acceptance-ratio", "stackvitals.flow.analyze.analyze",
     "Outsiders' pull requests only (insiders merge their own), with its sample size and range."),
    ("Change Request Review Duration", "change-request-review-duration", "stackvitals.flow.analyze.stages",
     "Split into waiting for a first review and the review itself, counted from when the PR was ready, not opened."),
    ("Change Requests Duration", "change-requests-duration", "stackvitals.core.delivery.phases",
     "LinearB's four phases (coding, pickup, review, deploy), with review split into its time to approve and time to merge, "
     "from first commit to deployment."),
    ("Release Frequency", "release-frequency", "stackvitals.core.delivery.dora",
     "Counted as DORA's deployment frequency from the source the repo really ships with (deployments, deploy "
     "workflows or releases), with the source shown."),
    ("Time to Close", "time-to-close", "stackvitals.connectors.tracker.lead_times",
     "From Jira or Linear when connected: created to done, by issue type."),
    ("Labor Investment", "labor-investment", "stackvitals.core.investment.mix",
     "Where merged work went each month (feature, fix, maintenance, security, docs), with how each PR was sorted."),
    ("Test Coverage", "test-coverage", "stackvitals.ci.analyze._coverage",
     "From the coverage reports CI already uploads, with the change on each pull request."),
    ("Upstream Code Dependencies", "upstream-code-dependencies", "stackvitals.deps.supply.sbom",
     "From GitHub's dependency graph, with upgrade evidence from public repos for each package."),
    ("SPDX Document", "spdx-document", "stackvitals.deps.supply.parse_spdx",
     "Read from the SPDX SBOM GitHub generates; StackVitals doesn't write one."),
    ("Code of Conduct for a Project", "code-of-conduct-for-a-project", "stackvitals.portal.inventory.repo_files",
     "Present or missing, per repo in the Portal catalog."),
    ("Bot Activity", "bot-activity", "stackvitals.core.actors.kind_of",
     "Bots and AI agents are found in every module and counted apart from people, never mixed into people's numbers."),
]


def markdown() -> str:
    lines = ["# StackVitals and CHAOSS", "",
             "[CHAOSS](https://chaoss.community) defines open source community health metrics. Each row below is a "
             "CHAOSS metric StackVitals answers, the code that computes it, and where ours differs and why. The list is "
             "built from `stackvitals/community/chaoss.py`, and a test checks every function it names exists.", "",
             "| CHAOSS metric | Computed by | How StackVitals differs |", "|---|---|---|"]
    for name, slug, where, differs in MAPPING:
        lines.append(f"| [{name}]({KB}{slug}/) | `{where.removeprefix('stackvitals.')}` | {differs or 'Same definition.'} |")
    lines += ["", f"{len(MAPPING)} of CHAOSS's 89 metrics. Most of the rest are about events, governance documents and "
              "surveys, which no repo's history can measure; the community page shows a repo's stated policies "
              "(governance, funding, response times) beside its numbers instead.", ""]
    return "\n".join(lines)
