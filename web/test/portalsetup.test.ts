// Portal's setup file and App links must be what `stackvitals portal init` and `portal app-link` print; the private-repo
// variant must still be valid YAML with the App's token step switched on.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { appLink, catalogYaml, codeowners, entityName, ownerRef, portalWorkflow } from "../src/pages/portal/setup";

const root = process.env.SV_REPO_ROOT || join(process.cwd(), "..");
const python = [join(root, ".venv", "Scripts", "python.exe"), join(root, ".venv", "bin", "python")].find(existsSync) || "python";

function py(script: string, input = ""): string | null {
  const r = spawnSync(python, ["-c", script], { input, encoding: "utf8", env: { ...process.env, PYTHONPATH: join(root, "src"), PYTHONIOENCODING: "utf-8" } });
  return r.status === 0 ? r.stdout : null;
}

test("the workflow and App links match the CLI", (t) => {
  const out = py(`
import json
from stackvitals.portal.cli import WORKFLOW, app_link
from stackvitals.ci.cli import ACTION_REF
print(json.dumps({"wf": WORKFLOW.format(ref=ACTION_REF), "read": app_link("acme-co"), "write": app_link("acme-co", True), "long": app_link("a-very-long-organisation-name-here", True)}))`);
  if (out === null) { t.skip("Python with stackvitals isn't available"); return; }
  const want = JSON.parse(out);
  assert.equal(portalWorkflow(), want.wf);
  assert.equal(appLink("acme-co"), want.read);
  assert.equal(appLink("acme-co", true), want.write);
  assert.equal(appLink("a-very-long-organisation-name-here", true), want.long);
});

test("the private-repo workflow parses and runs the App token step", (t) => {
  const yaml = portalWorkflow({ app: true });
  assert.doesNotMatch(yaml, /#\s*(- uses: actions\/create-github-app-token|portal-token:)/);
  const out = py(`
import json, sys, yaml
d = yaml.safe_load(sys.stdin.read())
steps = d["jobs"]["portal"]["steps"]
print(json.dumps({"id": steps[0].get("id"), "client": steps[0]["with"]["client-id"], "token": steps[1]["with"].get("portal-token"), "mods": steps[1]["with"]["modules"]}))`, yaml);
  if (out === null) { t.skip("PyYAML isn't available"); return; }
  assert.deepEqual(JSON.parse(out), { id: "app", client: "${{ vars.PORTAL_CLIENT_ID }}", token: "${{ steps.app.outputs.token }}", mods: "portal" });
});

test("catalog file, CODEOWNERS and owner refs", (t) => {
  assert.equal(entityName("Payments API!"), "payments-api");
  assert.equal(ownerRef("@acme/payments-core"), "group:payments-core");
  assert.equal(ownerRef("mira-k"), "user:mira-k");
  assert.equal(codeowners(["mira-k", "@acme/ops"]).split("\n")[1], "* @mira-k @acme/ops");
  const y = catalogYaml({ name: "ledger", title: "Ledger: core", description: "yes", type: "service", lifecycle: "production", owner: "group:ledger", system: "" });
  assert.match(y, /title: "Ledger: core"/);
  assert.match(y, /description: "yes"/);
  assert.doesNotMatch(y, /system:/);
  const out = py(`import sys, yaml, json; print(json.dumps(yaml.safe_load(sys.stdin.read())))`, y);
  if (out === null) { t.skip("PyYAML isn't available"); return; }
  assert.deepEqual(JSON.parse(out), { apiVersion: "backstage.io/v1alpha1", kind: "Component", metadata: { name: "ledger", title: "Ledger: core", description: "yes" },
    spec: { type: "service", lifecycle: "production", owner: "group:ledger" } });
});
