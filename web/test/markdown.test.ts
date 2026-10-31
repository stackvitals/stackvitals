// The Help page's Markdown renderer: everything escaped, only safe links, and the same anchors the docs bundle lists.
import assert from "node:assert/strict";
import { join } from "node:path";
import { test } from "node:test";
import { helpFiles } from "../scripts/docs.mjs";
import { helpHref } from "../src/features/helpLink";
import { markdown, slugify } from "../src/features/markdown";

const root = process.env.SV_REPO_ROOT || join(process.cwd(), "..");
const ctx = { file: "guides/manager.md", docs: { "install.md": "install", "guides/manager.md": "guides-manager", "settings.md": "settings" } };
const html = (src: string) => markdown(src, ctx).html;

test("raw HTML, scripts and attribute breakouts come out as text", () => {
  const out = html('<script>alert(1)</script>\n\n<img src=x onerror=alert(1)> **<b>x</b>**\n\n`<i>code</i>` and "quotes" & \'apostrophes\'');
  assert.ok(!/<script|<img|<b>|<i>/.test(out), out);
  assert.match(out, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.match(out, /<strong>&lt;b&gt;x&lt;\/b&gt;<\/strong>/);
  assert.match(out, /<code>&lt;i&gt;code&lt;\/i&gt;<\/code>/);
  assert.match(out, /&quot;quotes&quot; &amp; &#39;apostrophes&#39;/);
  const fenced = html("```html\n<a href=\"javascript:x\">hi</a>\n```");
  assert.equal(fenced, '<pre class="md-code" data-lang="html"><code>&lt;a href=&quot;javascript:x&quot;&gt;hi&lt;/a&gt;</code></pre>');
  const table = html("| a | b |\n|---|--:|\n| <u>x</u> | `y|z` |");
  assert.ok(!table.includes("<u>"));
  assert.match(table, /<td class="is-right"><code>y\|z<\/code><\/td>/);
});

test("links: only safe schemes, docs open in the app, other repo files on GitHub, outside links in a new tab", () => {
  assert.equal(html("[x](javascript:alert(1))"), "<p>x</p>");
  assert.equal(html("[x](data:text/html,hi)"), "<p>x</p>");
  assert.equal(html('[x](https://a.example/?q="><script>)'), '<p><a href="https://a.example/?q=&quot;&gt;&lt;script&gt;" target="_blank" rel="noopener noreferrer">x</a></p>');
  assert.equal(html("[wiki](https://en.wikipedia.org/wiki/Foo_(bar))"), '<p><a href="https://en.wikipedia.org/wiki/Foo_(bar)" target="_blank" rel="noopener noreferrer">wiki</a></p>');
  assert.equal(html("[Install](../install.md#first-run)"), '<p><a href="#/help/install#first-run">Install</a></p>');
  assert.equal(html("[here](#numbers)"), '<p><a href="#/help/guides-manager#numbers">here</a></p>');
  assert.equal(html("[action](../../action.yml)"), '<p><a href="https://github.com/stackvitals/stackvitals/blob/main/action.yml" target="_blank" rel="noopener noreferrer">action</a></p>');
  assert.equal(html("<https://x.example>"), '<p><a href="https://x.example" target="_blank" rel="noopener noreferrer">https://x.example</a></p>');
  // Doc images are badges: only their alt text shows, nothing loads from elsewhere.
  assert.equal(html("![alt](https://x.example/i.png)"), '<p><span class="md-alt">alt</span></p>');
});

test("blocks: headings with anchors, nested lists, quotes and paragraphs", () => {
  const r = markdown("## Hello, `World`!\n\n## Hello, World\n\n- one\n- two\n  - nested\n1. a\n2. b\n\n> quoted *text*\n\nplain_snake_case and *em*", ctx);
  assert.deepEqual(r.headings.map((h) => h.id), ["hello-world", "hello-world-1"]);
  assert.match(r.html, /<h2 id="h-hello-world">Hello, <code>World<\/code>!<\/h2>/);
  assert.match(r.html, /<ul><li>one<\/li><li>two\n?<ul><li>nested<\/li><\/ul><\/li><\/ul>/);
  assert.match(r.html, /<ol><li>a<\/li><li>b<\/li><\/ol>/);
  assert.match(r.html, /<blockquote><p>quoted <em>text<\/em><\/p><\/blockquote>/);
  assert.match(r.html, /plain_snake_case and <em>em<\/em>/);
  assert.equal(helpHref("dora-guide.md", "Change failure rate"), "#/help/dora-guide#change-failure-rate");
  assert.equal(helpHref("guides/manager.md#x"), "#/help/guides-manager#x");
  assert.equal(slugify("[ci.monitors.pass_on_retry]"), "cimonitorspass_on_retry");
});

test("every doc renders with the anchors its index lists, and its doc links point at docs that exist", () => {
  const files = helpFiles(root);
  const index = JSON.parse(files["help/index.json"]!);
  const bodies: Record<string, string> = Object.assign({}, ...Object.entries(files).filter(([n]) => n.startsWith("help/") && n !== "help/index.json").map(([, b]) => JSON.parse(b)));
  const docs = Object.fromEntries(index.docs.map((d: { file: string; id: string }) => [d.file, d.id]));
  assert.ok(index.docs.length >= 20 && !index.docs.some((d: { id: string }) => d.id === "release-checklist"));
  for (const d of index.docs) {
    const r = markdown(bodies[d.id]!, { file: d.file, docs });
    assert.deepEqual(r.headings.filter((h) => h.level <= 3).map((h) => h.id), d.headings.map((h: [number, string, string]) => h[2]), d.id);
    for (const [, target] of r.html.matchAll(/href="#\/help\/([^"#]+)/g)) assert.ok(index.docs.some((x: { id: string }) => x.id === target), `${d.id} links to ${target}`);
    assert.ok(!/<(script|img|iframe|style)\b/i.test(r.html), d.id);
  }
  for (const e of index.entries) assert.ok(!e.h || index.docs.find((d: { id: string }) => d.id === e.doc).headings.some((h: [number, string, string]) => h[2] === e.h), `${e.doc}#${e.h}`);
});
