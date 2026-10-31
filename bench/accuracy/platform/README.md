# Busy repos: does the built-in token keep up, and how fast does history grow?

The workflow token allows 1,000 REST requests an hour per repo (15,000 on Enterprise Cloud), and the data branch keeps
180 days of CI and 400 of the rest under a 250 MB cap. This folder measures both on busy public repos, read-only.

## Requests (`busy.py`)

StackVitals' own CI collector read one day of astral-sh/uv from nothing (2026-10-23): 455 completed runs, 1,595 REST
requests, 3.5 a run (one jobs read per run attempt, the artifact list, test report downloads, the odd second page).
With that rate and each repo's completed runs per day over the week before (GitHub's own count):

| Repo | Completed runs a day | CI Health's requests an hour | Share of the built-in token's limit |
|---|---|---|---|
| pytorch/pytorch | 2,500 | 366 | 37% |
| microsoft/vscode | 2,140 | 313 | 31% |
| home-assistant/core | 1,888 | 276 | 28% |

Even the busiest public repos leave most of the hour for Team Flow (every three hours), Community and the rest. The
run's own budget (`budget`, 800 a run) caps a single run; a run that hits it keeps what it read and the next continues.

## History growth

Bytes kept per CI run, gzipped as the data branch keeps them: 800 on pallets/click (94 runs, 12 records a run) and
1,000 on home-assistant/core (285 runs, 12 jobs a run). At 1,900 runs a day that is about 1.9 MB a day, so 180 days of
CI would be about 340 MB: over the 250 MB cap, which drops the oldest days first. A repo that busy keeps about four
months of CI history by default (flaky-test detection looks at the last 30 days); raise `size-cap-mb` or lower
`ci-retention-days` to choose. Most repos run under 100 runs a day and stay far below the cap.

## Reproduce

```
GH_TOKEN=... python bench/accuracy/platform/busy.py --sample astral-sh/uv --busy microsoft/vscode home-assistant/core pytorch/pytorch
```

Results: `busy-results.json`.
