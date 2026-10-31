# The StackVitals app

Every run publishes one app over all the modules that ran: `https://OWNER.github.io/REPO/` once GitHub Pages serves the
`stackvitals-data` branch. For a private repo, `stackvitals ui owner/repo` opens the same app on `127.0.0.1` from a copy
of that branch. The app is `docs/index.html` plus `docs/app/` in the branch: Preact and TypeScript bundled ahead of
time, with its font, the docs for Help and the demo data inside. It loads no code from other sites (apart from the SQL
explorer, which fetches DuckDB once) and has no tracking. The bundled libraries and their licences are listed in
`app/LICENSES.md`.

## Opening it

| Address | What opens |
|---|---|
| `index.html` | The repo whose data sits beside the page (the usual Pages site) |
| `index.html?demo=1` | The demo: three example repos with full data, nothing to connect |
| `index.html?repo=owner/name` | A repo's `stackvitals-data` branch, read from GitHub |
| `index.html?pages=https://owner.github.io/name/` | Another repo's Pages site |
| `index.html?welcome` | The Welcome screen |


## Layout

The sidebar groups the pages: **Health** (Overview, Insights, CI Health, Pull Requests, Delivery, Community,
Dependencies), **Organisation** (Investment, Portal, Explore), **Team** (Activity, Data health, Settings) and **Install** (Setup,
Connections, Agents, Help, About). A badge shows what waits on a page, for example flaky tests or newcomers waiting. A
page for a module that isn't set up is dimmed. On a phone the sidebar becomes a tab bar (Overview, Insights, CI, PRs)
with the rest under **More**.

The top bar holds the repo switcher: the repos you follow, **Add a repository** (by name or Pages address), your GitHub
repos, the demo, reloading the data, and appearance (light, dark or auto).

## First run

Where no repo's data sits beside the page (the project site, or a fresh install), the app opens on **Welcome** with three
choices:

1. **Connect GitHub.** Lists your repos: ones that run StackVitals open their dashboard, the others go to Setup.
2. **Try the demo.** Three example repos with full data.
3. **Open a public repo.** Type `owner/repo`; the app reads its published data from its Pages site or data branch, or
   offers setup when it has none.

A returning visitor with a remembered connection goes straight to the last repo.

## Connecting GitHub

- **With a token.** The app opens GitHub's token page with the name, a 90-day expiry and the permissions filled in; you
  pick the repos and paste the token back. It is checked at once, and the app lists what it can and can't do in plain
  words. The token goes only to `api.github.com`. It stays in this tab by default; switch on **Remember on this device**
  to keep it across visits. **Sign out** forgets it.
- **Sign in with GitHub.** Shown only when the site was built with a sign-in relay (`worker/relay`). The app uses
  GitHub's sign-in with PKCE; the relay only swaps the one-time code (and later a refresh) for a token and keeps
  nothing. A signed-in token lasts 8 hours and is renewed shortly before.

## Setup in a few clicks

Once GitHub is connected, setup takes a few clicks; connecting takes one token, made from a prefilled GitHub page.
**Setup** picks a repo, checks what it has and suggests a plan (modules ticked from what it finds) that you can change.
**Set it up** then commits the workflow (a pull request when the branch is protected), starts the first run and shows it
live, waits for the data branch and turns on Pages for public repos. Each step is saved, so a reload picks up where it
stopped. Without a token you get the file ready to add on GitHub, the YAML to copy, or the one CLI command (`stackvitals init owner/repo`), and the app
checks for the first run at a pace that stays inside GitHub's limit for visitors.

## Pages

| Page | What it shows | What you can do there |
|---|---|---|
| Overview | Installation health, the state of each area, the trend you pick, what needs a decision, what to fix first and decisions ending soon | Open any item |
| Insights | Every finding ranked by the hours at stake, with its sample, evidence, age and decision; flaky tests traced to the pull requests they held red | Snooze or acknowledge; query it in Explore |
| CI Health | The first-try green share with the pushes that missed it, flaky and failing tests and jobs by cost, failure groups (each with a prompt to copy into an AI agent), slowest tests and jobs, new and skipped tests, coverage; a page per item with its flake rate, the runs that show it and the decision in force | Quarantine (tests), mute, acknowledge, reopen |
| Pull Requests | Who holds the next move on each open pull request, stuck ones, working-agreement exceptions | Filter to your handle; leave a pull request out of the numbers |
| Delivery | DORA tiles with tiers (each opens into the deployments, pull requests and incidents it was counted from), deployment rework rate, the phases of a change and their trend, AI-assisted work, issues and sprints with Jira or Linear, the merge queue | Open the pull requests behind each phase and each DORA number |
| Community | Newcomers waiting for an answer, bus factor (no names), first answers for newcomers against regulars, stars and traffic | |
| Dependencies | Vulnerabilities and malware in every lockfile the scanner reads, runtimes out of support, update pull requests by age, the supply chain from the SBOM | Accept a risk or a licence until a date |
| Investment | Where merged work went each month (feature, fix, maintenance, security, docs) and how each pull request was sorted | |
| Portal | (portal repos) every repo with its level, owners and links; failing rules; the catalog; campaigns; golden paths | Open a repo's own app |
| Explore | The tables behind every page, one row per pull request, job, test or deployment | Download any table; open the SQL explorer (`explore.html`, DuckDB in your browser) |
| Activity | Every decision and settings change: who, when, why, until when | Undo in one click |
| Data health | Each source (every step of the run, every connected service): current, filling in, failing since when and why, when it last worked, what it read; how far back each history goes against how long it is kept, and what retention or the size cap last removed | |
| Settings | Every setting in groups, with its default, the value in force and what a change would do | Change settings and send them |
| Setup | Setup in a few clicks (above) | |
| Connections | Everything StackVitals reads or sends (GitHub, Jira, Linear, chat webhooks, other CI systems, DevLake), grouped as connected, needs attention or available | Save a secret, change its settings, test it |
| Agents | Connecting a coding agent to the MCP server, one config per client; the tools by module, the skills | Copy the config or the install command |
| Help | The StackVitals docs, with search; links between docs stay in the app | |
| About | The path from GitHub to this page, where the data lives, how numbers are counted, how accurate each rule is, what each permission is for, how to remove it all | |

## Where a number comes from

The headline numbers open into what they were counted from: deployment frequency into the deployments, lead time into each deployed pull request with its time (longest first), change fail rate into the deployments and the revert, hotfix or incident issue tied to each, recovery into each failed deployment and its time to resolve, every review phase into its pull requests, and the first-try green share into the pushes that missed it, each linked to GitHub. The same lists are in `delivery.json` and `data.json` (`evidence`, `not_first_try`), and the MCP tools return them, so an agent can answer "why is lead time 26 hours?" with the pull requests. Long lists keep the longest or newest first and say the total. From a terminal: `stackvitals explain owner/repo lead-time` (or `deployments`, `change-failure`, `recovery`, `first-try`, or a review phase like `pickup`) prints the number, what it means and each item with its GitHub link; `--json` for all of them.

## Data health

Every run writes `health.json` beside the other files: for each step of the run and each connected service, when it
last worked, whether it is failing and since when (with what it said), whether it has finished reading its history
(**Filling in** while a big history is read a few hundred items a run, within GitHub's and the service's limits), and
what it read. It also lists how far back each kind of history goes against how long it is kept, and what retention or
the size cap last removed, so a gap in a chart has a reason. A failing source keeps its last good data and the next
run tries again; a source with no run for two days may mean the schedule stopped (GitHub pauses schedules in repos
with no activity for 60 days). Times and counts refresh with the next run that changes something, so a quiet run
never commits just to move a clock.

## Connections

Each connection opens a sheet with what it unlocks, the steps, its secrets and its settings. A secret you type is sealed
in your browser with the repo's own public key and only the sealed value goes to GitHub, the same way GitHub's own
settings page saves it; the app can list secret names but never read a value back. **Test connection** starts the
workflow's check and reads the result back from `connectors.json`. For Linear the app can also test the key straight
from the page; the key then goes only to `api.linear.app`.

## Making a decision

"Decide" on a test, job, finding or pull request asks what to do, for how long and why. Quarantine and mute last 30
days, snooze 14, an accepted risk 30, unless you pick another length or a date. Then pick how it reaches the repo:

1. **Open the request on GitHub** (the default). A prefilled issue opens; press Submit. The workflow checks you have
   triage access or more, records the decision, answers and closes the issue. No token is involved.
2. **Apply now** with your connected GitHub account or a pasted token with **Actions: read and write**: the app starts the
   workflow with the request and shows the run.
3. **Copy as a comment.** The command to paste in any issue or pull request comment, for example
   `/stackvitals mute test:<id> for 7d because <reason>`.

Decisions land in `decisions/log.ndjson` on the data branch and show in Activity. Issues from people without access
start no run.

## Changing settings

Edits collect in a save bar. **Review** lists each change (old to new); for alert thresholds it replays the last 90 days
and says how often the new value would have fired. With GitHub connected, one click commits `.github/stackvitals.toml`
(a pull request when the branch is protected) or runs the workflow with the request; workflow inputs are edited in the
workflow file the same way. Without a connection, open a prefilled issue or copy the TOML. Settings need write access.

## On this device

The app keeps your repo list, theme and GitHub handle in this browser only. A token stays in this tab unless you
ask to remember it on this device.

## For agents

`stackvitals propose owner/repo --set KEY=VALUE --decide "/stackvitals ..."` (MCP: `propose_change`) prints the same
prefilled request link, checked with the workflow's own parsers. A person opens it and presses Submit.
