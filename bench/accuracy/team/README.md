# Team loops

Team Flow suggests reviewers and, since 2026-10-23, requests them on pull requests nobody was asked to review. This card
checks the suggestions before they turn into requests.

## Suggested reviewers (`reviewers.py`)

For each of 26 public repos' last 50 reviewed, merged pull requests by people (1,186 in all), using only what was known
before each opened: was a maintainer who really reviewed it among the top 3 suggestions? Scored beside the plain rule of
the 3 maintainers who reviewed most in the repo before it.

| Rule | Top 3 held a real reviewer |
|---|---|
| Busiest reviewers in the repo | 932 of 1,186 (78.6%) |
| Suggestions before 2026-10-23 (who wrote and reviewed in the same folders, CODEOWNERS, eased by load) | 955 (80.5%); against the busiest: McNemar p = 0.07 |
| Suggestions now (plus who reviewed this author's earlier PRs) | **975 (82.2%, 80-84%)**; against the busiest: p = 0.0004 |

**How the change was chosen:** the folder suggestions barely beat the busiest reviewers, so variants were tried on the
even-numbered repos and kept only if they also won on the odd ones. Adding who reviewed the author's earlier pull
requests (teams pair) did: held out, 440 of 555 (79.3%) against 430 (77.5%) before and 405 (73.0%) for the busiest
reviewers. No repo holds more than 50 of the 1,186; resampling repos, the suggestions' range is 75-89% against
70-87% for the busiest reviewers (`reviewers-results.json`, `by_repo`).

**What it can't show:** no CODEOWNERS files were read for these repos (CODEOWNERS only nudges the order), and "a real
reviewer was in the top 3" is not "the best reviewer": a team that always waits for one person scores high either way.

## Prospective test (`prospective.py`)

The test above looks back. This one looks forward: on 2026-10-24 the top 3 suggestions (and the 3 busiest reviewers)
were frozen for 877 open pull requests in 26 public repos, each opened in the 30 days before the stored read (14-17
October 2026), not a draft, and with no review from the project's maintainers yet. The suggestions used only the stored
history, and logins are kept hashed, so the file names nobody. `prospective-manifest.json` holds the file's SHA-256, the
rule, the test and the bar, fixed before any outcome was looked at:

- **Hit:** the first review by an owner, member or collaborator other than the author, after the freeze, came from one
  of the 3 names. Pull requests no maintainer reviewed are counted apart, never as misses. Reviews between the read and
  the freeze (up to a week) existed before the freeze, so they are scored apart as a weaker read.
- **Test and bar:** the suggestions' hit share with its 95% range, and McNemar's test against the busiest reviewers; met
  when the lower bound is at least 65% and the busiest reviewers don't do significantly better.
- **What to read it against:** 73 of the 877 have fewer than 3 suggestions, 262 suggest exactly the busiest reviewers
  (so the comparison rests on the other 615), and facebook/react holds 114; ranges over repos are reported beside it.

Scored from 2027-01-15.

## Reproduce

```
python bench/accuracy/team/reviewers.py --flow <folder of flow stores, one per repo>
python bench/accuracy/team/prospective.py freeze --flow <folder of flow stores>   # done 2026-10-24
GH_TOKEN=... python bench/accuracy/team/prospective.py score                       # 2027-01-15 or later
```
