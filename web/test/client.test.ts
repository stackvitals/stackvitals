// The GitHub client and token checks: the token goes only to api.github.com, limits and refusals read plainly.
import assert from "node:assert/strict";
import { test } from "node:test";
import { inspect, kindOf, tokenPageUrl, TOKEN_RE } from "../src/github/caps";
import { fromBase64, makeApi, paged, toBase64 } from "../src/github/client";
import { groupRepos, type GhRepo } from "../src/github/mine";
import { detect, suggest } from "../src/github/detect";
import { fakeGitHub } from "./fake";

test("every call goes to api.github.com, with the token only when there is one", async () => {
  const gh = fakeGitHub({ "GET /user": [200, { login: "me" }] });
  await makeApi("github_pat_abc", gh.fetchImpl).get("/user");
  await makeApi(null, gh.fetchImpl).get("/user");
  assert.ok(gh.calls.every((c) => c.url.startsWith("https://api.github.com/")));
  assert.equal(gh.calls[0]!.auth, "Bearer github_pat_abc");
  assert.equal(gh.calls[1]!.auth, null);
  await assert.rejects(makeApi("t", gh.fetchImpl).call("GET", "https://evil.example/x"));
});

test("404 is null; limits, refusals and outages are plain errors", async () => {
  const gh = fakeGitHub({
    "GET /limited": [403, { message: "API rate limit exceeded" }, { "x-ratelimit-remaining": "0" }],
    "GET /refused": [401, { message: "Bad credentials" }],
    "GET /forbidden": [403, { message: "Resource not accessible by personal access token" }],
  });
  const api = makeApi(null, gh.fetchImpl);
  assert.equal(await api.get("/missing"), null);
  await assert.rejects(api.get("/limited"), (e: any) => e.limited && /60 requests an hour/.test(e.message));
  await assert.rejects(makeApi("t", gh.fetchImpl).get("/refused"), /expired, revoked or mistyped/);
  await assert.rejects(makeApi("t", gh.fetchImpl).get("/forbidden"), /isn't allowed/);
  await assert.rejects(makeApi("t", async () => { throw new Error("offline"); }).get("/x"), /didn't answer/);
});

test("lists are read page by page until a short page", async () => {
  const gh = fakeGitHub({ "GET /user/repos": (_b, u) => [200, u.searchParams.get("page") === "1" ? Array(100).fill({}) : Array(7).fill({})] });
  assert.equal((await paged(makeApi("t", gh.fetchImpl), "/user/repos?sort=pushed")).length, 107);
  assert.equal(gh.calls.length, 2);
});

test("base64 round-trips UTF-8", () => {
  const s = "name: Déploiement 🚀\n";
  assert.equal(fromBase64(toBase64(s)), s);
});

test("the token link asks for every permission setup needs, and pasted tokens are recognised", () => {
  const u = new URL(tokenPageUrl());
  assert.equal(u.origin + u.pathname, "https://github.com/settings/personal-access-tokens/new");
  assert.equal(u.searchParams.get("name"), "StackVitals");
  assert.equal(u.searchParams.get("expires_in"), "90");
  for (const p of ["contents", "workflows", "pull_requests", "actions", "secrets", "variables", "pages", "administration"]) assert.equal(u.searchParams.get(p), "write", p);
  assert.equal(" github_pat_11ABCDEFG0123456789_abcdefghijklmnopqrstuvwxyzABCDEFGHIJ ".match(TOKEN_RE)?.[1]?.startsWith("github_pat_"), true);
  assert.equal(TOKEN_RE.test("ghp_" + "a".repeat(36)), true);
  assert.equal(TOKEN_RE.test("hello"), false);
  assert.deepEqual(["github_pat_x", "ghp_x", "ghu_x", "gho_x"].map(kindOf), ["fine", "classic", "app", "oauth"]);
});

test("a fine-grained token: missing permissions are found with read-only probes on a private repo", async () => {
  const gh = fakeGitHub({
    "GET /user": [200, { login: "me", avatar_url: "https://avatars.githubusercontent.com/u/1" }],
    "GET /user/repos": [200, [{ full_name: "me/pub", private: false }, { full_name: "me/priv", private: true }]],
    "GET /repos/me/priv/contents/": [200, []],
    "GET /repos/me/priv/actions/workflows": [200, { workflows: [] }],
    "GET /repos/me/priv/pulls": [200, []],
    "GET /repos/me/priv/actions/variables": [403, { message: "Resource not accessible by personal access token" }],
    "GET /repos/me/priv/actions/secrets/public-key": [200, {}],
    "GET /repos/me/priv/actions/permissions": [403, {}],
  });
  const info = await inspect(makeApi("github_pat_x", gh.fetchImpl), "github_pat_x");
  assert.equal(info.login, "me");
  assert.equal(info.probe, "me/priv");
  assert.equal(info.repos, 2);
  assert.deepEqual(info.missing.map((m) => m.id), ["variables", "administration"]);
  assert.equal(info.checks.find((c) => c.id === "pages")!.ok, true);  // 404: no site yet, but allowed to ask
  assert.equal(info.checks.find((c) => c.id === "workflows")!.ok, null);
  assert.ok(gh.calls.every((c) => c.method === "GET"));
});

test("a classic token is read from its scopes; a refused one says so", async () => {
  const gh = fakeGitHub({ "GET /user": [200, { login: "me" }, { "x-oauth-scopes": "repo, read:org" }] });
  const info = await inspect(makeApi("ghp_x", gh.fetchImpl), "ghp_x");
  assert.deepEqual(info.missing.map((m) => m.id), ["workflows"]);
  const bad = fakeGitHub({ "GET /user": [401, { message: "Bad credentials" }] });
  await assert.rejects(inspect(makeApi("ghp_x", bad.fetchImpl), "ghp_x"), /refused the token/);
});

test("repos group by owner with the account first, and search filters them", () => {
  const r = (full: string): GhRepo => ({ full_name: full, owner: full.split("/")[0]!, name: full.split("/")[1]!, private: false, default_branch: "main", pushed_at: null, archived: false, description: null });
  const list = [r("acme/api"), r("me/site"), r("acme/web"), r("zed/x")];
  assert.deepEqual(groupRepos(list, "", "me").map(([o, l]) => [o, l.length]), [["me", 1], ["acme", 2], ["zed", 1]]);
  assert.deepEqual(groupRepos(list, "WEB", "me").map(([o]) => o), ["acme"]);
});

test("detection suggests modules from what the repo has", async () => {
  const gh = fakeGitHub({
    "GET /repos/o/r": [200, { full_name: "o/r", private: false, default_branch: "trunk", has_pages: false, permissions: { push: true } }],
    "GET /repos/o/r/actions/workflows": [200, { workflows: [{ name: "Tests", path: ".github/workflows/t.yml", state: "active" }, { name: "Release", path: ".github/workflows/r.yml", state: "active" },
      { name: "StackVitals", path: ".github/workflows/stackvitals.yml", state: "active" }] }],
    "GET /repos/o/r/deployments": [200, []],
    "GET /repos/o/r/releases": [200, [{ id: 1 }]],
    "GET /repos/o/r/contents/": [200, [{ type: "file", name: "uv.lock" }, { type: "file", name: "README.md" }]],
  });
  const d = (await detect(makeApi(null, gh.fetchImpl), "o/r"))!;
  assert.equal(d.branch, "trunk");
  assert.deepEqual(d.workflows, ["Tests", "Release"]);
  assert.deepEqual(d.ciNames, ["Tests"]);
  assert.equal(d.installed, true);
  assert.equal(d.dataBranch, false);
  assert.deepEqual(d.lockfiles, ["uv.lock"]);
  assert.deepEqual(suggest(d), { modules: ["ci", "flow", "deps", "community"], names: ["Tests"], days: 90, budget: 800, pages: "public", everyCiRun: false, pagesSwitch: false, replace: false });
  assert.deepEqual(suggest({ ...d, private: true, lockfiles: [] }).modules, ["ci", "flow"]);
  assert.equal(suggest({ ...d, private: true }).pages, "local");
  assert.equal(gh.calls.length, 7);  // six, plus the installed file for the diff
  assert.equal(await detect(makeApi(null, fakeGitHub({}).fetchImpl), "o/missing"), null);
});
