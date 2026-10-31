// The setup state machine against a fake GitHub: the happy path, a protected branch, dispatch retries, a failed run,
// private repos, resuming after a reload, and the unauthenticated watch.
import assert from "node:assert/strict";
import { test } from "node:test";
import { fromBase64, makeApi } from "../src/github/client";
import { lineDiff, diffText } from "../src/github/diff";
import { detect, suggest } from "../src/github/detect";
import { newRun, releaseLock, retry, runSetup, takeLock, type SetupRun, type Target } from "../src/github/setup";
import { check, watchSteps } from "../src/github/watch";
import { fakeGitHub, fakeStorage, type Handler } from "./fake";

const NOW = Date.parse("2026-10-24T12:00:00Z");
const YAML = "name: StackVitals\n";
const target = (over: Partial<Target> = {}): Target => ({ repo: "o/r", branch: "main", private: false, yaml: YAML, everyCiRun: false, pages: "public", ...over });
const deps = (fetchImpl: any, saved: SetupRun[] = []) => ({ api: makeApi("github_pat_test", fetchImpl), sleep: async () => {}, now: () => NOW, save: (r: SetupRun) => saved.push(r), tokenPage: "https://github.com/settings/personal-access-tokens/new" });
const status = (r: SetupRun) => Object.fromEntries(r.steps.map((s) => [s.id, s.status]));

// A run that is queued, then in progress, then done.
function runSeq(conclusion = "success"): Handler {
  let n = 0;
  return () => { n++; return [200, { id: 77, run_number: 1, html_url: "https://github.com/o/r/actions/runs/77", status: n < 2 ? "queued" : n < 3 ? "in_progress" : "completed", conclusion: n < 3 ? null : conclusion }]; };
}
const happy = (extra: Record<string, any> = {}) => ({
  "PUT /repos/o/r/contents/.github/workflows/stackvitals.yml": [201, { commit: { sha: "c1", html_url: "https://github.com/o/r/commit/1" } }],
  "GET /repos/o/r/actions/workflows/stackvitals.yml/runs": [200, { workflow_runs: [{ id: 77, head_sha: "c1", event: "push", status: "queued", created_at: "2026-10-24T12:00:05Z", html_url: "https://github.com/o/r/actions/runs/77" }] }],
  "GET /repos/o/r/actions/runs/77": runSeq(),
  "GET /repos/o/r/actions/runs/77/jobs": [200, { jobs: [{ name: "vitals", status: "in_progress", conclusion: null, steps: [{ name: "Set up job", status: "completed", conclusion: "success" }] }] }],
  "GET /repos/o/r/branches/stackvitals-data": [200, { name: "stackvitals-data" }],
  "POST /repos/o/r/pages": [201, { html_url: "https://o.github.io/r/" }],
  ...extra,
});

test("public repo: commit, the push's own run watched live, data branch, Pages on", async () => {
  const gh = fakeGitHub(happy());
  const seen: SetupRun[] = [];
  const done = await runSetup(newRun(target(), NOW), (r) => seen.push(r), deps(gh.fetchImpl));
  assert.deepEqual(status(done), { commit: "done", variable: "skipped", run: "done", data: "done", pages: "done" });
  assert.equal(done.finished, true);
  assert.equal(done.siteUrl, "https://o.github.io/r/");
  const put = gh.calls.find((c) => c.method === "PUT")!;
  assert.equal(fromBase64(put.body.content), YAML);
  assert.equal(put.body.branch, "main");
  assert.equal(put.body.sha, undefined);
  assert.deepEqual(gh.calls.find((c) => c.method === "POST" && c.path.endsWith("/pages"))!.body, { source: { branch: "stackvitals-data", path: "/docs" } });
  // No dispatch: committing the file already started a run.
  assert.ok(!gh.calls.some((c) => c.path.includes("/dispatches")));
  assert.ok(seen.some((r) => r.jobs?.[0]?.name === "vitals"));
  assert.ok(seen.some((r) => r.steps.find((s) => s.id === "run")!.note?.startsWith("Queued")));
});

test("a file that is already there isn't written again", async () => {
  const gh = fakeGitHub(happy({ "GET /repos/o/r/contents/.github/workflows/stackvitals.yml": [200, { sha: "abc", content: Buffer.from(YAML).toString("base64") }] }));
  const done = await runSetup(newRun(target(), NOW), () => {}, deps(gh.fetchImpl));
  assert.equal(done.steps[0]!.note, "The workflow file is already there.");
  assert.ok(!gh.calls.some((c) => c.method === "PUT"));
});

test("a different file is replaced in a direct commit only when that was confirmed", async () => {
  const gh = fakeGitHub(happy({ "GET /repos/o/r/contents/.github/workflows/stackvitals.yml": [200, { sha: "abc", content: Buffer.from("old").toString("base64") }] }));
  await runSetup(newRun(target({ replace: true }), NOW), () => {}, deps(gh.fetchImpl));
  const put = gh.calls.find((c) => c.method === "PUT")!;
  assert.equal(put.body.sha, "abc");
  assert.equal(put.body.branch, "main");
});

test("a different file already there gets a pull request by default, never a direct commit", async () => {
  const gh = fakeGitHub(happy({
    "GET /repos/o/r/contents/.github/workflows/stackvitals.yml": (_b: any, u: URL) => (u.searchParams.get("ref") === "main" ? [200, { sha: "abc", content: Buffer.from("old: custom\n").toString("base64") }] : [404, {}]),
    "GET /repos/o/r/git/ref/heads/main": [200, { object: { sha: "base1" } }],
    "POST /repos/o/r/git/refs": [201, {}],
    "GET /repos/o/r/pulls": [200, []],
    "POST /repos/o/r/pulls": [201, { number: 8, html_url: "https://github.com/o/r/pull/8" }],
  }));
  const done = await runSetup(newRun(target(), NOW), () => {}, deps(gh.fetchImpl));
  assert.equal(status(done).commit, "waiting");
  assert.match(done.steps[0]!.note!, /already there and differs/);
  assert.ok(gh.calls.filter((c) => c.method === "PUT").every((c) => c.body.branch === "stackvitals-setup"));
  assert.equal(gh.calls.find((c) => c.method === "POST" && c.path.endsWith("/pulls"))!.body.title, "Update StackVitals");
});

test("a 409 means the file changed since it was read: read again and retry once", async () => {
  let puts = 0;
  const gh = fakeGitHub(happy({
    "GET /repos/o/r/contents/.github/workflows/stackvitals.yml": () => [404, {}],
    "PUT /repos/o/r/contents/.github/workflows/stackvitals.yml": () => (++puts === 1 ? [409, { message: "is at abc but expected def" }] : [201, { commit: { sha: "c1" } }]),
  }));
  const done = await runSetup(newRun(target(), NOW), () => {}, deps(gh.fetchImpl));
  assert.equal(puts, 2);
  assert.equal(status(done).commit, "done");
  assert.ok(!gh.calls.some((c) => c.path.includes("/git/refs")));
});

test("a refused setup branch stops instead of carrying on", async () => {
  const gh = fakeGitHub({
    "PUT /repos/o/r/contents/.github/workflows/stackvitals.yml": [422, { message: "Repository rule violations found" }],
    "GET /repos/o/r/git/ref/heads/main": [200, { object: { sha: "base1" } }],
    "POST /repos/o/r/git/refs": [403, { message: "Resource not accessible" }],
  });
  const done = await runSetup(newRun(target(), NOW), () => {}, deps(gh.fetchImpl));
  assert.equal(status(done).commit, "failed");
  assert.ok(!gh.calls.some((c) => c.method === "POST" && c.path.endsWith("/pulls")));
});

test("a bad repo name writes nothing", async () => {
  const gh = fakeGitHub(happy());
  const done = await runSetup(newRun(target({ repo: "x/y/../../victim/z" }), NOW), () => {}, deps(gh.fetchImpl));
  assert.equal(status(done).commit, "failed");
  assert.equal(gh.calls.length, 0);
});

test("the push run is found by the new commit, not the browser clock", async () => {
  // The browser clock is an hour fast; the run of commit c1 is still ours, an older run of another commit isn't.
  const gh = fakeGitHub(happy({ "GET /repos/o/r/actions/workflows/stackvitals.yml/runs": [200, { workflow_runs: [
    { id: 70, head_sha: "old", event: "push", status: "completed", created_at: "2026-10-24T11:59:00Z", html_url: "x" },
    { id: 77, head_sha: "c1", event: "push", status: "queued", created_at: "2026-10-24T11:00:05Z", html_url: "u" }] }] }));
  const done = await runSetup(newRun(target(), NOW), () => {}, { ...deps(gh.fetchImpl), now: () => NOW + 3600000 });
  assert.equal(done.runId, 77);
  assert.ok(!gh.calls.some((c) => c.path.includes("/dispatches")));
});

test("a run already going is watched instead of dispatching a second one", async () => {
  const gh = fakeGitHub(happy({
    "GET /repos/o/r/contents/.github/workflows/stackvitals.yml": [200, { sha: "abc", content: Buffer.from(YAML).toString("base64") }],
    "GET /repos/o/r/actions/workflows/stackvitals.yml/runs": [200, { workflow_runs: [{ id: 77, head_sha: "zz", event: "schedule", status: "in_progress", created_at: "2026-10-24T11:00:00Z", html_url: "u" }] }],
  }));
  const done = await runSetup(newRun(target(), NOW), () => {}, deps(gh.fetchImpl));
  assert.equal(done.runId, 77);
  assert.ok(!gh.calls.some((c) => c.path.includes("/dispatches")));
});

test("one tab at a time: a second tab can't take the setup lock until it lapses", () => {
  const s = fakeStorage();
  assert.ok(takeLock("O/R", "tab1", NOW, s));
  assert.ok(!takeLock("o/r", "tab2", NOW + 1000, s));
  assert.ok(takeLock("o/r", "tab1", NOW + 2000, s));
  assert.ok(takeLock("o/r", "tab2", NOW + 200000, s));
  releaseLock("o/r", "tab2", s);
  assert.ok(takeLock("o/r", "tab3", NOW + 200001, s));
});

test("the line diff shows what would change", () => {
  const d = lineDiff("a\nb\nc\nd\ne\nf\ng", "a\nb\nC\nd\ne\nf\ng\nh");
  assert.deepEqual(d.filter((l) => l.op !== " ").map((l) => l.op + l.text), ["-c", "+C", "+h"]);
  assert.equal(diffText(lineDiff("1\n2\n3\n4\n5\n6\n7", "1\n2\n3\n4\n5\n6\nX"), 1), "  …\n  6\n- 7\n+ X");
});

test("setup's detection names the Pages source and the file already there", async () => {
  const gh = fakeGitHub({
    "GET /repos/o/r": [200, { full_name: "o/r", private: false, default_branch: "main", has_pages: true }],
    "GET /repos/o/r/actions/workflows": [200, { workflows: [{ path: ".github/workflows/stackvitals.yml", state: "active", name: "StackVitals" }] }],
    "GET /repos/o/r/pages": [200, { build_type: "legacy", source: { branch: "main", path: "/" } }],
    "GET /repos/o/r/contents/.github/workflows/stackvitals.yml": [200, { content: Buffer.from("old").toString("base64") }],
  });
  const d = (await detect(makeApi("t", gh.fetchImpl), "o/r"))!;
  assert.deepEqual(d.pages, { ours: false, says: "the main branch (/)" });
  assert.equal(d.existing, "old");
  const plan = suggest(d);
  assert.equal(plan.pagesSwitch, false);
  assert.equal(plan.replace, false);
  await assert.rejects(detect(makeApi("t", gh.fetchImpl), "x/y/../../victim/z"));
});

test("a protected branch gets a pull request, then Continue finishes once it is merged", async () => {
  let merged = false;
  const routes: Record<string, any> = happy({
    "PUT /repos/o/r/contents/.github/workflows/stackvitals.yml": (body: any) => body.branch === "main" ? [409, { message: "Changes must be made through a pull request." }] : [201, {}],
    "GET /repos/o/r/git/ref/heads/main": [200, { object: { sha: "base1" } }],
    "POST /repos/o/r/git/refs": [201, {}],
    "GET /repos/o/r/pulls": [200, []],
    "POST /repos/o/r/pulls": [201, { number: 5, html_url: "https://github.com/o/r/pull/5" }],
    "GET /repos/o/r/pulls/5": [200, { state: "open", merged: false }],
    "GET /repos/o/r/contents/.github/workflows/stackvitals.yml": (_b: any, u: URL) => (u.searchParams.get("ref") === "main" && merged ? [200, { sha: "m", content: Buffer.from(YAML).toString("base64") }] : [404, {}]),
  });
  const gh = fakeGitHub(routes);
  const first = await runSetup(newRun(target(), NOW), () => {}, deps(gh.fetchImpl));
  assert.equal(status(first).commit, "waiting");
  assert.deepEqual(first.pr, { number: 5, url: "https://github.com/o/r/pull/5" });
  assert.equal(gh.calls.find((c) => c.method === "POST" && c.path.endsWith("/git/refs"))!.body.ref, "refs/heads/stackvitals-setup");
  assert.equal(gh.calls.find((c) => c.method === "POST" && c.path.endsWith("/pulls"))!.body.base, "main");
  // Continue before the merge: still waiting, nothing new written.
  const writes = gh.writes().length;
  const again = await runSetup(retry(first, NOW), () => {}, deps(gh.fetchImpl));
  assert.equal(status(again).commit, "waiting");
  assert.equal(gh.writes().length, writes);
  merged = true;
  const done = await runSetup(retry(again, NOW), () => {}, deps(gh.fetchImpl));
  assert.deepEqual(status(done), { commit: "done", variable: "skipped", run: "done", data: "done", pages: "done" });
});

test("no push run: the workflow is dispatched, retrying while GitHub registers it", async () => {
  let tries = 0, dispatched = false;
  const gh = fakeGitHub(happy({
    "GET /repos/o/r/actions/workflows/stackvitals.yml/runs": () => [200, { workflow_runs: dispatched ? [{ id: 77, event: "workflow_dispatch", created_at: "2026-10-24T12:01:00Z", html_url: "u" }] : [] }],
    "POST /repos/o/r/actions/workflows/stackvitals.yml/dispatches": () => { tries++; if (tries < 3) return [404, { message: "Not Found" }]; dispatched = true; return [204, null]; },
  }));
  const done = await runSetup(newRun(target(), NOW), () => {}, deps(gh.fetchImpl));
  assert.equal(tries, 3);
  assert.equal(status(done).run, "done");
  assert.deepEqual(gh.calls.find((c) => c.path.includes("/dispatches"))!.body, { ref: "main" });
});

test("a failed run stops with the fix; Continue starts a fresh run", async () => {
  const routes: Record<string, any> = happy({ "GET /repos/o/r/actions/runs/77": runSeq("failure") });
  const gh = fakeGitHub(routes);
  const failed = await runSetup(newRun(target(), NOW), () => {}, deps(gh.fetchImpl));
  assert.equal(status(failed).run, "failed");
  assert.match(failed.steps.find((s) => s.id === "run")!.fix!, /summary names what to fix/);
  assert.equal(status(failed).data, "pending");
  const next = retry(failed, NOW + 60000);
  assert.equal(next.runId, undefined);
  assert.equal(status(next).run, "pending");
  assert.equal(status(next).commit, "done");
});

test("refusals name the permission and link to a new token", async () => {
  const gh = fakeGitHub({ "PUT /repos/o/r/contents/.github/workflows/stackvitals.yml": [403, { message: "Resource not accessible by personal access token" }] });
  const done = await runSetup(newRun(target(), NOW), () => {}, deps(gh.fetchImpl));
  const s = done.steps[0]!;
  assert.equal(s.status, "failed");
  assert.match(s.fix!, /Contents and Workflows/);
  assert.match(s.fixLink!, /personal-access-tokens/);
});

test("private repo: the variable is set (PATCH when it exists), Pages stays off", async () => {
  const gh = fakeGitHub(happy({
    "POST /repos/o/r/actions/variables": [409, { message: "Already exists" }],
    "PATCH /repos/o/r/actions/variables/STACKVITALS_EVERY_CI_RUN": [204, null],
  }));
  const done = await runSetup(newRun(target({ private: true, everyCiRun: true, pages: "local" }), NOW), () => {}, deps(gh.fetchImpl));
  assert.deepEqual(status(done), { commit: "done", variable: "done", run: "done", data: "done", pages: "skipped" });
  assert.ok(!gh.calls.some((c) => c.path.endsWith("/pages")));
  assert.deepEqual(gh.calls.find((c) => c.method === "PATCH")!.body, { name: "STACKVITALS_EVERY_CI_RUN", value: "true" });
});

test("a reload mid-run resumes watching the same run without writing again", async () => {
  const saved: SetupRun[] = [];
  const gh1 = fakeGitHub(happy({ "GET /repos/o/r/actions/runs/77": [200, { id: 77, run_number: 1, html_url: "u", status: "in_progress", conclusion: null }] }));
  // The first page gives up after its poll window, as if the tab had closed mid-run.
  await runSetup(newRun(target(), NOW), () => {}, { ...deps(gh1.fetchImpl, saved), maxPollMin: 0, now: (() => { let t = NOW; return () => (t += 1000); })() });
  const last = JSON.parse(JSON.stringify(saved[saved.length - 1]!)) as SetupRun;
  assert.equal(last.runId, 77);
  assert.equal(status(last).commit, "done");
  const gh2 = fakeGitHub(happy());
  const done = await runSetup(last, () => {}, deps(gh2.fetchImpl));
  assert.equal(done.finished, true);
  assert.ok(!gh2.calls.some((c) => c.method === "PUT"));
  assert.ok(!gh2.calls.some((c) => c.path.includes("/runs?")));
});

test("Pages already serving another source is kept unless switching was asked for", async () => {
  const routes: Record<string, any> = { "GET /repos/o/r/pages": [200, { source: { branch: "main", path: "/" }, html_url: "https://o.github.io/r/" }], "PUT /repos/o/r/pages": [204, null] };
  const gh = fakeGitHub(happy(routes));
  const kept = await runSetup(newRun(target(), NOW), () => {}, deps(gh.fetchImpl));
  assert.equal(status(kept).pages, "skipped");
  assert.match(kept.steps.find((s) => s.id === "pages")!.note!, /already serves the main branch \(\/\): kept/);
  assert.ok(!gh.calls.some((c) => c.method === "PUT" && c.path.endsWith("/pages")));
  assert.equal(kept.siteUrl, undefined);
  const gh2 = fakeGitHub(happy(routes));
  const switched = await runSetup(newRun(target({ pagesSwitch: true }), NOW), () => {}, deps(gh2.fetchImpl));
  assert.equal(status(switched).pages, "done");
  assert.deepEqual(gh2.calls.find((c) => c.method === "PUT" && c.path.endsWith("/pages"))!.body, { build_type: "legacy", source: { branch: "stackvitals-data", path: "/docs" } });
});

test("the unauthenticated watch asks only about the next step", async () => {
  const gh = fakeGitHub({
    "GET /repos/o/r": [200, { private: false, default_branch: "main", has_pages: false }],
    "GET /repos/o/r/actions/workflows": [200, { workflows: [] }],
  });
  const api = makeApi(null, gh.fetchImpl);
  const w1 = await check(api, "o/r");
  assert.deepEqual([w1.exists, w1.installed], [true, false]);
  assert.equal(gh.calls.length, 2);
  assert.deepEqual(watchSteps(w1).map((s) => s.state), ["now", "later", "later", "later"]);
  const gh2 = fakeGitHub({ "GET /repos/o/r/actions/workflows": [200, { workflows: [{ path: ".github/workflows/stackvitals.yml" }] }],
    "GET /repos/o/r/actions/workflows/stackvitals.yml/runs": [200, { workflow_runs: [{ id: 1, status: "in_progress" }] }] });
  const w2 = await check(makeApi(null, gh2.fetchImpl), "o/r", w1);
  assert.equal(gh2.calls.length, 2);  // the repo itself isn't asked again
  assert.deepEqual(watchSteps(w2).map((s) => s.state), ["done", "done", "now", "later"]);
});

test("a StackVitals workflow someone turned off is turned back on before the first run", async () => {
  let enabled = false;
  const gh = fakeGitHub(happy({
    "GET /repos/o/r/contents/.github/workflows/stackvitals.yml": [200, { sha: "abc", content: Buffer.from(YAML).toString("base64") }],
    "GET /repos/o/r/actions/workflows/stackvitals.yml": () => [200, { id: 9, state: enabled ? "active" : "disabled_manually" }],
    "PUT /repos/o/r/actions/workflows/stackvitals.yml/enable": () => { enabled = true; return [204, null]; },
    "GET /repos/o/r/actions/workflows/stackvitals.yml/runs": [200, { workflow_runs: [] }],
    "POST /repos/o/r/actions/workflows/stackvitals.yml/dispatches": () => (enabled ? [204, null] : [422, { message: "Cannot trigger a 'workflow_dispatch' on a disabled workflow" }]),
  }));
  const done = await runSetup(newRun(target(), NOW), () => {}, deps(gh.fetchImpl));
  assert.ok(gh.calls.some((c) => c.method === "PUT" && c.path.endsWith("/enable")));
  assert.match(done.steps.find((s) => s.id === "run")!.note || "", /turned (it|the workflow) back on|Turned/i);
});
