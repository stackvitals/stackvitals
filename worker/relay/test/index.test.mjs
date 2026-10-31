// node --test worker/relay/test: CORS allowlist, PKCE and field checks, what reaches GitHub, and what comes back. No network.
import assert from "node:assert/strict";
import { test } from "node:test";
import relay, { validate } from "../src/index.js";

const APP = "https://app.example.org";
const env = { CLIENT_ID: "Iv1.abc", CLIENT_SECRET: "shh-secret", ALLOWED_ORIGINS: `${APP}, https://other.example.org/` };
const verifier = "v".repeat(43);
const good = { grant_type: "authorization_code", code: "c0de", code_verifier: verifier, redirect_uri: `${APP}/index.html` };

function post(body, origin = APP, path = "/token") {
  return new Request(`https://relay.example.workers.dev${path}`, { method: "POST", body: typeof body === "string" ? body : JSON.stringify(body),
    headers: { "Content-Type": "application/json", ...(origin ? { Origin: origin } : {}) } });
}
function github(reply = { access_token: "ghu_x", expires_in: 28800, refresh_token: "ghr_y", refresh_token_expires_in: 15811200, token_type: "bearer", scope: "" }, status = 200) {
  const calls = [];
  const impl = async (url, init) => { calls.push({ url, init }); return new Response(JSON.stringify(reply), { status, headers: { "Content-Type": "application/json" } }); };
  return { calls, impl };
}

test("a preflight from an allowed origin gets CORS headers; any other origin gets none", async () => {
  const ok = await relay.fetch(new Request("https://r/token", { method: "OPTIONS", headers: { Origin: APP } }), env);
  assert.equal(ok.status, 204);
  assert.equal(ok.headers.get("Access-Control-Allow-Origin"), APP);
  assert.equal(ok.headers.get("Vary"), "Origin");
  const bad = await relay.fetch(new Request("https://r/token", { method: "OPTIONS", headers: { Origin: "https://evil.example" } }), env);
  assert.equal(bad.status, 403);
  assert.equal(bad.headers.get("Access-Control-Allow-Origin"), null);
});

test("the code exchange adds the client id and secret and forwards only the checked fields", async () => {
  const gh = github();
  const res = await relay.fetch(post({ ...good, client_secret: "injected", extra: "x" }), env, {}, gh.impl);
  assert.equal(res.status, 200);
  assert.equal(res.headers.get("Access-Control-Allow-Origin"), APP);
  assert.equal(res.headers.get("Cache-Control"), "no-store");
  const body = await res.json();
  assert.deepEqual(Object.keys(body).sort(), ["access_token", "expires_in", "refresh_token", "refresh_token_expires_in", "scope", "token_type"]);
  assert.equal(gh.calls.length, 1);
  assert.equal(gh.calls[0].url, "https://github.com/login/oauth/access_token");
  const form = new URLSearchParams(gh.calls[0].init.body);
  assert.equal(form.get("client_secret"), "shh-secret");
  assert.equal(form.get("client_id"), "Iv1.abc");
  assert.equal(form.get("code_verifier"), verifier);
  assert.equal(form.get("extra"), null);
});

test("refresh passes the refresh token through", async () => {
  const gh = github();
  const res = await relay.fetch(post({ grant_type: "refresh_token", refresh_token: "ghr_y" }), env, {}, gh.impl);
  assert.equal(res.status, 200);
  const form = new URLSearchParams(gh.calls[0].init.body);
  assert.equal(form.get("grant_type"), "refresh_token");
  assert.equal(form.get("refresh_token"), "ghr_y");
});

test("unknown origins, missing PKCE, foreign redirects and odd grants never reach GitHub", async () => {
  const gh = github();
  assert.equal((await relay.fetch(post(good, "https://evil.example"), env, {}, gh.impl)).status, 403);
  assert.equal((await relay.fetch(post(good, null), env, {}, gh.impl)).status, 403);
  const nopkce = await relay.fetch(post({ ...good, code_verifier: undefined }), env, {}, gh.impl);
  assert.equal(nopkce.status, 400);
  assert.equal((await nopkce.json()).error, "pkce_required");
  assert.equal((await (await relay.fetch(post({ ...good, redirect_uri: "https://evil.example/cb" }), env, {}, gh.impl)).json()).error, "bad_redirect");
  assert.equal((await (await relay.fetch(post({ grant_type: "client_credentials" }), env, {}, gh.impl)).json()).error, "unsupported_grant_type");
  assert.equal((await relay.fetch(post("{not json"), env, {}, gh.impl)).status, 400);
  assert.equal((await relay.fetch(post("x".repeat(5000)), env, {}, gh.impl)).status, 413);
  assert.equal((await relay.fetch(new Request("https://r/token", { method: "GET", headers: { Origin: APP } }), env, {}, gh.impl)).status, 405);
  assert.equal(gh.calls.length, 0);
});

test("GitHub's errors come back as 400 with its words; its limits pass through without retries", async () => {
  const bad = github({ error: "bad_verification_code", error_description: "The code passed is incorrect or expired." });
  const res = await relay.fetch(post(good), env, {}, bad.impl);
  assert.equal(res.status, 400);
  assert.deepEqual(await res.json(), { error: "bad_verification_code", error_description: "The code passed is incorrect or expired." });
  const busy = github({}, 429);
  assert.equal((await relay.fetch(post(good), env, {}, busy.impl)).status, 429);
  assert.equal(busy.calls.length, 1);
});

test("a rate limit binding, when set, can turn callers away", async () => {
  const gh = github();
  const res = await relay.fetch(post(good), { ...env, LIMITER: { limit: async () => ({ success: false }) } }, {}, gh.impl);
  assert.equal(res.status, 429);
  assert.equal(gh.calls.length, 0);
});

test("without its settings the relay says so instead of calling GitHub", async () => {
  const gh = github();
  const res = await relay.fetch(post(good), { ALLOWED_ORIGINS: APP }, {}, gh.impl);
  assert.equal(res.status, 500);
  assert.equal(gh.calls.length, 0);
});

test("nothing is logged", async () => {
  const seen = [];
  const keep = { log: console.log, error: console.error, warn: console.warn, info: console.info };
  for (const k of Object.keys(keep)) console[k] = (...a) => seen.push(a);
  try {
    await relay.fetch(post(good), env, {}, github().impl);
    await relay.fetch(post({ ...good, code_verifier: "short" }), env, {}, github().impl);
  } finally { Object.assign(console, keep); }
  assert.deepEqual(seen, []);
});

test("validate accepts exactly the two grants", () => {
  assert.ok(validate(good, [APP]).form);
  assert.equal(validate(null, [APP]).error, "bad_request");
  assert.equal(validate({ ...good, code: "" }, [APP]).error, "bad_request");
});
