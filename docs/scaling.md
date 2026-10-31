# How StackVitals grows with you

StackVitals keeps each repo's history in that repo's own `stackvitals-data` branch. That branch is always the source of
truth: everything below is a view of it or a copy of it, and you can delete any copy and rebuild it from the branch.

## The ladder

1. **One repo, nothing to set up.** The Action writes the pages, the published JSON files and `summary/*.jsonl` (one row
   per pull request, CI job, test, and DevLake's tables) into the branch. Read them on Pages, in the job summary, with
   `stackvitals ui owner/repo` on your machine (private repos too), or with `stackvitals sql --repo owner/repo "..."`.
2. **SQL in the browser.** `docs/explore.html` runs DuckDB (WebAssembly) over the summaries, reading only the tables a
   query names. Measured on 2026-10-21 with a synthetic busy repo (20,648 pull requests, 23 MB of summaries): the first
   query took 2.8 to 3.2 s including starting DuckDB, DevLake's lead-time panel 0.6 s, later panels 0.2 s.
3. **Several repos, one query.** `stackvitals sql --repo org/web --repo org/api --repo org/worker "select repo,
   median(cycle_s) / 3600 from prs where merged_at is not null group by repo"`: each summary table becomes one view over
   all of them with a `repo` column. Portal covers the org's catalog and owners.
4. **A database, when a team wants one.** `stackvitals export owner/repo --format postgres` writes DevLake's tables as CSV
   and `postgres.sql`; `psql "$DATABASE_URL" -f postgres.sql` in that folder creates and loads them. Any Postgres works.

### When would the files be too big?

The summaries take about 1.2 KB per pull request (measured on pytest, aiohttp, pip and guidellm). With 400 days kept, a
repo merging 30 pull requests a day (12,000 in 400 days) has about 15 MB of summaries, the largest file about 7 MB. Explore and `stackvitals
sql` read them comfortably. A Parquet copy would be added only when one file passes 25 MB (about 40,000 pull requests
in 400 days) or the first query in Explore passes 3 s (about 20,000), a small fraction of a percent of repos. Until
then the Action needs no extra libraries.

### Busy repos

Estimated for public repos with 1,900 to 2,500 CI runs a day (pytorch, vscode, home-assistant), from the 3.5 requests a
run StackVitals' collector made on a full day of astral-sh/uv: CI Health alone needs 28% to 37% of the built-in token's
1,000 requests an hour, so it keeps up without a personal token. Repos with many more jobs a run need more. At about
1 KB stored a run (measured on click and home-assistant), their CI history grows by about 2 MB a day, so the 250 MB cap keeps about four months of it (the oldest days go first); raise `size-cap-mb` or
lower `ci-retention-days` to choose ([bench/accuracy/platform](../bench/accuracy/platform/README.md)).

## Actions minutes (private repos)

Public repos run on GitHub's free minutes. On a private repo every StackVitals job is billed, at least one minute each,
at GitHub's per-minute price for the runner. A small repo's job takes about a minute; a busy repo's, one to three.

What starts a job, by default:
- the schedule, 8 runs a day (Team Flow, Community, the CI catch-up);
- a CI run that **failed** (it gets its pull request comment at once); a CI run that passed starts nothing on a private
  repo, and the next scheduled run reads it;
- settings changes, request issues, `/stackvitals` commands, and pull requests that change a lockfile.

Jobs share one queue (`concurrency`), so a burst of finished CI runs collapses into one running job and one waiting (pull request checks and Test connection runs have their own, so they are never dropped behind it).

| CI runs a day | Failed (about 15%) | StackVitals minutes a day, roughly |
|---|---|---|
| 20 | 3 | 10-20 |
| 200 | 30 | 40-90 |
| 2,000 | 300 | 300-600 (the queue caps it: one job at a time) |

These are estimates from run counts, not measured bills. The verdict check needs every CI run, passing ones included,
to start a job: set the repository variable `STACKVITALS_EVERY_CI_RUN` to `true` (Settings, Secrets and variables,
Actions, Variables). That makes each row's job count six or seven times larger (every CI run instead of the failed 15%); the queue still caps the busiest repos at one job at a time. Turning modules off (`modules:`) shortens
each job.

## Free Postgres services (checked 2026-10-21; they change, so check before you rely on them)

| Service | Free tier | Watch out for |
|---|---|---|
| [Neon](https://neon.com/pricing) | 1 GB per project, 20 GB in all, 100 projects, 100 compute hours a project, no card | sleeps after 5 minutes idle (wakes on the next query) |
| [Prisma Postgres](https://www.prisma.io/pricing) | 2 GB, 50 databases, 200k operations a month, no card | counts operations |
| [Supabase](https://supabase.com/pricing) | 500 MB per project, 2 active projects | pauses after a week without use |
| [Aiven](https://aiven.io/pricing) | 1 GB storage, 1 CPU, 1 GB RAM | no choice of region; idle services may be shut down |
| [Nile](https://www.thenile.dev/pricing) | 1 GB, 50 million query tokens | metered by query tokens |
| Your own server | as big as you make it | you run it |

At about 1.2 KB a pull request, 1 GB holds roughly 800,000 pull requests: years of a large org.

## What stays the same at every step

- The Action only ever writes to the repo's own branch; nothing is sent to any service unless you load it there yourself.
- Every published number carries its sample size and the time it is from.
- Deleting a copy (a database, a local folder) loses nothing: `stackvitals ui` and the export rebuild it from the branch.
