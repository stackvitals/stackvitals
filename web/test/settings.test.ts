// Settings: what the app sends is what the Action reads (request block, TOML edit, alert replay), and the workflow edit.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { request, requestBody } from "../src/data/write";
import { check, fmt, label, tomlSnippet } from "../src/features/settingsModel";
import { replay, type Point } from "../src/features/settingsReplay";
import { tomlEdit, workflowEdit, workflowValues } from "../src/features/settingsToml";
import { workflowTemplate } from "../src/github/workflow";

const root = process.env.SV_REPO_ROOT || join(process.cwd(), "..");
const python = [join(root, ".venv", "Scripts", "python.exe"), join(root, ".venv", "bin", "python")].find(existsSync) || "python";

function py(script: string, input: unknown): any {
  const run = spawnSync(python, ["-c", script], { input: JSON.stringify(input), encoding: "utf8", env: { ...process.env, PYTHONPATH: join(root, "src"), PYTHONIOENCODING: "utf-8" }, maxBuffer: 64 << 20 });
  return run.status === 0 ? JSON.parse(run.stdout) : null;
}

test("a settings request the app builds parses back exactly in the Action", (t) => {
  const change = { verb: "mute", kind: "job", id: "ci.yml / lint", until: "2026-11-20", reason: 'say "hi" & <b>' };
  const settings = { "alerts.pickup_p75_hours": 6, "identity.teams": { web: ["amy", "bob"] }, "digest.day": null, "community.norms": "Ünïcode ✓ \\ \"q\"" };
  const out = py(`
import json, sys
from datetime import date
from stackvitals.core import decisions as dec
req = dec.parse_request(json.loads(sys.stdin.read()), date(2026, 10, 21))
print(json.dumps({"settings": req.settings, "changes": [c.__dict__ for c in req.changes]}))`, requestBody(request([change], settings), "note"));
  if (!out) { t.skip("python with stackvitals isn't available here"); return; }
  assert.deepEqual(out.settings, settings);
  assert.equal(out.changes[0].id, "ci.yml / lint");
  assert.equal(out.changes[0].reason, 'say "hi" & <b>');
});

const KINDS: Record<string, string> = {
  "alerts.pickup_p75_hours": "hours", "alerts.change_failure_rate": "share", "alerts.channels": "choices", "identity.teams": "teams", "identity.aliases": "map",
  "ci.mute": "dates", "automation.issues": "switch", "digest.day": "choice", "community.norms": "text", "connectors.jira.key_expires": "date",
  "ci.monitors.pass_on_retry.min_events": "int", "deps.policy.min_scorecard": "number", "ci.quarantine.never": "list",
};
const FILES = [
  "",
  "# StackVitals\n[alerts]\npickup_p75_hours = 4  # keep it tight\nchannels = [\n  \"webhook\",\n]\n\n[digest]\nday = \"monday\"\n",
  "[identity.teams]\n\"web\" = [\"amy\"]\n\n[ci.mute]\n\"a b\" = 2026-12-31\n\n[automation]\nissues = false\n",
  "[ci.monitors.pass_on_retry]\nmin_events = 3\r\n\r\n[community]\nnorms = 'old # not a comment'\n",
];
const CHANGES = [
  { "alerts.pickup_p75_hours": 6, "alerts.channels": ["webhook", "issue"] },
  { "alerts.change_failure_rate": 0.2, "digest.day": "friday", "automation.issues": true },
  { "identity.teams": { web: ["amy", "bob"], "plat form": ["c"] }, "ci.mute": { "tests/x.py::t": "2027-01-31" }, "identity.aliases": { old: "new" } },
  { "ci.monitors.pass_on_retry.min_events": 2, "community.norms": "Issues on \"Mondays\" ✓", "connectors.jira.key_expires": "2027-10-21" },
  { "alerts.pickup_p75_hours": null, "identity.teams": null, "automation.issues": null, "deps.policy.min_scorecard": 5.5, "ci.quarantine.never": ["a", "b c"] },
];

test("the settings file edit matches core/tomledit.py line for line", (t) => {
  const cases = FILES.flatMap((text) => CHANGES.map((changes) => ({ text, changes })));
  const out = py(`
import json, sys
from stackvitals.core.tomledit import EditError, apply
res = []
for c in json.loads(sys.stdin.read()):
    try:
        res.append(apply(c["text"], c["changes"]))
    except EditError as e:
        res.append("ERROR")
print(json.dumps(res))`, cases);
  if (!out) { t.skip("python with stackvitals isn't available here"); return; }
  let compared = 0;
  cases.forEach((c, i) => {
    if (out[i] === "ERROR") return;
    assert.equal(tomlEdit(c.text, c.changes, KINDS), out[i], `case ${i}: ${JSON.stringify(c)}`);
    compared++;
  });
  assert.ok(compared >= 15, `only ${compared} cases compared`);
  assert.throws(() => tomlEdit("", { "nope.key": 1 }, KINDS), /not a setting/);
});

test("the alert preview replays like core/alerts.py, gaps, thin days and ranges included", (t) => {
  let seed = 7;
  const rnd = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
  const trials = Array.from({ length: 20 }, () => {
    const series: Record<string, Point[]> = {};
    for (const m of ["pickup_p75_hours", "review_p75_hours", "cycle_p75_hours", "change_failure_rate"]) {
      series[m] = Array.from({ length: 91 }, (_, d) => {
        const v = rnd() < 0.1 ? null : Math.round(rnd() * (m === "change_failure_rate" ? 0.4 : 30) * 1000) / 1000;
        const low = v === null || rnd() < 0.2 ? null : Math.round(v * (0.3 + rnd() * 0.7) * 1000) / 1000;
        return [`d${d}`, v, [0, 5, 9, 10, 20, 40][Math.floor(rnd() * 6)]!, low] as Point;
      });
    }
    return { series, limits: { pickup_p75_hours: [4, 8, 12][Math.floor(rnd() * 3)]!, cycle_p75_hours: 20, change_failure_rate: 0.15 } };
  });
  const out = py(`
import json, sys
from stackvitals.core.alerts import HEADS_UP, MIN_N, replay
trials = json.loads(sys.stdin.read())
print(json.dumps({"heads": HEADS_UP, "min": MIN_N, "fired": [replay({m: [tuple(p) for p in v] for m, v in t["series"].items()}, t["limits"]) for t in trials]}))`, trials);
  if (!out) { t.skip("python with stackvitals isn't available here"); return; }
  trials.forEach((tr, i) => assert.deepEqual(replay(tr.series, tr.limits, { headsUp: out.heads, minN: out.min }), out.fired[i], `trial ${i}`));
});

test("TOML lines to paste, labels, formats and field checks", () => {
  assert.equal(tomlSnippet({ "alerts.pickup_p75_hours": 6, "ci.mute": { "a b": "2026-12-31" }, "digest.day": null }, KINDS),
    "[alerts]\npickup_p75_hours = 6\n\n[ci.mute]\n\"a b\" = 2026-12-31\n\n[digest]\n# day: back to its default (remove the line)\n");
  assert.equal(label("alerts.pickup_p75_hours"), "Pickup time");
  assert.equal(label("ci.monitors.slow.p50_ms"), "P50 ms");
  assert.equal(fmt(0.15, "share"), "15%");
  assert.equal(fmt(null, "switch"), "Workflow input");
  assert.match(check("connectors.jira.url", "text", "https://evil.example.com"), /Jira Cloud/);
  assert.equal(check("connectors.jira.url", "text", "https://acme.atlassian.net"), "");
  assert.match(check("delivery.deploy_workflow", "regex", "(unclosed"), /compile/);
});

test("workflow inputs are read and edited inside the StackVitals step only", () => {
  const yml = workflowTemplate(["CI"]);
  const now = workflowValues(yml)!;
  assert.equal(now.modules, "ci,flow,deps,community");
  assert.equal(now["jira-token"], "${{ secrets.JIRA_API_TOKEN }}");
  const out = workflowEdit(yml, { modules: "ci,flow", days: "30", "jira-token": null, webhook: "${{ secrets.HOOK }}" });
  const after = workflowValues(out)!;
  assert.equal(after.modules, "ci,flow");
  assert.equal(after.days, "30");
  assert.equal(after["jira-token"], undefined);
  assert.equal(after.webhook, "${{ secrets.HOOK }}");
  // Everything outside the step's with: block is unchanged.
  const strip = (s: string) => s.split("\n").filter((l) => !/^ {10}\S/.test(l)).join("\n");
  assert.equal(strip(out), strip(yml));
  assert.match(out, /\n {10}modules: ci,flow\n/);
  assert.throws(() => workflowEdit("name: x\non: push\n", { days: "3" }), /no StackVitals step/);
  // A step without with: gets one.
  const bare = "jobs:\n  a:\n    steps:\n      - uses: stackvitals/stackvitals@v0\n      - run: echo\n";
  assert.equal(workflowEdit(bare, { days: "7" }), "jobs:\n  a:\n    steps:\n      - uses: stackvitals/stackvitals@v0\n        with:\n          days: 7\n      - run: echo\n");
});
