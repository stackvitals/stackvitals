# Portal: how light the core is

The Portal promises to stay light: no server, one daily run, and an org that fits the built-in token (1,000 requests an
hour). This folder measures that, before and after the 2026-10-23 speed changes, on the same public orgs.

## Requests and time (`speed.py`)

A full catalog run on two public orgs, cold (nothing kept) and then warm (the next day's run, with what the data branch
keeps), public mode, Scorecard lookups off. Counted requests are the ones GitHub charges to the hourly limit; a
conditional read GitHub answers "unchanged" costs nothing.

| | pallets, before | pallets, after | psf, before | psf, after |
|---|---|---|---|---|
| Repos checked | 10 | 10 | 38 | 38 |
| REST requests, cold | 100 (10 a repo) | 40 (4 a repo) | 371 (9.8 a repo) | 149 (3.9 a repo) |
| Counted against the limit, warm | 100 | 28 | 371 | 104 (2.7 a repo) |
| Seconds, cold | 64 | 14 | 1,519 | 49 |
| Seconds, warm | 62 | 11 | 208 | 47 |
| GraphQL points | 10 | 12 | 38 | 42 |
| Repos that failed | 0 | 0 | 0 | 0 |

What changed:

- **One GraphQL query reads ten repos' files** (CODEOWNERS, catalog-info.yaml, the rule files, the community files
  GitHub resolves, the docs folder and the suite's facts on the data branch) where each was a REST request per repo.
  On 13 repos of two orgs (pallets, astral-sh), every reader gave the same answer from the batch as from REST.
- **Repos are checked six at a time**, one at a time near the end of the request budget so the repos checked longest
  ago still go first. psf's runs fell from 25 minutes cold and 3.5 minutes warm to under a minute each (the before
  run's cold time varied with GitHub's response times; even its warm run was four times slower).
- **Small answers that rarely change are read conditionally** and kept in the data branch (`portal/etags.json`); the
  push CI read reuses yesterday's numbers when no run happened since.

A run with the built-in token keeps 700 counted requests for the catalog (unchanged answers don't count against it):
about 180 repos on the first run (3.9 a repo) and up to about 260 on later ones (2.7 a repo), against 70 before. The
warm runs here came minutes after the cold ones, so they are the best case: a real next-day run sees more changes. A
bigger org fills in over consecutive runs, oldest first, or uses the org App (4,000 a run).

## Scale (`scale.py`)

A synthetic org of 10,000 repos shaped like real catalog entries, through everything after the reads (its entries
are simpler than real ones, so they compress better: the real-entry estimate is the one to use for download size):

| Step | Time | Size |
|---|---|---|
| Scoring every repo | 0.3 s | |
| The catalog file in the data branch | 2.2 s | 24.3 MB (17.5 MB compact) |
| The app's copy, packed (each rule and evidence line named once) | | 8.5 MB, 0.35 MB gzip |
| The same, estimated from a real org's entries (psf's 44, scaled to 10,000) | | 8.4 MB, 1.0 MB gzip |
| The Markdown page | 0.2 s | 0.8 MB |
| The printable HTML page | 0.1 s | 1.3 MB |
| Backstage entities.yaml | 6.2 s | 2.6 MB |

## Reproduce

```
GH_TOKEN=... python bench/accuracy/portal/speed.py --label after pallets psf
python bench/accuracy/portal/scale.py --repos 10000
```

Results: `speed-before.json` (measured on the code before those changes), `speed-after.json`, `scale-results.json`.
