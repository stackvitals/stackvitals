# How well the existing features work

The accuracy cards check StackVitals' rules. This folder checks the features around them: how much of the real world
each one reads correctly, what it costs and how it scales. Each row has the value measured, its sample and the
method; `scorecard.json` holds them all, built by `scorecard.py` from the scripts here.

| Feature | Measured | Result |
|---|---|---|
| Portal: `catalog-info.yaml` | Real files found by GitHub code search, read by Portal's own parser (`catalog.py`) | 186 of 198 read with no problems (94%). All 12 flagged files had real faults: no owner or lifecycle (fields Backstage requires), invalid YAML, an empty kind. 208 of 218 entities name an owner |
| Test reports in run artifacts | A seeded sample of 190 crawl repos: their artifact lists, and the newest report-like artifact of each opened and parsed (`reports.py`) | 16 keep report-named artifacts; 4 of those held report files (3 JUnit, 1 TRX), and all 5 files parsed. Of 23 repos with loosely named artifacts ("html-report", "test-shard-3"), 2 held JUnit, both inside coverage-named artifacts, which StackVitals reads too. So about 3% of active repos keep readable test reports today: most of CI Health's value comes from job history, and single-test features need a team to upload reports |
| Reading CI history | GitHub requests per CI run read, cold, one day (`api_use.py`) | About 2 requests per run (pytest 2.2, React 2.0). A day of React (about 600 runs) needs about 1,300 requests cold; the Action's later runs read only what finished since the last one, about 50 an hour for React against the built-in token's 1,000 per repo |
| Dependency evidence | The crawler's daily package files | 4,033 packages (2,270 npm, 1,763 PyPI); source repo known for 95.5% (38% proven by a signed build or publish attestation); licence known for 98.6%; OSV checked for all, 784 with advisories, 26 flagged as malware |
| Data branch size | One real busy day (Sentry's CI, 2,929 records) replayed for 400 days with the Action's write path, 24 runs a day (`branch_growth.py`) | 147 MB of history after 400 days by default, 48 MB with squash; the files themselves stop at 41 MB (180-day retention). See below |
| Deployment settings with no setup | The DORA card | 30 of 35 held-out repos right (53 of 60 with an earlier 25) |
| Regular responders | The community card | Catch about half the project answers a roles-only rule misses |
| Answers for AI agents (MCP) | The agents card | An agent with StackVitals used 259 GitHub calls against 214 without, on single failures |

Not measured yet, and why:
- **In-browser SQL:** measured on 2026-10-21 on 20,648 pull requests ([../../../docs/scaling.md](../../../docs/scaling.md)); a
  re-check is due.
- **Comment commands' access check, chat alerts, uploads from other CI systems:** covered by tests only. A live
  check needs an outside account, a webhook or another CI.
- **Test-level quarantine:** the rule now needs 3 or more flakes, as jobs do; its masking rate needs repos that
  upload test reports.

## Data branch size

The history is measured as git counts it after a full repack: what a clone of the repo downloads for the branch.

| Day | History, no squash | History, squash every 1,000 commits | Files |
|---|---|---|---|
| 50 | 17.57 MB | 9.21 MB | 12.87 MB |
| 100 | 28.92 MB | 12.62 MB | 23.55 MB |
| 150 | 48.89 MB | 24.53 MB | 34.24 MB |
| 200 | 68.22 MB | 35.79 MB | 40.86 MB |
| 250 | 87.76 MB | 32.27 MB | 40.87 MB |
| 300 | 107.4 MB | 40.26 MB | 40.88 MB |
| 350 | 126.73 MB | 44.29 MB | 40.87 MB |
| 400 | 146.64 MB | 48.03 MB | 40.88 MB |

- **Files:** retention keeps the files flat at about 41 MB from day 180, well under the 250 MB cap.
- **History without squash:** it grows by about 0.37 MB a day, because every run's commit rewrites today's file.
  Since a normal `git clone` fetches every branch, everyone who clones a repo this busy downloads it.
- **With `squash-history: true`:** the history stays near 40-50 MB.

This is Sentry's scale, one of the busiest public repos (2,929 CI records a day); a repo with a tenth of the traffic
grows about a tenth as fast. Squash is off by default because it force-pushes the branch. For busy repos the setup
page should suggest it. A lighter option to measure next folds each finished day's run commits into one, so history
grows by a day's file instead of a day's 24 versions of it.
