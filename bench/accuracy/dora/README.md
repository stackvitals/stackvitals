# Deployments and failures: what DORA numbers count

DORA's numbers rest on two choices most tools make silently: what counts as a deployment, and which deployment a
failure belongs to. This folder measures how much each choice moves the result and checks StackVitals' choices
against the commit graph and labelled repos.

## Which deployment a revert blames (`linkage.py`)

DevLake, and most tools that copy its DORA queries, blame a failure on the last deployment finished before it began
(time order). StackVitals follows each revert to the pull request it undoes and to the deployment that shipped that pull
request (the fix chain), and says "never shipped" when the change was reverted before any deployment ran it.

On the merged pull requests and releases of 23 public repos (aiohttp, pandas, pydantic, react, uv, vue and others), 18
merged reverts in a year:

- **11 of the 18 reverts (61%) undid a change that never shipped.** Time order still counts each one as a failed
  deployment. (A first version missed 3 of these, reverted before any later release; the review caught it.)
- **Of the 7 that shipped, time order blamed a different deployment for 5** (71%, range 36-92%); the median distance
  was one deployment.
- In 3 of the 7 repos with reverts, the 90-day change failure rate lands in a different DORA tier under the two rules.

**Checked against the commit graph** (`--check`, GitHub's compare API: does the blamed release contain the undone pull
request's merge commit?), on the 16 links where both commits were known:

| | Right | Wrong |
|---|---|---|
| Fix chain: "never shipped" (the last release before the revert lacks the change) | 10 | 0 |
| Fix chain: the release that shipped it contains the change | 4 | 2 |
| Time order: the blamed release contains the change | 4 | 12 |

Time order blamed a release that never held the undone change in 12 of 16 cases. Both of the fix chain's misses are in
repos that ship from maintenance branches with backports (aiohttp 3.14, pandas 3.0.x). There, the release after a
main-branch merge doesn't contain that merge commit, and time order blames the same release. Following backport pull
requests would fix both and is left for later.

**A larger held-out check** (`linkage-more-results.json`): 20 more repos chosen for having the most merged reverts in
the crawl (by GitHub's revert-button branch names), none used for tuning. 16 had deployments, with 99 merged reverts in
a year:

- **63 of the 99 (64%, 54-72%) undid a change that never shipped.**
- 77 could be linked to the pull request they undid; 22 couldn't (the undone change wasn't in the year read, or the
  revert named no pull request).
- Checked against the commit graph, on the 73 links where both commits were known:

  | | Right | Wrong |
  |---|---|---|
  | Fix chain: "never shipped" | 59 | 0 |
  | Fix chain: the release that shipped it contains the change | 14 | 0 |
  | Time order: the blamed release contains the change | 14 | 59 |

  The fix chain was right on all 73 (95-100%); time order blamed a release lacking the change on 59 (81%, 70-88%).
- Across both samples, 89 checked links: the fix chain was right on 87 (98%, 92-99%), time order wrong on 71 (80%,
  70-87%). None of this needs a labeller: the commit graph is the answer key.

## How much the deployment definition moves the tier (`spread.py`)

For 4,618 crawled repos with at least 10 days with a merge in the 13 weeks before the read, the deployment-frequency
tier was computed twice: every merged pull request as a deployment (DevLake's merge-as-deploy option) and every GitHub
release as one. **The tier certainly changes for 61.9% of repos, certainly stays for 3.5%,** and 34.6% stay undecided
because the crawl then read only a repo's newest 20 releases (it reads 100 from 2026-10-22). Most moves are down: 1,676
repos that are "high" by merges are "low" by releases.

## Which source each rule counts (`sources.py`)

25 repos drawn at random (seeded) from the crawl's CI records, none of them used to tune the rules. For each: every
workflow file, the releases and deployments of the last 90 days, and 90 days of runs of any workflow a rule could
count. Labels follow [codebook.md](codebook.md): which workflows ship the project to users (155 readable workflow files)
and which ways of counting match the repo's real shipments. Two model families labelled every repo blind (Claude,
then Gemini 3.5 Flash-Lite), and their disagreements were adjudicated blind; the tables use the adjudicated labels
(see [Labels](#labels-two-model-families)). No person has audited the labels.

DevLake expects a pattern written for each repo, so it is scored twice: with its default, and with the pattern a user
would plausibly write after reading their workflow names, `(?i)(deploy|release|publish|push-image)`, with no production
filter (the reading most generous to DevLake; `devlake_configured.py`, runs read on 2026-10-22).

| Repo-level, no setup: the source counts the repo's real shipments | Right |
|---|---|
| StackVitals (Deployments API, else deploy workflows unless they are a side service, else releases, else release workflows) | **23 of 25, 92%** (75-98%) |
| DevLake's default deployment pattern `(deploy\|push-image)` on workflow names | 6 of 25, 24% (12-43%) |
| DevLake with that configured pattern | 9 of 25, 36% (20-55%) |
| Every merge as a deployment | 3 of 25, 12% (4-30%) |

Paired on the same 25 repos (McNemar's exact test): StackVitals was right where DevLake's default was wrong on 17 repos
and never the other way (p < 0.001); against the configured pattern, 14 and 0 (p < 0.001); against every merge, 20
and 0 (p < 0.001).

The configured pattern mostly fails by also counting what isn't shipping: GitHub Pages builds ("pages build and
deployment") of docs sites, release drafters, a quarterly tag job, and hand-run re-bakes of an existing release. A
pattern hand-written per repo by someone who knows it can match the labels; that per-repo setup is what StackVitals'
rule saves.

| Workflow-level: ships to users | Precision | Recall |
|---|---|---|
| StackVitals' name rule (deploy, release, publish or push-image, minus 47 words like preview, docs, check, beta) | 84% (62-94%) | 89% (67-97%) |
| DevLake's default pattern | 0 of 1 | 0 of 18 |

On Claude's labels alone, 19 workflows shipped and the rule's precision and recall were both 89%; adjudication moved
one workflow to "doesn't ship": a hand-run job that re-bakes auxiliary assets onto an existing release. Of the workflows that ship, 17 are named for releasing or publishing ("Release", "Publish to npm", "Build and
publish ORFS images") and none for deploying: DevLake's default pattern finds none of them, so its deployment frequency
reads zero for these repos unless someone writes a pattern per repo. StackVitals' rule missed the two with neither
word ("PyPI", "Upload assets to dl.oxide.computer"). Its one match was a docs site. Every merge counts as a deployment only where
each merge really ships (3 websites and apps here).

StackVitals' first pass got 22 of 25. One miss was a workflow file named `deploy.yml` whose display name, "Check and
Publish …", hit the deny word "check"; a file named just deploy, release or publish now ships whatever its display name
says (checked against the 117 workflows labelled earlier: no change there). The two left are repos that published
nothing in the 90 days (a tag-only GoReleaser and a hand-run PyPI upload): the count of zero is right, and the page says
"no deployment source found" instead of naming the source.

## A second held-out sample (35 more repos)

The same draw (seed 13) extended to 60 repos, leaving out the first 25 (`sources.py collect --exclude`). It was
labelled the same way (Claude, then Gemini 3.5 Flash-Lite, disagreements adjudicated blind) and scored with the rule
unchanged (`sources-more-results.json`, `sources-more-labels.csv`, `devlake-configured-more-results.json`).

| Repo-level, no setup | Right, 35 new repos | All 60 repos |
|---|---|---|
| StackVitals | **30 of 35, 86%** (71-94%) | 53 of 60, 88% |
| DevLake with a configured pattern | 13 of 35, 37% (23-54%) | 22 of 60, 37% |
| DevLake's default pattern | 3 of 35, 9% (3-22%) | 9 of 60, 15% |
| Every merge as a deployment | 2 of 35, 6% (2-19%) | 5 of 60, 8% |

- **Paired on the new repos:** against DevLake's default, 28 to 1; against the configured pattern, 19 to 2; against
  every merge, 29 to 1. All p < 0.001.
- **On each labeller's labels** the new sample reads 86% (Claude), 89% (Gemini) and 86% (adjudicated).
- **The weak spot is workflow recall:** the name rule found 25 of the 42 workflows that ship (60%, 44-73%), at 81%
  precision (64-91%).
  - It misses shipping workflows with plain names: "docker", "pypi", "CD", "Main", "Build LNbits AppImage".
  - It rejected two real ones on a deny word: a course site whose Pages site is the product, and "Create Java and
    GitHub Release".
- **The next rule to measure** reads what a workflow does rather than its name: triggered by a tag or release, with a
  publish step such as `docker push`, a PyPI or npm publish, or goreleaser.

## Environments: staging, production and publishing (`environments.py`)

On the 60 labelled repos (59 readable), GitHub environments read the way the product reads them today (production
names shown, everything else hidden):

| Environments | Repos |
|---|---|
| Any | 40 |
| A production name (production, prod, live) | 7 |
| A staging-like name (staging, preview, dev, test, qa, ...) | 7 (5 with production too) |
| A publishing name (pypi, npm, github-pages, release, docker, ...) | 29 |

Showing staging apart from production matters for few public repos (7 of 59). Publishing environments looked like a
missed signal: 29 repos have one. **Checked against the labels, they add nothing:** of the 8 repos with
deployments to a registry environment (pypi, npm, release), the labellers accepted those deployments as a source in 5,
but releases were also right in all 8, and releases are what StackVitals already picks there. GitHub Pages deployments
were docs in every repo but one (a course site, where the pages are the product). So no new source was added; the
deploy dry run (`stackvitals delivery owner/repo --deploys`) shows these environments as seen and skipped instead.

## Which release an incident blames (`incidents.py`)

Change failure rate and time to restore link each incident to the last deployment finished before it was reported
(DevLake's rule, and StackVitals' by default). Regression reports often say which release broke things, so they can
check that rule. 60 regression and incident issues that name a version (seeded, at most 2 a repo, 39 repos from the
crawl) were labelled with `incidents-codebook.md` (Claude, Gemini, blind adjudication: the adjudicator sided with Claude
in 29 of 33 disputes; kappa is low, they agreed on 27 of 60, mostly because Gemini named a release where Claude said
unclear).

Sampled: 60 issues in 39 repos. Decided (a label other than "unclear"): 30 issues in 24 repos (the `repos` count in
`incidents-results.json`), of which 15 name the release that broke (13 repos) and are scored below.

| | Result |
|---|---|
| Reports whose text names the release that broke | 15 of 60 (15 weren't from a release at all; 30 don't say) |
| The last release before the report was that release | **6 of 15** (40%, 20-64%; 13 repos, 19-66% counting each repo once) |
| The newest released version the report names was it | 10 of 15 (67%, 42-85%) |
| Held-out half (the naming rule wasn't tuned on it) | 4 of 9 against 2 of 9 for the last release; McNemar p = 0.5 (all 15: p = 0.13) |

**What it means:** in libraries, a regression is usually noticed a release or two after the one that brought it, so
"the last deployment before the incident" blames the wrong release more often than not when the reporter can say which
one broke. The naming rule does better but rests on 15 reports and isn't significant, so the metric is unchanged; the
DORA guide (`docs/dora-guide.md`) says so beside change failure rate. Services that deploy continuously and report
outages within hours may fare better; these are mostly libraries.

## Labels: two model families

- **Agreement.** Claude and Gemini agree on whether a workflow ships for 95% of the 170 workflows (kappa 0.79). They
  agree on a repo's full set of sources for 14 of 25 repos (kappa 0.50). Most splits are over GitHub Pages
  deployments of a library's docs or demo site, which the codebook doesn't count as shipping.
- **Adjudication.** A blind third reading, which never saw whose label was whose, settled 11 source disputes and 8
  workflow disputes (`adjudication-sources.csv`, with reasons). It sided with Claude 9 and 7 times, with Gemini once
  each, and once with neither.
- **The headline on each labeller's labels** (`../label-sensitivity.json`):

  | | StackVitals | DevLake's default | Every merge |
  |---|---|---|---|
  | Claude's labels | 92% | 24% | 12% |
  | Gemini's labels | 88% | 20% | 12% |
  | Adjudicated | 92% | 24% | 12% |

  The headline holds under either labeller.

## What it can't show

- No person has audited the labels; the adjudicator was Claude, blind to whose label was whose.
- The 60 repos are mostly libraries and tools that ship by release, like most public repos; teams deploying services
  from workflows or the Deployments API are few here (9 of 60).
- The linkage study covers releases as deployments in public repos; teams deploying from workflows or the Deployments
  API have more deployments, so time order's misses are likely smaller there, and wider for monthly releasers.
- The revert checks cover 117 reverts from 23 repos (89 links checked against the commit graph); one repo can supply
  many reverts, so the ranges are kinder than the evidence.
- The definition spread compares two definitions the crawl can read for every repo; deploy workflows and the
  Deployments API need per-repo reads and are measured on the labelled repos instead.

## Reproduce

```
GH_TOKEN=... python bench/accuracy/dora/environments.py   # environments of the labelled repos
python bench/accuracy/dora/incidents.py sample --crawl <crawl folder> --home <work>; then fetch, label, adjudicate, score
# Pull request histories: `stackvitals delivery owner/repo` keeps them under ~/.stackvitals/flow/<owner>__<repo>
GH_TOKEN=... python bench/accuracy/dora/linkage.py ~/.stackvitals/flow --check
# Crawl tables: the prs and repo_meta parquet folders inside the crawl release tars (public at launch)
python bench/accuracy/dora/spread.py <crawl folder>
GH_TOKEN=... python bench/accuracy/dora/sources.py collect <folder of the crawl's ci-*.ndjson.gz> --home <work folder>
python bench/accuracy/dora/sources.py score --home <work folder>
```

Results: `linkage-results.json`, `linkage-more-results.json`, `spread-results.json`, `sources-results.json`; labels in `sources-labels.csv`
(adjudicated), Gemini's in `labels-gemini-sources.csv`, agreement in `agreement-gemini-sources.json`, every ruling in
`adjudication-sources.csv`. The 23
linkage repos are the keys of `per_repo` in `linkage-results.json`, their histories read on 2026-10-21 (each linked
revert, with the commit-graph check's verdict, is in `links`); a later read holds later reverts.
