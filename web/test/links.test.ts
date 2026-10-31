// Prefilled github.com links stay under the length GitHub accepts; past it, only the name or title is prefilled and the rest is pasted.
import assert from "node:assert/strict";
import { test } from "node:test";
import { issueUrl } from "../src/data/requestIssue";
import { request, requestBody } from "../src/data/write";
import { GH_LINK_MAX, newFile, newIssue } from "../src/github/links";
import type { AppJson } from "../src/data/types";

const app = { repo: "acme/api" } as AppJson;

test("the cap is 4,000 characters (GitHub answered 500 at 5,727 signed out)", () => {
  assert.equal(GH_LINK_MAX, 4000);
});

test("a new file: filled in when it fits, else the file name only with the content to paste", () => {
  const small = newFile("acme/api", "main", ".github/CODEOWNERS", "* @a\n");
  assert.equal(small.paste, null);
  assert.equal(new URL(small.url).searchParams.get("value"), "* @a\n");
  const content = "x: a b\n".repeat(800);
  const big = newFile("acme/api", "release/1.0", ".github/workflows/x.yml", content);
  assert.equal(big.url, "https://github.com/acme/api/new/release%2F1.0?filename=.github%2Fworkflows%2Fx.yml");
  assert.equal(big.paste, content);
  assert.equal(big.kind, "file");
  // A different text to paste (the full file) when the short one doesn't fit either.
  assert.equal(newFile("acme/api", "main", "f.yml", content, "full").paste, "full");
  // Right at the edge: a link of exactly the cap is kept whole, one more character is not.
  const base = "https://github.com/acme/api/new/main?filename=f&value=".length;
  assert.equal(newFile("acme/api", "main", "f", "a".repeat(GH_LINK_MAX - base)).paste, null);
  assert.ok(newFile("acme/api", "main", "f", "a".repeat(GH_LINK_MAX - base + 1)).paste);
});

test("a request issue: title and body when they fit, else the title only with the body to paste", () => {
  const short = issueUrl(app, "StackVitals: mute test a", request([{ verb: "mute", kind: "test", id: "a" }]));
  assert.ok(short && short.paste === null && short.url.includes("&body="));
  assert.equal(new URL(short.url).searchParams.get("title"), "StackVitals: mute test a");
  const settings = Object.fromEntries(Array.from({ length: 200 }, (_, i) => [`alerts.key_${i}`, i]));
  const req = request([], settings);
  const long = issueUrl(app, "StackVitals: change 200 settings", req);
  assert.ok(long);
  assert.equal(long.url, `https://github.com/acme/api/issues/new?title=${encodeURIComponent("StackVitals: change 200 settings")}`);
  assert.equal(long.paste, requestBody(req));
  assert.equal(long.kind, "issue");
  assert.equal(issueUrl({ repo: "not a repo" } as AppJson, "t", req), null);
});

test("every generated link is at most 4,000 characters", () => {
  for (const n of [0, 10, 100, 1000, 3000, 3990, 4000, 4100, 9000, 50000]) {
    const text = "line with spaces & symbols +/?#\n".repeat(Math.ceil(n / 32)).slice(0, n);
    assert.ok(newFile("acme/api", "main", ".github/workflows/stackvitals-tests.yml", text).url.length <= GH_LINK_MAX, `file ${n}`);
    assert.ok(newIssue("acme/api", "StackVitals: a title", text).url.length <= GH_LINK_MAX, `issue ${n}`);
  }
});
