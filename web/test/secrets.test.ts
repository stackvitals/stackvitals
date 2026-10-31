// The sealed box GitHub's secrets API takes: what the app seals opens with an independent libsodium-style open
// (tweetnacl's fast build plus BLAKE2b nonce) for a fresh keypair, and nothing else can open it.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";
import { load, web } from "./load.mjs";

const require = createRequire(web + "/package.json");
const nacl = require("tweetnacl");
const { blake2b } = require("blakejs");

// crypto_box_seal_open: nonce = BLAKE2b-192(ephemeral pk || recipient pk), then crypto_box_open.
function sealOpen(sealed, pk, sk) {
  const epk = sealed.subarray(0, 32);
  const nonce = blake2b(new Uint8Array([...epk, ...pk]), null, 24);
  return nacl.box.open(sealed.subarray(32), nonce, epk, sk);
}

const b64 = (bytes) => Buffer.from(bytes).toString("base64");

test("a sealed secret opens with the repo's private key and holds the exact value", async () => {
  const { sealFor } = await load("src/features/secrets.ts");
  const keys = nacl.box.keyPair();
  const value = "xoxb-1234-ünïcode\nsecond line";
  const sealed = Buffer.from(await sealFor(b64(keys.publicKey), value), "base64");
  assert.equal(sealed.length, 32 + 16 + Buffer.byteLength(value));
  const opened = sealOpen(new Uint8Array(sealed), keys.publicKey, keys.secretKey);
  assert.ok(opened, "the sealed box should open");
  assert.equal(new TextDecoder().decode(opened), value);
});

test("each seal uses a new ephemeral key, and another key can't open it", async () => {
  const { sealFor } = await load("src/features/secrets.ts");
  const keys = nacl.box.keyPair(), other = nacl.box.keyPair();
  const a = Buffer.from(await sealFor(b64(keys.publicKey), "same"), "base64");
  const b = Buffer.from(await sealFor(b64(keys.publicKey), "same"), "base64");
  assert.notDeepEqual(a, b);
  assert.equal(sealOpen(new Uint8Array(a), other.publicKey, other.secretKey), null);
});

test("secret names follow GitHub's rule", async () => {
  const { SECRET_RE } = await load("src/features/secrets.ts");
  assert.ok(SECRET_RE.test("JIRA_API_TOKEN"));
  assert.ok(!SECRET_RE.test("GITHUB_TOKEN"));
  assert.ok(!SECRET_RE.test("1KEY"));
  assert.ok(!SECRET_RE.test("github_x") && !SECRET_RE.test("A-B"));
});
