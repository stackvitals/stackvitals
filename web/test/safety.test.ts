// Safety checks: names from app.json or the address never steer a request elsewhere, logos and links from data stay inert,
// "remember" is off on shared github.io origins, sign-out forgets every token, and the signed-in token is renewed or dropped.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { makeApi } from "../src/github/client";
import { checkRepo, isRepo, isWorkflowFile } from "../src/github/names";
import { ACTION_REF } from "../src/github/workflow";
import { asLogo, STRATA } from "../src/brand/mark";
import { LOGOS } from "../src/brand/logos";
import { browserGlobals, fakeGitHub } from "./fake";
import { load } from "./load.mjs";

const root = process.env.SV_REPO_ROOT || join(process.cwd(), "..");
const EVIL = { repo: "x/y/../../victim/z", default_branch: "main", links: { workflow: "stackvitals.yml" } };
const EVIL_WF = { repo: "o/r", default_branch: "main", links: { workflow: "../../../../forks" } };

// Every fetch made while `fn` runs, so a test can say nothing was sent.
async function noFetch(fn: () => Promise<unknown>): Promise<string[]> {
  const seen: string[] = [];
  const old = globalThis.fetch;
  globalThis.fetch = (async (u: string) => { seen.push(String(u)); return new Response("{}", { status: 200 }); }) as typeof fetch;
  try { await assert.rejects(fn()); } finally { globalThis.fetch = old; }
  return seen;
}

test("repo and workflow names: owner/name only, no dot segments", () => {
  for (const ok of ["o/r", "my-org/my.repo", "a_b/c-d.e"]) assert.ok(isRepo(ok), ok);
  for (const bad of ["x/y/../../victim/z", "../x", "x/..", "./x", "o/r/", "o", "o/r?x=1", "o/r#a", "o /r", "", "o/r\n"]) assert.ok(!isRepo(bad), bad);
  assert.throws(() => checkRepo("x/y/../../victim/z"), /isn't a repo name/);
  assert.ok(isWorkflowFile("stackvitals.yml") && isWorkflowFile("ci.yaml"));
  for (const bad of ["../../../../forks", "a/b.yml", "..", "x.yml?y", "forks"]) assert.ok(!isWorkflowFile(bad), bad);
});

test("the client refuses a path with dot segments before sending the token", async () => {
  const gh = fakeGitHub({});
  const api = makeApi("github_pat_secret", gh.fetchImpl);
  await assert.rejects(api.call("GET", "/repos/x/y/../../victim/z"));
  await assert.rejects(api.call("PUT", "/repos/o/r/contents/%2e%2e/x"));
  await assert.rejects(api.call("GET", "/repos/o/r/actions/workflows/./x"));
  assert.equal(gh.calls.length, 0);
});

test("a malicious app.json can't steer settings, dispatches or secrets to another repo", async () => {
  browserGlobals();
  const sa = await load("src/features/settingsApply.ts");
  const sec = await load("src/features/secrets.ts");
  const wr = await load("src/data/write.ts");
  const gh = fakeGitHub({});
  const api = makeApi("github_pat_secret", gh.fetchImpl);
  await assert.rejects(sa.commitFile(EVIL, ".github/stackvitals.toml", (t: string) => t + "x", "settings", api), /isn't a repo name/);
  wr.setToken("github_pat_secret");
  assert.deepEqual(await noFetch(() => sa.dispatchRequest(EVIL_WF, { version: 1, changes: [], settings: {} })), []);
  assert.deepEqual(await noFetch(() => sa.dispatchRequest(EVIL, { version: 1, changes: [], settings: {} })), []);
  assert.deepEqual(await noFetch(() => sec.startCheck(EVIL_WF, "jira")), []);
  assert.deepEqual(await noFetch(() => sec.startCheck(EVIL, "jira")), []);
  assert.deepEqual(await noFetch(() => sec.saveSecret("x/y/../../victim/z", "KEY", "v")), []);
  assert.deepEqual(await noFetch(() => wr.dispatch(EVIL_WF, { version: 1, changes: [], settings: {} })), []);
  assert.deepEqual(await noFetch(() => wr.dispatch(EVIL, { version: 1, changes: [], settings: {} })), []);
  assert.equal(await sa.workflowText(EVIL_WF), null);
  assert.equal(gh.calls.length, 0);
  wr.setToken(null);
});

test("a data source with a bad owner or repo reads nothing", async () => {
  browserGlobals();
  const src = await load("src/data/source.ts");
  assert.deepEqual(await noFetch(async () => { if ((await src.fetchText({ kind: "branch", owner: "..", repo: "x", token: "t" }, "app.json")) === null) throw new Error("refused"); }), []);
  assert.equal(src.parseSource("../x"), null);
});

test("?repo= and ?pages= with odd values open nothing", async () => {
  for (const search of ["?repo=x/..", "?repo=../victim", "?repo=x/y/../../z", "?pages=javascript:alert(1)", "?pages=data:text/html,x"]) {
    browserGlobals();
    (globalThis as any).location.search = search;
    const { current } = await load("src/data/repos.ts");
    assert.equal(current.get().id, "here", search);
  }
  browserGlobals();
  (globalThis as any).location.search = "?repo=octo/hello.world";
  assert.equal((await load("src/data/repos.ts")).current.get().id, "branch:octo/hello.world");
});

test("a remembered logo is parsed against an allowlist", () => {
  const ok = { id: "x", name: "X", body: '<path d="M1 2L3 4" fill="none" stroke="F" stroke-width="2.6"/><circle cx="16" cy="16" r="4" fill="A" opacity=".5"/>' };
  assert.equal(asLogo(ok).body, ok.body);
  const bad = [
    '<path d="M1 2" style="x"/>', '<path d="M1 2"/><image href="x"/>', '<path d="M1 2" fill="url(javascript:x)"/>',
    '<path d="M1 2" onload="x"/>', '<rect x="1"></rect><script>1</script>', '<path d="M1 2" fill="a"b"/>', "<path d=\"M1\" fill='x'/>",
    '<path d="M1 2"/>text', '<foreignObject/>', '<path d="M1 2" xlink:href="#a"/>', '<path d="M1 2" fill="&#106;avascript"/>',
  ];
  for (const body of bad) assert.equal(asLogo({ id: "x", name: "X", body }), STRATA, body);
  for (const l of LOGOS) assert.equal(asLogo(l).body, l.body, l.id);
});

test("settings commit: a 409 re-reads and re-applies once; protection opens a pull request; a refused branch stops", async () => {
  browserGlobals();
  const sa = await load("src/features/settingsApply.ts");
  const app = { repo: "o/r", default_branch: "main" };
  let n = 0;
  const gh = fakeGitHub({
    "GET /repos/o/r": [200, { default_branch: "main" }], "GET /user": [200, { login: "me" }],
    "GET /repos/o/r/contents/.github/stackvitals.toml": () => [200, { sha: `s${n}`, content: Buffer.from(n ? "b = 2\n" : "a = 1\n").toString("base64") }],
    "PUT /repos/o/r/contents/.github/stackvitals.toml": () => (++n === 1 ? [409, { message: "sha does not match" }] : [200, { commit: { html_url: "u" } }]),
  });
  const out = await sa.commitFile(app, ".github/stackvitals.toml", (t: string) => t + "x = 3\n", "settings", makeApi("t", gh.fetchImpl));
  assert.equal(out.kind, "committed");
  const puts = gh.calls.filter((c) => c.method === "PUT");
  assert.equal(puts.length, 2);
  assert.equal(puts[1]!.body.sha, "s1");
  assert.equal(Buffer.from(puts[1]!.body.content, "base64").toString(), "b = 2\nx = 3\n");
  const prot = fakeGitHub({
    "GET /repos/o/r": [200, { default_branch: "main" }],
    "PUT /repos/o/r/contents/.github/stackvitals.toml": (b: any) => (b.branch === "main" ? [422, { message: "Changes must be made through a pull request." }] : [201, {}]),
    "GET /repos/o/r/git/ref/heads/main": [200, { object: { sha: "b1" } }],
    "POST /repos/o/r/git/refs": [403, { message: "nope" }],
  });
  await assert.rejects(sa.commitFile(app, ".github/stackvitals.toml", (t: string) => t + "x\n", "settings", makeApi("t", prot.fetchImpl)));
  assert.ok(!prot.calls.some((c) => c.path.endsWith("/pulls")));
  const plain403 = fakeGitHub({ "GET /repos/o/r": [200, { default_branch: "main" }], "PUT /repos/o/r/contents/.github/stackvitals.toml": [403, { message: "Resource not accessible" }] });
  await assert.rejects(sa.commitFile(app, ".github/stackvitals.toml", (t: string) => t + "x\n", "settings", makeApi("t", plain403.fetchImpl)), /isn't allowed/);
  assert.ok(!plain403.calls.some((c) => c.path.includes("/git/")));
});

// A fetch that sends api.github.com calls to a fake and serves connectors.json per Pages site.
function routeFetch(gh: ReturnType<typeof fakeGitHub>, sites: Record<string, () => unknown>) {
  globalThis.fetch = (async (u: string, init?: RequestInit) => {
    const url = String(u);
    if (url.startsWith("https://api.github.com/")) return gh.fetchImpl(url, init);
    const site = Object.keys(sites).find((s) => url.startsWith(s));
    return site ? new Response(JSON.stringify(sites[site]!()), { status: 200 }) : new Response("", { status: 404 });
  }) as typeof fetch;
}

test("a connection check keeps reading the repo it started on, and a replaced run says so", async () => {
  browserGlobals();
  const { m0: sec, m1: repos, m2: wr } = await load(["src/features/secrets.ts", "src/data/repos.ts", "src/data/write.ts"]);
  wr.setToken("github_pat_t");
  const A = "https://a.example/", B = "https://b.example/";
  repos.openRepo({ id: `pages:${A}`, label: "o/r", source: { kind: "pages", url: A } });
  const app = { repo: "o/r", default_branch: "main", links: { workflow: "stackvitals.yml" } };
  let reads = 0, conclusion: string | null = null;
  const gh = fakeGitHub({
    "POST /repos/o/r/actions/workflows/stackvitals.yml/dispatches": [204, null, { date: "Sat, 24 Oct 2026 12:00:00 GMT" }],
    "GET /repos/o/r/actions/workflows/stackvitals.yml/runs": [200, { workflow_runs: [{ id: 3, created_at: "2026-10-24T11:00:00Z" }, { id: 9, created_at: "2026-10-24T12:00:01Z" }] }],
    "GET /repos/o/r/actions/runs/9": () => [200, { status: conclusion ? "completed" : "in_progress", conclusion }],
  });
  const old = globalThis.fetch;
  try {
    routeFetch(gh, { [A]: () => (++reads < 2 ? { connectors: {} } : { connectors: { jira: { check: { ok: true, checked_at: "2026-10-24T12:01:00Z" } } } }),
      [B]: () => { throw new Error("read the other repo"); } });
    const started = await sec.startCheck(app, "jira");
    assert.equal(started.run, 9);
    repos.openRepo({ id: `pages:${B}`, label: "x/y", source: { kind: "pages", url: B } });
    const e = await sec.waitForCheck("jira", "2026-10-24T11:59:00Z", () => true, 0, 5);
    assert.equal(e?.check?.ok, true);
    // Cancelled by a newer StackVitals run: a plain message to test again.
    reads = -100; conclusion = "cancelled";
    await sec.startCheck(app, "jira");
    await assert.rejects(sec.waitForCheck("jira", "2026-10-24T11:59:00Z", () => true, 0, 5), /replaced by another StackVitals run/);
  } finally { globalThis.fetch = old; wr.setToken(null); }
});

test("links from data: only https, http, mailto, relative and hash", async () => {
  browserGlobals();
  const { safeHref } = await load("src/ui/Button.tsx");
  for (const ok of ["https://github.com/o/r", "http://x.example/", "mailto:a@b.c", "#/ci", "explore.html#sql=1", "../summary/x.html", "/docs/"]) assert.equal(safeHref(ok), ok, ok);
  for (const bad of ["javascript:alert(1)", " JavaScript:alert(1)", "data:text/html,x", "vbscript:x", "java\nscript:x", "//evil.example/x", "file:///etc/passwd"]) assert.equal(safeHref(bad), undefined, bad);
});

test("ACTION_REF matches the Python CLI", () => {
  const py = readFileSync(join(root, "src", "stackvitals", "ci", "cli.py"), "utf8");
  const m = py.match(/^ACTION_REF\s*=\s*"([^"]+)"/m);
  assert.ok(m, "ACTION_REF not found in ci/cli.py");
  assert.equal(ACTION_REF, m[1]);
});

test("on a github.io origin the account is kept for this tab only", async () => {
  const { local, session } = browserGlobals("someone.github.io");
  const tok = await load("src/github/token.ts");
  assert.equal(tok.canRemember(), false);
  tok.saveAccount({ token: "github_pat_x", kind: "fine", remember: true });
  assert.equal(local.getItem("sv:gh"), null);
  assert.ok(session.getItem("sv:gh"));
  assert.equal(tok.account.get().remember, false);
  const other = browserGlobals("stackvitals.example.com");
  const tok2 = await load("src/github/token.ts");
  assert.equal(tok2.canRemember(), true);
  tok2.saveAccount({ token: "github_pat_x", kind: "fine", remember: true });
  assert.ok(other.local.getItem("sv:gh"));
});

test("sign-out forgets every token: account, pasted, per-repo, setup state and the open repo's", async () => {
  const { local, session } = browserGlobals();
  local.setItem("sv:gh", JSON.stringify({ token: "github_pat_dev", kind: "fine", remember: true }));
  local.setItem("sv:repos", JSON.stringify([{ id: "branch:o/p", label: "o/p", source: { kind: "branch", owner: "o", repo: "p" }, private: true }]));
  local.setItem("sv:current", JSON.stringify("branch:o/p"));
  session.setItem("sv:tokens", JSON.stringify({ "branch:o/p": "github_pat_repo" }));
  session.setItem("sv:setup:o/p", "{}");
  session.setItem("sv:token", "github_pat_pasted");
  const { m0: tok, m1: wr, m2: repos } = await load(["src/github/token.ts", "src/data/write.ts", "src/data/repos.ts", "src/github/session.ts"]);
  assert.equal(repos.current.get().source.token, "github_pat_repo");
  wr.setToken("github_pat_memory");
  tok.signOut();
  assert.equal(tok.account.get(), null);
  assert.equal(wr.token(), null);
  for (const k of ["sv:gh", "sv:tokens", "sv:setup:o/p", "sv:token"]) { assert.equal(session.getItem(k), null, k); assert.equal(local.getItem(k), null, k); }
  assert.equal(repos.current.get().source.token, undefined);
  assert.ok(repos.repos.get().every((e: any) => !e.source.token));
  assert.ok(!JSON.stringify([...Array(local.length).keys()].map((i) => local.getItem(local.key(i)!))).includes("github_pat_"));
});

test("a signed-in token near its expiry is renewed and saved; a failed renewal signs out plainly", async () => {
  const { session } = browserGlobals();
  const now = Date.now();
  session.setItem("sv:gh", JSON.stringify({ token: "ghu_old", kind: "app", expires: now + 60000, refresh: "ghr_r", login: "me" }));
  session.setItem("sv:tokens", JSON.stringify({ "branch:o/p": "ghu_old" }));
  const { m0: ses, m1: tok, m2: repos } = await load(["src/github/session.ts", "src/github/token.ts", "src/data/repos.ts"]);
  repos.openRepo({ id: "branch:o/p", label: "o/p", source: { kind: "branch", owner: "o", repo: "p", token: "ghu_old" }, private: true });
  const cfg = { relay: "https://relay.example", clientId: "c" };
  const relay = async () => new Response(JSON.stringify({ access_token: "ghu_new", expires_in: 28800, refresh_token: "ghr_n" }), { status: 200 });
  const said: string[] = [];
  const a = await ses.freshAccount({ cfg, fetchImpl: relay, say: (m: string) => said.push(m) });
  assert.equal(a.token, "ghu_new");
  assert.equal(tok.account.get().token, "ghu_new");
  assert.equal(JSON.parse(session.getItem("sv:gh")!).token, "ghu_new");
  assert.equal(repos.current.get().source.token, "ghu_new");
  // Not due: nothing is asked.
  let asked = 0;
  assert.equal((await ses.freshAccount({ cfg, fetchImpl: async () => { asked++; return relay(); } })).token, "ghu_new");
  assert.equal(asked, 0);
  // Due and the relay refuses: signed out with a plain message.
  tok.saveAccount({ ...tok.account.get(), expires: Date.now() - 1000 });
  const gone = await ses.freshAccount({ cfg, fetchImpl: async () => new Response(JSON.stringify({ error: "bad_refresh_token" }), { status: 400 }), say: (m: string) => said.push(m) });
  assert.equal(gone, null);
  assert.equal(tok.account.get(), null);
  assert.match(said.at(-1)!, /sign in again/i);
  assert.equal(said.length, 1);
});

test("data links on the CI evidence and bug tables go through safeHref", () => {
  // Audit finding (2026-10-31): these two took a URL from data straight into href.
  const ci = readFileSync(join(root, "web", "src", "pages", "ci.tsx"), "utf8");
  const bugs = readFileSync(join(root, "web", "src", "pages", "delivery", "more.tsx"), "utf8");
  assert.match(ci, /<a href=\{safeHref\(r\.url\)\}/);
  assert.match(bugs, /<a href=\{safeHref\(x\.url\)\}/);
  assert.doesNotMatch(ci + bugs, /href=\{(r|x)\.url\}/);
});

test("the add-repo example is a neutral public name, not a personal sandbox", () => {
  const add = readFileSync(join(root, "web", "src", "app", "AddRepo.tsx"), "utf8");
  assert.match(add, /For example octo-org\/octo-repo/);
  assert.doesNotMatch(add, /kaushik-yadav/);
});
