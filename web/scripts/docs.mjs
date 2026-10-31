// Build step: the docs (docs/*.md and docs/guides/*.md) as lazy JSON for the Help page, and the Action's workflow inputs
// (action.yml) for the Settings page's Workflow group. Output paths are relative to app/.
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { gzipSync } from "node:zlib";

export const HELP_GROUPS = ["Getting started", "Modules", "Connectors", "Agents", "Privacy and security", "Accuracy", "Reference"];
const GROUP = {
  quickstart: 0, install: 0, app: 0, faq: 0, "guides/maintainer": 0, "guides/manager": 0, "guides/platform": 0,
  modules: 1, "dora-guide": 1, chaoss: 1, coverage: 1, scaling: 1, connectors: 2, triage: 2,
  privacy: 4, "threat-model": 4, enterprise: 4, accuracy: 5, methods: 5, rules: 5, limitations: 5,
  settings: 6, architecture: 6, roadmap: 6,
};
// Internal plans stay out of the app.
const SKIP = new Set(["release-checklist"]);
// Sections listed on their own: every module, and what the docs say about agents.
const SECTIONS = [["modules", 1, null], ["app", 3, "For agents"], ["limitations", 3, "The MCP server"],
  ["accuracy", 3, "Against a general AI agent"], ["faq", 3, "How is this different from asking an AI agent to look at my CI?"]];
const SPLIT_GZ = 60 * 1024;
// Sections whose opening lines are commands or a source note get a written summary instead.
const SUMMARY = {
  "modules#ci-health": "Flaky and failing tests and jobs, time to green and the cost of re-runs, from every CI run kept in your repo.",
  "app#for-agents": "Agents can propose a settings change or a decision as a prefilled link; a person opens it and submits.",
  "limitations#the-mcp-server": "What the MCP server adds for a coding agent and where it doesn't help: it needs a token, never changes a repo and answers from kept history.",
};

// Kept in step with features/markdown.ts (a test checks both give the same anchors).
const slugify = (t) => t.trim().toLowerCase().replace(/[^\p{L}\p{N}\p{M}\s_-]/gu, "").replace(/\s/g, "-");
const plain = (s) => s.replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1").replace(/`+([^`]*)`+/g, "$1")
  .replace(/\*\*|__|~~/g, "").replace(/(^|\W)[*_](\S[^*_]*?)[*_](?=\W|$)/g, "$1$2").replace(/\\(.)/g, "$1").trim();
const docId = (file) => file.replace(/\.md$/, "").replace(/\//g, "-");

function clip(text, max = 220) {
  const t = text.replace(/\s+/g, " ").trim();
  return t.length <= max ? t : t.slice(0, t.lastIndexOf(" ", max)).replace(/[,;:]$/, "") + "…";
}

// The first real paragraph from line `from` on, as plain text for summaries; a lead-in to code ("Try it:") or a bare
// "(note)" is skipped for the paragraph after it.
function firstPara(lines, from = 0) {
  let out = [], stub = "";
  let fence = false;
  const done = () => { const t = plain(out.join(" ")); if ((/:$/.test(t) && t.length < 120 && !t.includes("?")) || /^\(.*\)$/.test(t)) { stub ||= t; out = []; return false; } return true; };
  for (let i = from; i < lines.length; i++) {
    const l = lines[i];
    if (/^\s*(```|~~~)/.test(l)) { fence = !fence; continue; }
    if (fence) continue;
    if (!l.trim()) { if (out.length && done()) break; continue; }
    if (/^\s*(#|\||>|[-*+] |\d+[.)] |<)/.test(l)) { if (out.length && done()) break; if (/^#/.test(l) && i > from) break; continue; }
    if (!out.length && /^\s{2}/.test(l)) continue;
    out.push(l.trim());
  }
  return clip((out.length ? plain(out.join(" ")) : stub).replace(/:$/, ""));
}

function parse(file, text) {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const t = lines.findIndex((l) => /^# /.test(l));
  const title = t >= 0 ? plain(lines[t].slice(2)) : file;
  const body = lines.slice(t + 1).join("\n").replace(/^\n+/, "");
  const bl = body.split("\n");
  const seen = new Map(), headings = [];
  let fence = null;
  bl.forEach((l, i) => {
    const f = /^\s*(`{3,}|~{3,})/.exec(l);
    if (f) { if (!fence) fence = f[1]; else if (l.trim().startsWith(fence[0].repeat(fence.length)) && /^\s*[`~]+\s*$/.test(l)) fence = null; return; }
    const m = !fence && /^(#{1,6})\s+(.*?)\s*#*\s*$/.exec(l);
    if (!m) return;
    const text = plain(m[2]), base = slugify(text), n = seen.get(base);
    seen.set(base, (n ?? -1) + 1);
    const id = n === undefined ? base : `${base}-${n + 1}`;
    headings.push({ level: m[1].length, text, id, line: i });
  });
  return { id: docId(file), file, title, body, summary: firstPara(bl), headings, lines: bl };
}

export function helpFiles(root) {
  const dir = join(root, "docs");
  const files = [...readdirSync(dir).filter((f) => f.endsWith(".md")).sort(),
    ...(existsSync(join(dir, "guides")) ? readdirSync(join(dir, "guides")).filter((f) => f.endsWith(".md")).sort().map((f) => `guides/${f}`) : [])]
    .filter((f) => !SKIP.has(f.replace(/\.md$/, "")));
  const docs = files.map((f) => parse(f, readFileSync(join(dir, f), "utf8")));
  const group = (d) => GROUP[d.file.replace(/\.md$/, "")] ?? 6;
  // Within a group, docs follow GROUP's order (quick start first); docs it doesn't name come last.
  const rank = (d) => { const i = Object.keys(GROUP).indexOf(d.file.replace(/\.md$/, "")); return i < 0 ? 99 : i; };
  const entries = [...docs].sort((a, b) => rank(a) - rank(b)).map((d) => ({ doc: d.id, title: d.title, summary: d.summary, group: group(d) }));
  for (const [name, g, heading] of SECTIONS) {
    const d = docs.find((x) => x.id === name);
    for (const h of d ? d.headings.filter((x) => x.level === 2 && (!heading || x.text === heading)) : []) {
      entries.push({ doc: d.id, h: h.id, title: h.text, summary: SUMMARY[`${d.id}#${h.id}`] || firstPara(d.lines, h.line + 1), group: g });
    }
  }
  const bodies = Object.fromEntries(docs.map((d) => [d.id, d.body]));
  const whole = gzipSync(JSON.stringify(bodies), { level: 9 }).length;
  const chunkOf = (d) => (whole > SPLIT_GZ ? slugify(HELP_GROUPS[group(d)]) : "docs");
  const out = {};
  for (const d of docs) (out[`help/${chunkOf(d)}.json`] ||= {})[d.id] = d.body;
  const index = {
    groups: HELP_GROUPS, entries,
    docs: docs.map((d) => ({ id: d.id, file: d.file, title: d.title, group: group(d), chunk: chunkOf(d),
      headings: d.headings.filter((h) => h.level <= 3).map((h) => [h.level, h.text, h.id]) })),
  };
  const result = { "help/index.json": JSON.stringify(index) };
  for (const [name, body] of Object.entries(out)) result[name] = JSON.stringify(body);
  result["settings-workflow.json"] = JSON.stringify(workflowInputs(root));
  return result;
}

const unquote = (v) => (v.startsWith('"') ? JSON.parse(v) : v.startsWith("'") ? v.slice(1, -1).replace(/''/g, "'") : v);

// The Action's inputs, each with its help, default and the control that fits it; secrets are named, never set here.
export function workflowInputs(root) {
  const lines = readFileSync(join(root, "action.yml"), "utf8").replace(/\r\n?/g, "\n").split("\n");
  const start = lines.indexOf("inputs:");
  const inputs = [];
  for (let i = start + 1; i < lines.length && (/^\s/.test(lines[i]) || !lines[i].trim()); i++) {
    const name = /^ {2}([\w-]+):\s*$/.exec(lines[i]);
    if (name) { inputs.push({ name: name[1], help: "", default: "" }); continue; }
    const field = /^ {4}(description|default):\s*(.*)$/.exec(lines[i]);
    if (field && inputs.length) inputs[inputs.length - 1][field[1] === "description" ? "help" : "default"] = unquote(field[2].trim());
  }
  return inputs.map((x) => {
    const secret = /pass a secret/i.test(x.help) || /(^|-)token$|-key$|^s3-(key-id|secret)$|^triage-key$/.test(x.name);
    const kind = x.name === "modules" ? "choices" : x.name === "pages" ? "choice" : /^(true|false)$/.test(x.default) ? "bool" : /^\d+$/.test(x.default) ? "int" : "text";
    return { ...x, kind, ...(kind === "choices" ? { choices: ["ci", "flow", "deps", "community", "portal"] } : kind === "choice" ? { choices: ["branch", "deploy", "artifact"] } : {}),
      ...(secret ? { secret: true } : {}) };
  });
}

// Sizes for the build log: what Help downloads, gzipped.
export function helpReport(files) {
  return Object.entries(files).filter(([n]) => n.startsWith("help/"))
    .map(([n, body]) => `${n} ${(gzipSync(body, { level: 9 }).length / 1024).toFixed(1)} KB gz`).join(", ");
}
