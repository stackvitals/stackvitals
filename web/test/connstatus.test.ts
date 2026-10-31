// A connection's status from connectors.json, the repo's secret names and its settings: every pill the page shows.
import assert from "node:assert/strict";
import test from "node:test";
import { load } from "./load.mjs";

const m = await load("src/features/connstatus.ts");
const jira = { kind: "key", secrets: [{ name: "JIRA_EMAIL" }, { name: "JIRA_API_TOKEN" }] };
const chat = { kind: "key", secrets: [{ name: "STACKVITALS_WEBHOOK" }, { name: "STACKVITALS_TEAM_WEBHOOKS", optional: true }] };
const forum = { kind: "nokey" };
const pulled = { as_of: "2026-10-24T08:00:00Z", error: null, rows: { issue: 40 } };

test("built-in and local connections have fixed statuses", () => {
  assert.equal(m.statusOf({ kind: "builtin" }, null, null, false), "builtin");
  assert.equal(m.statusOf({ kind: "local" }, pulled, ["X"], true), "off");
});

test("nothing set up is available; a pull, a passing check or every secret is connected", () => {
  assert.equal(m.statusOf(jira, null, null, false), "off");
  assert.equal(m.statusOf(jira, null, [], false), "off");
  assert.equal(m.statusOf(jira, pulled, null, false), "connected");
  assert.equal(m.statusOf(chat, { check: { ok: true, checked_at: "2026-10-24T08:00:00Z" } }, null, false), "connected");
  assert.equal(m.statusOf(jira, null, ["JIRA_EMAIL", "JIRA_API_TOKEN"], false), "connected");
  assert.equal(m.statusOf(chat, null, ["stackvitals_webhook"], false), "connected");
});

test("a missing or expiring key needs a key", () => {
  assert.equal(m.statusOf(jira, null, ["JIRA_EMAIL"], false), "key");
  assert.equal(m.statusOf(jira, null, null, true), "key");
  assert.equal(m.statusOf(jira, { ...pulled, expiring: true, key_expires: "2026-11-01" }, null, false), "key");
});

test("a refused pull or a failed check that no later pull fixed is a failed check", () => {
  assert.equal(m.statusOf(jira, { ...pulled, error: "Jira refused the key" }, null, false), "failed");
  const failed = { ok: false, detail: "No Jira key is set.", checked_at: "2026-10-24T09:00:00Z" };
  assert.equal(m.statusOf(jira, { ...pulled, check: failed }, null, false), "failed");
  assert.equal(m.statusOf(jira, { ...pulled, as_of: "2026-10-24T10:00:00Z", check: failed }, null, false), "connected");
});

test("history read with a key the repo no longer has is recorded only", () => {
  assert.equal(m.statusOf(jira, pulled, ["OTHER"], false), "recorded");
  assert.equal(m.statusOf(jira, pulled, null, false), "connected");
});

test("a forum needs only its address", () => {
  assert.equal(m.statusOf(forum, null, [], false), "off");
  assert.equal(m.statusOf(forum, null, null, true), "connected");
});

test("buckets, newer checks and configured settings", () => {
  assert.equal(m.BUCKET.recorded, "attention");
  assert.equal(m.BUCKET.builtin, "on");
  const e = { check: { ok: true, checked_at: "2026-10-24T09:00:00Z" } };
  assert.equal(m.newerCheck(e, "2026-10-24T08:59:00Z")?.ok, true);
  assert.equal(m.newerCheck(e, "2026-10-24T09:00:00Z"), null);
  const defaults = { teams: [], incident_labels: ["incident"], key_expires: "", write_back: false };
  assert.equal(m.isConfigured({ teams: [], incident_labels: ["incident"], key_expires: "2027-01-01" }, defaults), false);
  assert.equal(m.isConfigured({ teams: ["ENG"], incident_labels: ["incident"] }, defaults), true);
});
