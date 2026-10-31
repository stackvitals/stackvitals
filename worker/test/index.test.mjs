// node --test worker/test: signatures, what each event says, payloads per channel, and the whole request.
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { test } from "node:test";
import worker, { describe, payloadFor, plain, usualPickup, verify } from "../src/index.js";

const SECRET = "s3cret";
const sign = (body) => "sha256=" + createHmac("sha256", SECRET).update(body).digest("hex");
const repo = { full_name: "o/r" };

test("a body signed with the secret passes and anything else fails", async () => {
  const body = JSON.stringify({ zen: "ok" });
  assert.equal(await verify(SECRET, body, sign(body)), true);
  assert.equal(await verify(SECRET, body + " ", sign(body)), false);
  assert.equal(await verify(SECRET, body, "sha256=" + "0".repeat(64)), false);
  assert.equal(await verify(SECRET, body, null), false);
  assert.equal(await verify("", body, sign(body)), false);
});

test("text from GitHub never pings or links", () => {
  const out = plain("Fix <!channel> @everyone [x](http://evil) & more");
  assert.ok(!out.includes("<!") && !out.includes("@everyone") && !out.includes("](") && !out.includes("&"));
});

test("each event worth hearing says one plain sentence; the rest are ignored", () => {
  const pr = { number: 12, title: "Add cache", html_url: "https://github.com/o/r/pull/12", draft: false };
  const asked = describe("pull_request", { action: "review_requested", pull_request: pr, repository: repo,
    requested_reviewer: { login: "bob" } }, {}, "4.0 h");
  assert.match(asked.text, /Review requested on o\/r#12 "Add cache" \(this repo usually picks up reviews within 4.0 h\)/);
  assert.ok(!asked.text.includes("bob"));  // people are named only when the org opts in
  assert.match(describe("pull_request", { action: "review_requested", pull_request: pr, repository: repo,
    requested_reviewer: { login: "bob" } }, { NAME_PEOPLE: "true" }).text, /from bob/);
  assert.equal(describe("pull_request", { action: "review_requested", pull_request: { ...pr, draft: true }, repository: repo }), null);
  assert.equal(describe("pull_request_review", { action: "submitted", review: { state: "approved" }, pull_request: pr,
    repository: repo }).kind, "approved");
  const failed = describe("workflow_run", { action: "completed", repository: repo, workflow_run: { name: "CI",
    conclusion: "failure", run_attempt: 2, html_url: "https://github.com/o/r/actions/runs/9", pull_requests: [{ number: 12 }] } });
  assert.equal(failed.text, "CI failed on o/r pull request #12 (attempt 2).");
  assert.equal(describe("workflow_run", { action: "completed", repository: repo, workflow_run: { conclusion: "failure",
    pull_requests: [] } }), null);  // a push to main is CI Health's business, not a PR alert
  assert.equal(describe("check_suite", { action: "completed", repository: repo, check_suite: { conclusion: "failure",
    app: { slug: "github-actions" }, pull_requests: [{ number: 12 }] } }), null);
  assert.equal(describe("check_suite", { action: "completed", repository: repo, check_suite: { conclusion: "failure",
    app: { slug: "circleci", name: "CircleCI" }, pull_requests: [{ number: 12 }] } }).kind, "checks_failed");
  assert.equal(describe("issues", { action: "opened", repository: repo }), null);
});

test("payloads fit Slack, Discord, Teams and plain JSON", () => {
  const m = { kind: "approved", text: "o/r#12 is approved.", url: "https://github.com/o/r/pull/12" };
  assert.deepEqual(payloadFor("https://hooks.slack.com/services/x", m), { text: "o/r#12 is approved. https://github.com/o/r/pull/12" });
  assert.deepEqual(payloadFor("https://discord.com/api/webhooks/1/x", m).allowed_mentions, { parse: [] });
  assert.equal(payloadFor("https://x.logic.azure.com/workflows/1", m).attachments[0].content.type, "AdaptiveCard");
  assert.equal(payloadFor("https://example.com/hook", m).source, "stackvitals");
});

test("the usual pickup comes from the published Delivery file, or is left out", async () => {
  const ok = async () => ({ ok: true, json: async () => ({ phases: { pickup: { p50_h: 3.25 } } }) });
  assert.equal(await usualPickup("o/r", {}, ok), "3.3 h");
  assert.equal(await usualPickup("o/r", {}, async () => ({ ok: false })), null);
  assert.equal(await usualPickup("o/r", { READ_DELIVERY: "false" }, ok), null);
});

test("a signed webhook reaches every configured channel; an unsigned one is refused", async () => {
  const posted = [];
  const fake = async (url, init) => {
    if (url.startsWith("https://api.github.com/")) return { ok: false };
    posted.push([url, JSON.parse(init.body)]);
    return { ok: true };
  };
  const env = { GITHUB_WEBHOOK_SECRET: SECRET, SLACK_WEBHOOK_URL: "https://hooks.slack.com/services/x",
    DISCORD_WEBHOOK_URL: "https://discord.com/api/webhooks/1/x" };
  const body = JSON.stringify({ action: "completed", repository: repo, workflow_run: { name: "CI", conclusion: "failure",
    html_url: "https://github.com/o/r/actions/runs/9", pull_requests: [{ number: 12 }] } });
  const headers = { "X-GitHub-Event": "workflow_run", "X-Hub-Signature-256": sign(body) };
  const res = await worker.fetch(new Request("https://w.example/", { method: "POST", body, headers }), env, {}, fake);
  assert.equal(res.status, 200);
  assert.deepEqual(await res.json(), { kind: "checks_failed", sent: 2, channels: 2 });
  assert.equal(posted.length, 2);
  const bad = await worker.fetch(new Request("https://w.example/", { method: "POST", body,
    headers: { ...headers, "X-Hub-Signature-256": "sha256=00" } }), env, {}, fake);
  assert.equal(bad.status, 401);
  assert.equal(posted.length, 2);
});

test("a failed run whose failed jobs are all known flakes is skipped, or marked when asked", async () => {
  const { knownFlakyOnly } = await import("../src/index.js");
  const run = { id: 7, name: "CI", path: ".github/workflows/ci.yml", conclusion: "failure", run_attempt: 1,
    html_url: "https://github.com/o/r/actions/runs/7", pull_requests: [{ number: 3 }],
    jobs_url: "https://api.github.com/repos/o/r/actions/runs/7/jobs" };
  const data = { jobs: [{ workflow: ".github/workflows/ci.yml", job: "tests (3.12)", state: "flaky" },
                        { workflow: ".github/workflows/ci.yml", job: "lint", state: "ok" }] };
  const fake = (failed) => async (url) => {
    if (url.includes("data.json")) return new Response(JSON.stringify(data), { status: 200 });
    if (url.includes("/jobs")) return new Response(JSON.stringify({ jobs: failed.map((name) => ({ name, conclusion: "failure" }))
      .concat([{ name: "build", conclusion: "success" }]) }), { status: 200 });
    return new Response("{}", { status: 404 });
  };
  assert.equal(await knownFlakyOnly("o/r", run, {}, fake(["tests (3.12)"])), true);
  assert.equal(await knownFlakyOnly("o/r", run, {}, fake(["tests (3.12)", "lint"])), false);
  assert.equal(await knownFlakyOnly("o/r", run, { READ_DELIVERY: "false" }, fake(["tests (3.12)"])), false);

  const body = JSON.stringify({ action: "completed", workflow_run: run, repository: { full_name: "o/r" } });
  const sent = [];
  const fetchImpl = async (url, init) => {
    if (url.startsWith("https://hooks.slack.com")) { sent.push(JSON.parse(init.body)); return new Response("ok"); }
    return fake(["tests (3.12)"])(url);
  };
  const request = () => new Request("https://w.example", { method: "POST", body,
    headers: { "X-GitHub-Event": "workflow_run", "X-Hub-Signature-256": sign(body) } });
  const env = { GITHUB_WEBHOOK_SECRET: SECRET, SLACK_WEBHOOK_URL: "https://hooks.slack.com/x" };
  assert.equal((await worker.fetch(request(), env, {}, fetchImpl)).status, 202);
  assert.equal(sent.length, 0);
  await worker.fetch(request(), { ...env, KNOWN_FLAKES: "tell" }, {}, fetchImpl);
  assert.match(sent[0].text, /only known flaky jobs failed/);
});
