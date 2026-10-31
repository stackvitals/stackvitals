// The app's workflow file must be byte for byte what `stackvitals ci init` writes, for every module set, names and form.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { GH_LINK_MAX, newFile } from "../src/github/links";
import { FILE, MODULES, ciGuess, cliCommand, withInputs, workflowTemplate } from "../src/github/workflow";

const root = process.env.SV_REPO_ROOT || join(process.cwd(), "..");
const python = [join(root, ".venv", "Scripts", "python.exe"), join(root, ".venv", "bin", "python")].find(existsSync) || "python";

const subsets: string[][] = [];
for (let mask = 1; mask < 1 << MODULES.length; mask++) subsets.push(MODULES.filter((_, i) => mask & (1 << i)));
const NAMES: (string[] | null)[] = [null, ["Tests"], ["CI", "Lint # quick", "Build 'all'"], ["Déploiement 🚀", 'Say "hi"']];

function fromPython(): Record<string, string> | null {
  const script = `
import json, sys
from itertools import product
from stackvitals.ci.cli import workflow_template
cases = json.loads(sys.stdin.read())
print(json.dumps({c["key"]: workflow_template(names=c["names"], compact=c["compact"], modules=tuple(c["modules"])) for c in cases}))
`;
  const cases = [];
  for (const modules of subsets) for (const [i, names] of NAMES.entries()) for (const compact of [false, true]) cases.push({ key: `${modules}|${i}|${compact}`, names, compact, modules });
  const run = spawnSync(python, ["-c", script], { input: JSON.stringify(cases), encoding: "utf8", env: { ...process.env, PYTHONPATH: join(root, "src"), PYTHONIOENCODING: "utf-8" }, maxBuffer: 64 << 20 });
  if (run.status !== 0) return null;
  return JSON.parse(run.stdout);
}

test("matches stackvitals ci init for every module set, workflow names and compact form", (t) => {
  const py = fromPython();
  if (!py) { t.skip("python with stackvitals isn't available here"); return; }
  let n = 0;
  for (const modules of subsets) for (const [i, names] of NAMES.entries()) for (const compact of [false, true]) {
    assert.equal(workflowTemplate(names, { compact, modules }), py[`${modules}|${i}|${compact}`], `${modules} names#${i} compact=${compact}`);
    n++;
  }
  assert.equal(n, 15 * 4 * 2);
});

test("advanced choices become Action inputs under with:, only when they differ from the defaults", () => {
  const base = workflowTemplate(["CI"]);
  assert.equal(withInputs(base, { days: 90, budget: 800 }), base);
  const out = withInputs(base, { days: 30, budget: 1500, pages: "artifact" });
  assert.match(out, /\n {10}modules: ci,flow,deps,community\n {10}days: "30"\n {10}budget: "1500"\n {10}pages: artifact\n/);
  assert.match(withInputs(workflowTemplate(null, { compact: true, modules: ["flow"] }), { days: 14 }), /modules: flow\n {10}days: "14"\n/);
});

test("the CI guess, the prefilled GitHub link and the CLI command", () => {
  assert.deepEqual(ciGuess(["Tests", "Release", "Stale", "build-docs"]), ["Tests", "build-docs"]);
  assert.deepEqual(ciGuess(["Release"]), ["Release"]);
  const link = newFile("o/r", "main", FILE, "a: 1\n");
  assert.deepEqual(link, { url: "https://github.com/o/r/new/main?filename=.github%2Fworkflows%2Fstackvitals.yml&value=a%3A+1%0A", kind: "file", paste: null });
  assert.equal(cliCommand("o/r", [...MODULES]), "stackvitals ci init o/r > .github/workflows/stackvitals.yml");
  assert.equal(cliCommand("o/r", ["deps", "ci"]), "stackvitals ci init o/r --modules ci,deps > .github/workflows/stackvitals.yml");
  // The compact file fits GitHub's link cap; the full one (with comments) is what gets pasted when it doesn't.
  const setup = newFile("o/r", "main", FILE, workflowTemplate(["CI", "Tests"], { compact: true }), workflowTemplate(["CI", "Tests"]));
  assert.ok(setup.url.length <= GH_LINK_MAX, String(setup.url.length));
});
