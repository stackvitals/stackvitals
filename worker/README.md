# StackVitals instant alerts (Cloudflare Worker)

(The app's optional "Sign in with GitHub" relay is a separate Worker in [`relay/`](relay/README.md).)

The StackVitals Action runs on a schedule, so its alerts come every few hours. This small Worker gives you the
in-the-moment ones, within seconds of the GitHub event:

- a pull request's checks failed (GitHub Actions, or any other CI that reports a check suite),
- a review was requested on a pull request (with the repo's usual pickup time when it runs StackVitals),
- a pull request was approved and is ready to merge.

It posts to Slack, Discord, Microsoft Teams (a Workflows webhook) or any JSON webhook. Each org deploys its own copy to
its own free Cloudflare account (100,000 requests a day, no card needed), so no event leaves your accounts except to
your chat. It checks GitHub's signature on every request and refuses anything unsigned. People are not named unless you
turn that on, and titles from pull requests can never ping a channel or form a link.

## Set it up (about 10 minutes)

1. **Deploy the Worker.** Either:
   - **No install:** in the Cloudflare dashboard, Workers & Pages, Create, Start with Hello World, Deploy; then Edit
     code, replace everything with [`src/index.js`](src/index.js), and Deploy again. Or
   - **From a terminal:** in this folder, `npx wrangler login` and `npx wrangler deploy`.

   Note the address it gets, like `https://stackvitals-alerts.<you>.workers.dev`.
2. **Add its settings** (dashboard: the Worker, Settings, Variables and Secrets; terminal: `npx wrangler secret put NAME`):
   - `GITHUB_WEBHOOK_SECRET`: any long random string (keep it for step 3).
   - At least one of `SLACK_WEBHOOK_URL`, `DISCORD_WEBHOOK_URL`, `TEAMS_WEBHOOK_URL` (Teams: a "Post to a channel when a
     webhook request is received" workflow) or `JSON_WEBHOOK_URL`.
   - Optional: `NAME_PEOPLE` = `true` to name the requested reviewer; `GITHUB_TOKEN`, a read-only token, only if your
     repos are private and you want the usual pickup time in review messages (and the flaky-job check below).
   - Failed runs where every failed job is one CI Health already knows as flaky send nothing (they are noise);
     `KNOWN_FLAKES` = `tell` sends them marked "only known flaky jobs failed", `off` turns the check off.
3. **Point GitHub at it:** your org's (or one repo's) Settings, Webhooks, Add webhook. Payload URL: the Worker's address.
   Content type: `application/json`. Secret: the same string. Events: *Pull requests*, *Pull request reviews*,
   *Workflow runs* and *Check suites*.
4. **Check it:** GitHub sends a ping right away (the Worker answers 202). Redeliver a recent "workflow_run" from the
   webhook's Recent Deliveries tab to see a message arrive.

## Test it locally

`node --test test/index.test.mjs` (Node 20 or newer; nothing to install).
