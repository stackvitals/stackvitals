# First responses, counted for what the project did

"Time to first response" is the most quoted community number, and the tools that compute it disagree on what a first
response is:

- **issue-metrics** (GitHub OSPO): the first comment by anyone but the author and bots; issues nobody answered are left
  out of the median.
- **OpenDigger:** the first comment by anyone but the author, bots included, or a close; an unanswered issue counts as
  15 days.
- **StackVitals:** the first reply from a maintainer (owner, member, collaborator, or anyone who merged a PR there) or,
  on issues, from a regular responder (someone who commented on 10 or more other people's issues, gave the first
  review on 2 or more other people's PRs, or triaged someone else's issue, in the last 360 days), or a close. Issues still waiting stay in the median
  (Kaplan-Meier), so a repo that answers only the easy ones can't look fast.

This folder measures the three rules on the same issues from the crawl, and checks each one against labelled comments.

## Across the crawl (`responses.py`)

86,733 issues opened by outside contributors 1 to 180 days before the read, in 2,370 public repos with at least 10 of
them:

- **Unanswered issues hide the wait.** In 1,447 repos (61%), more than half of the outside issues have no answer from a
  maintainer, yet issue-metrics' answered-only median still shows a number. Where both medians exist (843 repos), the
  one that counts waiting issues is 5.2 times the answered-only one (median repo); in 583 (69%) it is at least twice.
- **Half of issue-metrics' first responses aren't the project's.** 20,283 of 39,431 (51%) first comments came from
  someone who isn't a maintainer.
- **OpenDigger counts bots:** 6,939 of its first responses are bot comments.
- **Regular responders:** 1,695 repos have at least one; they wrote 3,419 of the non-maintainer first comments (17%).
  Counting them gives 957 repos a median instead of 844; where both rules give one, the typical repo's median doesn't
  move.

## What the non-maintainer first comments are (labels)

Each item is an issue's first comment from someone who isn't a maintainer: the issue's title, the commenter's role as
GitHub shows it, how long after opening it came, the first 500 characters, and whether a maintainer replied later.
Labels follow [codebook.md](codebook.md): a project answer (someone acting for the project), peer help (another user
with a real answer), a drive-by ("+1", "same here", "any update?") or unclear. Two model families labelled every
comment blind (Claude, then Gemini 3.5 Flash-Lite); their disagreements were adjudicated blind, and the tables below
use the adjudicated labels. [Labels](#labels-two-model-families) shows how much the labeller moves each number. No
person has audited the labels.

Two sets, at most 5 items per repo so large repos don't dominate:

- **First set** (`labels-main.csv`): 400 comments from 85 repos. The regular-responder rule was chosen on it.
- **Held-out set** (`labels-validation.csv`): 400 comments from 86 other repos, drawn after the rule was fixed (seed
  14), half from regular responders' comments so the rule's mistakes get enough items; shares are weighted back to the
  pool.

| Of the non-maintainer first comments | First set | Held-out set |
|---|---|---|
| Drive-bys: issue-metrics counts these as the answer | 46% (41-50%) | 46% (40-52%) |
| Peer help | 34% (29-39%) | 35% (29-41%) |
| Project answers by people without a listed role: the roles-only rule misses these | 21% (17-25%) | 19% (15-23%) |
| Claude and Gemini agree | 72% (kappa 0.57) | 68% (kappa 0.52) |

The regular-responder rule on the same comments:

| | First set (chose the rule) | Held-out set |
|---|---|---|
| Comments it counts as answers | 83 | 198 |
| Drive-bys among them | 6% (3-13%) | 17% (12-22%) |
| Real answers among them (project or peer) | 94% (87-97%) | 83% (78-88%) |
| Project answers it catches (roles only: 0%) | 67% (56-77%) | 47% (38-59%) |

On repos it was not tuned on, the rule catches about half of the project answers the roles-only rule misses, and
about one in six comments it adds is a drive-by (one in nine on Claude's labels alone, one in five on Gemini's). issue-metrics counts every one of these comments, nearly half of them
drive-bys. A rule that also counted people with 3 or more merged PRs caught 7 more points of project answers on the
first set, but 9 of the 15 comments it added were drive-bys or other users' replies, so it was left out.

## Labels: two model families

- **Agreement.** Both labellers read the same codebook and the same evidence, blind to each other. They agree on the
  kind of comment for 72% of the first set (kappa 0.57) and 68% of the held-out set (kappa 0.52).
- **Where they split.** Most splits are between peer help and a drive-by, and between a project answer and peer
  help, when someone without a maintainer role triages ("fixed in #12", "duplicate of #8") or offers to take the
  issue.
- **Adjudication.** Every disagreement went to a third reading that saw the labels as A and B, never whose they were
  (`adjudication-main.csv`, `adjudication-validation.csv`, with reasons). It sided with Claude's label 93 of 112 and
  97 of 129 times.
- **Who adjudicated.** The third reading was Claude's. Gemini, adjudicating a sample of the same disputes, mostly
  sided with its own labels, so adjudication alone doesn't settle who is right.
- **Each held-out number on each labeller's labels** (`../label-sensitivity.json`):

  | | Claude's labels | Gemini's labels | Adjudicated |
  |---|---|---|---|
  | Drive-bys that issue-metrics counts | 46.9% | 50.8% | 45.8% |
  | Project answers the roles-only rule misses | 21.7% | 22.6% | 18.9% |
  | Project answers regular responders catch | 45.2% | 32.3% | 47.4% |
  | Drive-bys among what they add | 11.1% | 21.5% | 16.7% |

  The findings about issue-metrics hold under either labeller. How well the regular-responder rule does depends on
  the labeller.
- **A clearer codebook** (version 2: triage from anyone counts as a project answer, a bare "I'd like to take this" is
  a drive-by) was tested on a random 100 comments relabelled by both. Agreement moved only from 70% to 74% and from
  72% to 72% (kappa 0.55 to 0.59, and 0.57 to 0.58). So the gap is the two models judging differently, not the
  codebook being vague.

**A six-model check** (`../panel.py`, 2026-10-24): six models from three families (two OpenAI, two Google, two
Anthropic) answered plain-language questions on 30 of these replies, drawn from a pool that put the replies the two
labellers disagreed on first. Their majority matched the labels on 11 of the 24 it decided with a clear label (30 asked): it
called 5 of 7 labelled drive-bys and 6 of 9 labelled project answers helpful answers from other users
(`label_to_majority` in `../panel-results.json`). On these harder items, then, the line between "adds
nothing", "helps" and "acts for the project" is where model families part, and the drive-by share above should be read
with that in mind. No person has labelled them yet.

## People who triage count too (`triage.py`)

On GitHub only people with triage rights (or more) can label, assign, close or mark as duplicate someone else's issue,
so whoever did any of those acts for the project, whatever role their comments show. Read for 167 of the 171 labelled
repos (the first 5 such acts on up to 200 recently updated issues each, before the crawl was read; StackVitals itself
also checks each act is from the last 360 days) and added to the regular-responder rule:

| | Tune set: regular responders | + people who triage | Held-out set: regular responders | + people who triage |
|---|---|---|---|---|
| Project answers caught (weighted) | 67% (56-77%) | 72% (62-81%) | 47% (38-59%) | 57% (46-69%) |
| The same on Claude's labels / Gemini's | 67% / 55% | 71% / 59% | 45% / 32% | 53% / 38% |
| Drive-bys among what is counted (unweighted) | 6% | 7% | 17% | 16% |

The rule only adds people, so the comments it adds are the whole test: 5 on the tune set (4 project answers, 1
drive-by) and 6 on the held-out set (4 project answers, 1 peer help, 1 unclear). On the held-out set that is 4 more of
the project's answers found, nine points once weighted back to the pool (the held-out sample over-drew regular
responders' comments, so each of the others counts for more), and the gain holds on either labeller's labels. The
held-out set had been labelled before; it was used once, for this decision. StackVitals now uses the rule.

## Which organisation people say they work for (`affiliation.py`)

The elephant factor (CHAOSS: the fewest organisations behind half the work) needs to know where people work, and public
profiles often don't say. StackVitals uses only the company people put on their profile (membership of the repo's own
org is not an employer: volunteer projects have orgs too). On 24 crawled repos with 20+ merged PRs by people in 180
days, the median repo had 81% of its merged work by people with no company on their profile (from 4% to 100%), and a
factor could be claimed for 9. So the page shows the unknown share beside the factor, computes the factor over the work
with a known organisation (CHAOSS counts all work), claims none when most of the work is unknown, and names no
organisation of a single person.

## New questions outside GitHub (`channels.py`)

Five public projects with a Discourse forum, read 2026-10-23 with StackVitals' own Discourse connector (forum staff as
the team, no team list; moderator and system notices aren't replies) against GitHub search for the same 30 days. The
forum serves its whole community and the issues are one repo's, so the share compares new forum topics with that repo's
new issues, not like with like:

| Project | New forum topics | The repo's new issues | Forum's share | Topics anyone answered | Answered by forum staff |
|---|---|---|---|---|---|
| python/cpython | 129 | 668 | 16% | 83% | 11% |
| rust-lang/rust | 192 | 455 | 30% | 63% | 5% |
| pytorch/pytorch | 28 | 782 | 3% | 23% | 8% |
| JuliaLang/julia | 126 | 143 | 47% | 73% | 13% |
| huggingface/transformers | 368 | 176 | 68% | 51% | 1% |

Two things follow. A tool that reads only GitHub misses a project's forum, which here held from a few to most of the
new questions, so Community reads Discourse (and Slack, Discord and GitHub Discussions) when connected. And forum staff
answered from 1% to 13% of topics while someone answered from 23% to 83%, so an answer rate from staff alone would
mislead: the connector takes a `team` and `groups` setting for the people who answer for the project. Answer shares come
from the 26 to 120 most recent topics per forum, which leans toward topics that had less time to be answered;
`channels-results.json` holds the rest.

## What it can't show

- **By repo:** the labelled sets barely cluster: 400 items in 85 repos (the biggest holds 5) and 400 in 86
  (the biggest holds 10), so the item-level ranges above stand; other cards add ranges over repos where one repo holds
  many items.
- No person has audited the labels; the two model families disagree on about a third of comments (above).
- The crawl doesn't record who closed an issue, so any close counts as an answer here; the app knows the closer and
  skips the author's own close.
- The crawl keeps only a PR's first reviewer; the app sees every review, so it may find a few more regular responders.
- About 43% of the project answers from occasional contributors still go uncounted (57% caught held out, counting
  people who triage); the rule errs toward "still waiting" rather than toward counting drive-bys.
- Labels judge the first 500 characters of a comment.

## Reproduce

```
# Crawl tables: the issues, comments, prs and repo_meta parquet folders inside the crawl release tars (public at launch)
python bench/accuracy/community/responses.py <crawl folder> --home <work folder>
python bench/accuracy/community/responses.py <crawl folder> --home <work folder 2> --seed 14 --exclude <work folder> \
    --stratify --out bench/accuracy/community/responses-validation-results.json
python bench/accuracy/community/score_labels.py --crawl <crawl folder>
# Second labeller, blind adjudication, final labels, each number on each labeller's labels
python bench/accuracy/labeller.py community-main --work <work folder> --run --batch 20   # and community-validation
python bench/accuracy/adjudicate.py community-main --work <work folder> --packets         # then --apply
python bench/accuracy/finalise.py community --work <work folders' parent>
python bench/accuracy/sensitivity.py --work <work folders' parent> --cards community
# Triage acts, affiliation, forums
GH_TOKEN=... python bench/accuracy/community/triage.py fetch --crawl <crawl folder> --home <work folder 3>   # then score
GH_TOKEN=... python bench/accuracy/community/affiliation.py --crawl <crawl folder> --repos 25
GH_TOKEN=... python bench/accuracy/community/channels.py --home <work folder 4>
```

Results: `responses-results.json`, `responses-validation-results.json`, `labels-results.json`. The labels are frozen
in `labels-main.csv` and `labels-validation.csv` (links and labels, no comment text; `kind` is adjudicated, with
`claude_kind` and `gemini_kind` beside it). The first set was drawn before the
script sorted its rows, so it is reproduced from its frozen file rather than from the seed.
