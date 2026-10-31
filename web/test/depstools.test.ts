// Dependencies and Community tools: the code scanning workflow parses and uploads both files from the data branch,
// "check a package" finds a name across this repo's files, and the commands use only real CLI flags.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { reportCommand } from "../src/pages/community/command";
import { checkCommand, lookup, parseSpec } from "../src/pages/deps/lookup";
import { scanningWorkflow, yourCodeSteps } from "../src/pages/deps/scanning";

const root = process.env.SV_REPO_ROOT || join(process.cwd(), "..");
const python = [join(root, ".venv", "Scripts", "python.exe"), join(root, ".venv", "bin", "python")].find(existsSync) || "python";

test("the code scanning workflow is valid YAML with both uploads", (t) => {
  if (spawnSync(python, ["-c", "import yaml"]).status !== 0) { t.skip("python with pyyaml isn't available here"); return; }
  const r = spawnSync(python, ["-c", "import json, sys, yaml\nprint(json.dumps(yaml.safe_load(sys.stdin.read()), default=str))"], { input: scanningWorkflow("acme/app"), encoding: "utf-8" });
  assert.equal(r.status, 0, r.stderr);
  const doc = JSON.parse(r.stdout);
  assert.equal(doc.permissions["security-events"], "write");
  assert.deepEqual(doc.true.workflow_run.workflows, ["StackVitals"]);
  const steps = doc.jobs.upload.steps;
  assert.equal(steps[0].with.ref, "stackvitals-data");
  assert.deepEqual(steps.slice(1).map((s: { with: { sarif_file: string } }) => s.with.sarif_file), ["stackvitals-data/docs/vulns.sarif", "stackvitals-data/docs/security.sarif"]);
});

test("the Your code steps pass the file the Action reads", () => {
  assert.match(yourCodeSteps("imports").steps, /stackvitals deps imports \. --out imports\.json/);
  // Installed like the CI builder's workflow (the Action's repo and lock), not from PyPI.
  assert.match(yourCodeSteps("imports").steps, /uv sync --quiet --frozen --only-group action/);
  assert.doesNotMatch(yourCodeSteps("imports").steps, /pipx|pip install/);
  assert.match(yourCodeSteps("govulncheck").steps, /actions\/setup-go@[0-9a-f]{40}/);
  assert.match(yourCodeSteps("imports").input, /imports-json: imports\.json/);
  assert.match(yourCodeSteps("govulncheck").input, /govulncheck-json: govulncheck\.json/);
});

test("check a package finds a name in every file, by ecosystem when named", () => {
  const f = {
    vulns: { open: [{ id: "GHSA-1", package: "Lodash", ecosystem: "npm", severity: "high", file: "package-lock.json", version: "4.0.0", fixed: "4.17.21" }] },
    deps: { open: [{ pr: 7, package: "lodash", ecosystem: "npm", from: "4.0.0", to: "4.17.21", security: true }], security_overdue: [{ package: "lodash", pr: 7, age_hours: 60 }] },
    supply: { licences: { denied: [{ name: "lodash", licence: "AGPL-3.0-only", system: "NPM" }] }, scorecards: { low: [{ project: "github.com/lodash/lodash", score: 3, packages: ["lodash"] }] } },
  };
  const hits = lookup("lodash", f, "acme/app");
  assert.deepEqual(hits.map((h) => h.area), ["Known vulnerability", "Update pull request", "Licence rule", "Scorecard"]);
  assert.equal(hits[1]!.state, "security, overdue");
  assert.equal(lookup("pypi:lodash", f, "acme/app").filter((h) => h.area === "Known vulnerability").length, 0);
  assert.equal(lookup("react", f, "acme/app").length, 0);
  assert.deepEqual(parseSpec("npm:lodash"), { eco: "npm", name: "lodash" });
});

test("commands use only real flags", () => {
  assert.equal(checkCommand("npm:lodash"), "stackvitals deps check npm:lodash");
  assert.equal(checkCommand("go:golang.org/x/net"), "stackvitals deps check golang.org/x/net");
  assert.equal(reportCommand("acme/app", 12, "html"), "stackvitals community report acme/app --html ./community");
  assert.equal(reportCommand("acme/app", 24, "json"), "stackvitals community report acme/app --months 24 --json > community.json");
  assert.equal(reportCommand("not a repo", 12, "text"), "stackvitals community report owner/name");
});
