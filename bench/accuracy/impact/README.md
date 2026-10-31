# Test impact and flaky rules on public test reports: not measurable yet

Run 2026-10-29. The question: on real repos, how many of a pull request's real test failures would test impact
(`stackvitals ci impact`) have run, and do our flaky-test rules agree with Trunk's documented one (a test that both
passed and failed on the same commit)?

## What it took to find data

- 500 active crawl repos (100+ stars, not archived), drawn with seed 20261029 ([find_report_repos.py](find_report_repos.py)):
  one artifact list each. 17 kept test-report artifacts; 8 had a readable report from a pull request branch
  ([search.json](search.json)). That matches the earlier finding that about 3% of active repos keep test reports.
- Five of those, one per language, were read for 45 days: every run, its test reports and the pull requests' changed
  files, capped at 600 requests a repo ([collect_reports.py](collect_reports.py)).

## What the data holds

| Repo | Runs | Reports | On PR runs | Test results | Failed | Failed on PR runs |
|---|---|---|---|---|---|---|
| 99designs/gqlgen (Go) | 281 | 20 | 0 | 46,577 | 4 | 0 |
| frankarobotics/franka_ros2 (C++) | 7 | 3 | 0 | 2,564 | 64 (lint) | 0 |
| langchain4j/langchain4j-spring (Java) | 164 | 243 | 62 | 153,293 | 8 | 0 |
| shap/shap (Python) | 284 | 37 | 2 | 18,830 | 0 | 0 |
| tomkerkhove/promitor (.NET) | 591 | 69 | 33 | 107,913 | 1 | 1 |
| **All** | **1,327** | **372** | **97** | **329,177** | **77** | **1** |

([totals.json](totals.json), [replay-results.json](replay-results.json))

## Reading it

Of 329,177 test results, 77 failed and only one failed on a pull request run; no test both passed and failed on the
same commit. Public repos mostly keep reports from their green runs (an upload step after a failed test step often
doesn't run), so the failures that test impact must catch and the flips that flaky rules look for are not in the
public record. Neither number can be measured honestly from this, so none is claimed.

The measure that does work is each repo's own: the Action replays test impact on the repo's past pull requests every
run (each judged with only what was known before it) and shows how many real failures it would have run, on the CI
page. For flaky rules, the job-level checks in [../flaky](../flaky/README.md) stand, where job history is public.

To re-run: `python find_report_repos.py 500`, `python collect_reports.py`, `python replay_tia.py` (GH_TOKEN set; they
write to `work/`).
