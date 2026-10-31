# Quick start: your monitor in about five minutes

A GitHub repo is all you need; CI on GitHub Actions makes the CI part useful. Nothing has to be installed: the StackVitals app's Setup page checks your repo and, with a GitHub token, commits the workflow, starts the first run and turns on Pages (public repos only) in a few clicks once GitHub is connected; connecting takes one token, made from a prefilled GitHub page (without a token it opens GitHub with the file ready). From a terminal, [uv](https://docs.astral.sh/uv/) or pipx prints the same file. A public repo gets its monitor on GitHub Pages; a private repo works the same way, and you open its monitor on your machine or as a download instead (step 3), because Pages from a private repo is public on most plans.

## 1. Add the workflow

Print a workflow that already names your CI workflows, and save it in your repo:

```
uvx stackvitals ci init OWNER/REPO > .github/workflows/stackvitals.yml
```

It runs CI health, Team Flow, the dependency check and Community, and starts after the CI workflows it names (the ones that look like tests and builds; edit the list as you like). To install only some modules, print the file for them, for example `uvx stackvitals ci init OWNER/REPO --modules ci,deps`: it asks only for the permissions and triggers those modules use (the app's Setup page has the same choice). Every permission in the file has a comment saying what it is for. The whole file, what each module id needs and every input: [install.md](install.md).

## 2. Commit it

Commit the file to your default branch. That starts the first run by itself (it also runs after every CI run and every 3 hours). The first run reads up to 90 days of CI history and a year of pull requests; on a small repo it finished 55 seconds after the commit, and on a busy repo it may say "still filling in older history", and the next runs continue where it stopped. The supply chain part needs GitHub's dependency graph (on for public repos; for a private repo turn it on under Settings, Code security); until then the job says so once a week.

## 3. Turn on the dashboard

Open **Settings → Pages**. Under "Build and deployment", choose **Deploy from a branch**, branch `stackvitals-data`, folder `/docs`, and save. After a minute the dashboard is at:

```
https://OWNER.github.io/REPO/
```

That address opens the StackVitals app: Overview first, then a page per module, Settings (change any setting and save it with your GitHub token, or send it as an issue the workflow applies), Activity (every decision and change), Connections and Help. Add `?demo=1` to the address for three example repos; [app.md](app.md) walks through it. The module pages (`ci.html`, `flow.html`, ...) stay as printable views and work without JavaScript.

**A private repo:** skip Pages and run `pip install stackvitals` then `stackvitals ui OWNER/REPO` (it uses your `gh` login or `GITHUB_TOKEN` for one git command and keeps nothing). The same app opens on `127.0.0.1` in a few seconds.

**No install at all:** `stackvitals ui OWNER/REPO --collect` reads a repo's history on your machine (CI runs and pull requests, 90 days by default) into a local data branch and opens the app, with no Action, server, database or Docker. It only reads from GitHub: nothing is posted, labelled or committed there. On pallets/click the first read took 11 minutes.

## What next

- **Single flaky tests:** upload your test results (JUnit XML, CTRF, Jest or Vitest JSON, `go test -json`, .NET TRX) with `actions/upload-artifact` under a name containing `test-results`, `junit` or `ctrf`.
- **Opt-in automation:** turn switches on under `[automation]` in `.github/stackvitals.toml` (`rerun_flaky`, `issues`, `assign_owners`, `mention_owners`, `quarantine`, `preflight_comments`, `deps_comments`, `label_stuck`), or with the Action input of the same name written with hyphens (`rerun-flaky`; the file wins when both are set); [docs/settings.md](settings.md) lists every setting and the permission each needs. The `webhook` input takes a Slack, Discord, Teams or JSON URL.
- **Traffic history:** pass a token from your own GitHub App as `traffic-token:` (see [Community](modules.md#community)).
- **Your org:** Portal runs from a separate private repo (`stackvitals portal init`).
- **Agents:** `stackvitals serve` starts the MCP server; `stackvitals contribute brief OWNER/REPO` prints how changes get merged in a repo.
- **Busy repos:** GitHub Pages builds a branch about 10 times an hour at most. Past that, publish from the job instead: set `pages: deploy` on the Action, choose **GitHub Actions** as the Pages source, and give the job `pages: write`, `id-token: write` and `environment: github-pages`.

## If something goes wrong

- **"Resource not accessible by integration":** a permission is missing from the workflow file; the job summary names it.
- **No dashboard after enabling Pages:** check that the `stackvitals-data` branch exists (it is created by the first run) and that Pages points at its `/docs` folder.
- **Private repos:** GitHub Pages from a private repo is public on most plans, so set `pages: artifact` (each run that changed the app uploads it as a download kept 7 days; unzip it and follow its OPEN-ME.txt), or use `stackvitals ui OWNER/REPO` on your machine instead.
