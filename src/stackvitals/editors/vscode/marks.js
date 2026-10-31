// Where the repo's flaky and broken tests are declared in one file, from the data branch's docs/data.json.
"use strict";

const MARKED = new Set(["flaky", "broken"]);
// Test declarations by language; group 1 is the name (an identifier, or a title for JS and TS).
const DECLS = [
  { re: /^[ \t]*(?:async[ \t]+)?def[ \t]+(test\w*)/gmd },
  { re: /^func[ \t]+(?:\([^)]*\)[ \t]*)?((?:Test|Benchmark|Fuzz|Example)\w*)/gmd },
  { re: /\b(?:void|fun|Task|fn)[ \t]+(\w+)[ \t]*[(<]/gd },
  { re: /\b(?:it|test|describe|context)(?:\.\w+)*[ \t]*\([ \t]*(?:'((?:\\.|[^'\\\n])+)'|"((?:\\.|[^"\\\n])+)"|`((?:\\.|[^`\\\n])+)`)/gd, title: true },
];

function parts(tid) {
  // "file::Class::name", "pkg::TestX/sub" or "Ns.Class.Method": the scope it lives in and its own name.
  const cut = tid.lastIndexOf("::");
  let scope = cut >= 0 ? tid.slice(0, cut) : "";
  let name = cut >= 0 ? tid.slice(cut + 2) : tid;
  // Parameters ("test_x[1.5]") may hold dots, so only the part before them is split.
  const bare = name.replace(/\[.*$/s, "");
  if (!/\s/.test(bare) && bare.includes(".") && !bare.includes("(")) {
    scope += "." + bare.slice(0, bare.lastIndexOf("."));
    name = name.slice(bare.lastIndexOf(".") + 1);
  }
  return { scope, name };
}

function identifier(name) {
  // test_x[param], method(args) and TestX/sub all live where their first part is declared.
  return name.replace(/\[.*$/s, "").replace(/\(.*$/s, "").split("/")[0].trim();
}

function inFile(scope, rel) {
  if (!scope) return true;
  const file = rel.split("/").pop();
  const stem = file.replace(/\.[^.]+$/, "");
  if (stem && scope.includes(stem)) return true;
  // Go names the package (its folder), not the file.
  if (file.endsWith(".go")) {
    const dirs = rel.split("/").slice(0, -1);
    return dirs.length === 0 || scope.split("/").pop() === dirs[dirs.length - 1];
  }
  return false;
}

function findMarks(text, rel, tests) {
  const wanted = (Array.isArray(tests) ? tests : [])
    .filter((t) => t && typeof t.id === "string" && t.id && MARKED.has(t.state))
    .map((t) => ({ t, ...parts(t.id) }))
    .filter((w) => w.name && inFile(w.scope, rel));
  if (!wanted.length) return [];
  const starts = [0];
  for (let i = 0; i < text.length; i++) if (text[i] === "\n") starts.push(i + 1);
  const at = (offset) => {
    let lo = 0, hi = starts.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (starts[mid] <= offset) lo = mid; else hi = mid - 1;
    }
    return { line: lo, col: offset - starts[lo] };
  };
  const out = [];
  for (const decl of DECLS) {
    decl.re.lastIndex = 0;
    for (const m of text.matchAll(decl.re)) {
      const g = [1, 2, 3].find((k) => m[k] !== undefined);
      const found = m[g];
      const hits = wanted.filter((w) => decl.title
        ? w.name === found || [" ", " > ", " › "].some((sep) => w.name.endsWith(sep + found))
        : identifier(w.name) === found);
      if (!hits.length) continue;
      // Parametrised cases share one declaration; the one that flaked most speaks for it.
      hits.sort((a, b) => (b.t.flake_events || 0) - (a.t.flake_events || 0));
      out.push({ ...at(m.indices[g][0]), length: found.length, test: hits[0].t, variants: hits.length });
    }
  }
  return out.sort((a, b) => a.line - b.line || a.col - b.col);
}

function describe(t) {
  const n = (v) => (Number.isFinite(v) ? v : "?");
  if (t.state === "broken") {
    return `Broken (StackVitals): failed in ${n(t.failures)} of the last ${n(t.runs)} runs.`
      + (t.message ? ` Failure: ${String(t.message).slice(0, 200)}` : "");
  }
  const last = typeof t.last_flake === "string" ? `, last on ${t.last_flake.slice(0, 10)}` : "";
  return `Flaky (StackVitals): failed and then passed with no code change ${n(t.flake_events)} times in ${n(t.runs)} runs`
    + ` over the last 30 days${last}.`
    + (t.flake ? ` Looks like a ${t.flake} flake.` : "")
    + (t.message ? ` Usual failure: ${String(t.message).slice(0, 200)}` : "");
}

module.exports = { findMarks, describe };
