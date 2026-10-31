// The "Set up in your CI" workflow: valid YAML for every runner and feature set, each stackvitals command with only the
// flags its CLI takes, shell that parses, and a runner guess from test and job names.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { GH_LINK_MAX } from "../src/github/links";
import { FEATURES, RUNNERS, PRESETS, fileLink, guessRunner, suggestShards, testWorkflow, type Feature, type Options, type RunnerId } from "../src/pages/ci/workflowgen";

const root = process.env.SV_REPO_ROOT || join(process.cwd(), "..");
const python = [join(root, ".venv", "Scripts", "python.exe"), join(root, ".venv", "bin", "python")].find(existsSync) || "python";
const bash = [process.env.SV_BASH, "C:/Program Files/Git/bin/bash.exe", "/bin/bash", "/usr/bin/bash"].find((b) => b && existsSync(b));

// The flags each command takes, as `stackvitals ci <cmd> --help` lists them.
const FLAGS: Record<string, string[]> = {
  retry: ["--reports", "--times"], "burn-in": ["--base", "--times", "--reports", "--only-new"], impact: ["--base", "--tests", "--learned"],
  shards: ["--n", "--reports", "--files", "--index", "--py-paths", "--json"], validate: [], quarantine: ["--reports", "--list", "--print"],
};

const opts = (runner: RunnerId, features: Feature[], more: Partial<Options> = {}): Options => ({
  repo: "acme/api", branch: "main", runner, features, install: PRESETS[runner].install, tests: PRESETS[runner].tests, extra: "", shards: 4, times: 5, ...more });

const SETS: Feature[][] = [[], [...FEATURES], ...FEATURES.map((f) => [f]), ["impact", "shards"], ["retry", "quarantine"]];
const cases = RUNNERS.flatMap((r) => SETS.flatMap((fs) => [true, false].map((comments) => ({ key: `${r}|${fs.join(",")}|${comments}`, o: opts(r, fs, { comments }) }))));

// null only when python with pyyaml isn't here; a file that doesn't parse fails the test.
function parsed(): Record<string, any> | null {
  if (spawnSync(python, ["-c", "import yaml"]).status !== 0) return null;
  const script = "import json, sys, yaml\nprint(json.dumps({k: yaml.safe_load(v) for k, v in json.loads(sys.stdin.read()).items()}, default=str))";
  const input = JSON.stringify(Object.fromEntries(cases.map((c) => [c.key, testWorkflow(c.o)])));
  const run = spawnSync(python, ["-c", script], { input, encoding: "utf8", env: { ...process.env, PYTHONIOENCODING: "utf-8" }, maxBuffer: 64 << 20 });
  assert.equal(run.status, 0, `a workflow isn't valid YAML: ${run.stderr}`);
  return JSON.parse(run.stdout);
}

// Each stackvitals invocation and its flags, up to the "--" that starts the wrapped command.
function invocations(script: string): { cmd: string; flags: string[] }[] {
  const out: { cmd: string; flags: string[] }[] = [];
  for (const m of script.matchAll(/stackvitals ci ([a-z-]+)((?: (?!--(?: |$))\S+)*)/g)) out.push({ cmd: m[1]!, flags: (m[2]!.match(/ --[a-z-]+/g) || []).map((s) => s.trim()) });
  return out;
}

const steps = (doc: any, job = "tests"): any[] => doc.jobs[job].steps;
const runs = (doc: any): string[] => Object.values(doc.jobs).flatMap((j: any) => j.steps.filter((s: any) => s.run).map((s: any) => s.run as string));

test("valid workflow YAML for every runner, feature set and form", (t) => {
  const docs = parsed();
  if (!docs) { t.skip("python with pyyaml isn't available here"); return; }
  for (const { key, o } of cases) {
    const d = docs[key];
    assert.equal(d.name, "Tests (StackVitals)", key);
    // YAML 1.1 reads the "on" key as true.
    const on = d.on ?? d[true as any] ?? d["True"];
    assert.deepEqual(on.push.branches, ["main"], key);
    assert.ok("pull_request" in on && "workflow_dispatch" in on, key);
    assert.deepEqual(d.permissions, { contents: "read", actions: "read" }, key);
    for (const [name, job] of Object.entries<any>(d.jobs)) {
      assert.equal(job["runs-on"], "ubuntu-latest", `${key} ${name}`);
      for (const s of job.steps) assert.ok(!!s.uses !== !!s.run, `${key} ${name}: a step has uses or run, not both`);
    }
    const st = steps(d);
    assert.match(st[0].uses, /^actions\/checkout@[0-9a-f]{40}$/, key);
    const upload = st.find((s: any) => s.name === "Keep the test reports");
    assert.match(upload.uses, /^actions\/upload-artifact@[0-9a-f]{40}$/);
    assert.equal(upload.with.path, PRESETS[o.runner].reports, key);
    assert.match(upload.with.name, /^test-results/);
    const has = (f: Feature) => o.features.includes(f);
    assert.deepEqual(Object.keys(d.jobs), ["tests"], key);
    const burn = st.find((s: any) => /^Run new and changed tests/.test(s.name || ""));
    assert.equal(!!burn, has("burnin"), key);
    if (burn) assert.equal(burn.if, `always() && github.event_name == 'pull_request'${has("shards") ? " && matrix.shard == 1" : ""}`, key);
    assert.equal(!!d.jobs.tests.strategy, has("shards"), key);
    if (has("shards")) assert.deepEqual(d.jobs.tests.strategy.matrix.shard, [1, 2, 3, 4], key);
    assert.equal(st[0].with?.["fetch-depth"] === 0, has("burnin") || has("impact"), key);
    assert.equal(st.some((s: any) => s.name === "Install StackVitals"), o.features.length > 0, key);
    assert.equal(st.some((s: any) => s.name === "Check the test reports" && s["continue-on-error"] === true), has("validate"), key);
    assert.equal(st.some((s: any) => s.name === "Pick the tests"), has("impact") || has("shards"), key);
    const all = runs(d).join("\n");
    assert.equal(/stackvitals ci retry /.test(all), has("retry"), key);
    assert.equal(/stackvitals ci quarantine /.test(all), has("quarantine"), key);
    assert.equal(/stackvitals ci impact /.test(all), has("impact"), key);
    assert.equal(/stackvitals ci shards /.test(all), has("shards"), key);
    assert.equal(/stackvitals ci burn-in /.test(all), has("burnin"), key);
    for (const { cmd, flags } of invocations(all)) {
      assert.ok(cmd in FLAGS, `${key}: unknown command ${cmd}`);
      for (const f of flags) assert.ok(FLAGS[cmd]!.includes(f), `${key}: ${cmd} takes no ${f}`);
    }
    // No pull request text reaches a shell through a ${{ }} expression; values come in through env.
    assert.ok(!/\$\{\{ github\.(base_ref|head_ref|event\.pull_request)/.test(all), key);
    if (!o.comments) assert.ok(!/(^|\s)#(?!!)/m.test(testWorkflow(o).replace(/'[^']*'|"[^"]*"/g, "")), `${key}: no comments in the short form`);
  }
});

test("the right flags per feature", () => {
  const all = testWorkflow(opts("pytest", [...FEATURES]));
  assert.match(all, /stackvitals ci quarantine --reports 'reports\/\*\.xml' -- stackvitals ci retry --reports 'reports\/\*\.xml' -- run-tests \$FILES --then rerun-failed/);
  assert.match(all, /stackvitals ci burn-in --base "origin\/\$BASE" --times 5 --reports 'reports\/\*\.xml' -- run-tests \{files\}/);
  assert.match(all, /stackvitals ci impact --base "origin\/\$BASE" --tests 'tests\/\*\*\/test_\*\.py'/);
  assert.match(all, /stackvitals ci shards "\$GITHUB_REPOSITORY" --n 4 --index "\$SHARD" --py-paths --files 'tests\/\*\*\/test_\*\.py'/);
  assert.match(all, /stackvitals ci validate 'reports\/\*\.xml'/);
  assert.match(all, /pytest --lf --junitxml=reports\/junit\.xml/);
  // Runners without "only failed" retry the same tests; class-based runners get no --files.
  const mvn = testWorkflow(opts("maven", ["retry", "shards"]));
  assert.match(mvn, /stackvitals ci retry --reports '\*\*\/target\/surefire-reports\/\*\.xml' -- run-tests \$FILES --then run-tests \$FILES/);
  assert.doesNotMatch(mvn, /rerun-failed|--files/);
  assert.match(testWorkflow(opts("go", ["retry"])), /--then rerun-failed[\s\S]*|rerun-failed/);
  assert.match(testWorkflow(opts("jest", ["burnin"], { times: 8 })), /--times 8 --reports 'reports\/\*\.json' -- run-tests \{files\}/);
  assert.match(testWorkflow(opts("vitest", [], { extra: "--project unit" })), /--outputFile\.junit=reports\/vitest\.xml --project unit "\$@"/);
  assert.match(testWorkflow(opts("pytest", ["shards"], { shards: 3 })), /shard: \[1, 2, 3\][\s\S]*name: test-results-\$\{\{ matrix\.shard \}\}/);
  // StackVitals installs from the Action's own repo and lock, like the Action and the GitLab template.
  assert.match(all, /git clone -q --depth 1 --branch v0 https:\/\/github\.com\/stackvitals\/stackvitals\.git/);
  assert.match(all, /uv sync --quiet --frozen --only-group action --project/);
  assert.match(all, /astral-sh\/setup-uv@c18668ad3cf93ea998bef934396af7bb5c839dc7/);
  // Every action, language setups included, is pinned to a full commit SHA.
  for (const r of RUNNERS) for (const line of testWorkflow(opts(r, [])).split("\n").filter((l) => l.includes("uses:")))
    assert.match(line, /uses: [\w.-]+\/[\w.-]+@[0-9a-f]{40}( # v\d+(\.\d+)*)?$/, `${r}: ${line}`);
});

test("every run block is valid bash", (t) => {
  if (!bash) { t.skip("bash isn't available here"); return; }
  for (const { key, o } of cases.filter((c) => c.o.comments)) {
    const text = testWorkflow(o);
    // The run blocks, unindented, with ${{ }} expressions as plain words.
    const blocks = [...text.matchAll(/^( +)run: \|\n((?:\1  .*\n|\n)+)/gm)].map((m) => m[2]!.split("\n").map((l) => l.slice(m[1]!.length + 2)).join("\n"));
    assert.ok(blocks.length >= 2, key);
    for (const b of blocks) {
      const r = spawnSync(bash, ["-n"], { input: b.replace(/\$\{\{[^}]*\}\}/g, "X"), encoding: "utf8" });
      assert.equal(r.status, 0, `${key}: ${r.stderr}\n${b}`);
    }
    // The test scripts themselves.
    for (const m of text.matchAll(/<<'EOF'\n([\s\S]*?)\n *EOF/g)) {
      const body = m[1]!.split("\n").map((l) => l.replace(/^ {10}/, "")).join("\n");
      const r = spawnSync(bash, ["-n"], { input: body, encoding: "utf8" });
      assert.equal(r.status, 0, `${key}: ${r.stderr}\n${body}`);
    }
  }
});

test("the GitHub link: prefilled (with comments, else without) when it fits, else the file name only and the whole file to paste; never over 4,000", () => {
  const head = "https://github.com/acme/api/new/main?filename=.github%2Fworkflows%2Fstackvitals-tests.yml";
  let pasted = 0;
  for (const r of RUNNERS) {
    for (const fs of SETS) {
      const o = opts(r, fs), l = fileLink(o);
      assert.equal(l.comments, !l.url.includes("&value=") || new URL(l.url).searchParams.get("value") === testWorkflow(o), `${r} ${fs}`);
      assert.ok(l.url.length <= GH_LINK_MAX, `${r} ${fs}: ${l.url.length}`);
      if (l.paste) {
        pasted++;
        assert.equal(l.url, head, `${r} ${fs}: filename only`);
        assert.equal(l.paste, testWorkflow(o), "the whole file, comments kept, goes to the clipboard");
      } else {
        assert.ok(l.url.startsWith(head + "&value="), r);
        // Spaces as "+" and a literal "+" escaped, so the editor reads back exactly the file.
        assert.equal(new URL(l.url).searchParams.get("value"), testWorkflow({ ...o, comments: l.comments }), r);
      }
    }
  }
  // Measured: pytest with all six features is a 6,031-character link, which GitHub answered with a 500.
  const big = fileLink(opts("pytest", [...FEATURES]));
  assert.equal(big.url, head);
  assert.ok(big.paste && big.paste.includes("stackvitals ci"));
  // A short one stays fully prefilled.
  const small = fileLink(opts("go", []));
  assert.equal(small.paste, null);
  assert.equal(small.comments, true);
  // The usual choices fit once the comments are left out, rather than needing the paste.
  const usual = fileLink(opts("pytest", ["retry", "quarantine", "validate"]));
  assert.ok(usual.paste === null && usual.comments === false);
  assert.ok(small.url.includes("&value=") && small.url.length <= GH_LINK_MAX);
  assert.ok(pasted > 0 && pasted < RUNNERS.length * SETS.length, `${pasted} of ${RUNNERS.length * SETS.length} need the paste`);
});

test("the runner guess from test ids and job names", () => {
  assert.equal(guessRunner(["TestSettlement/concurrent_refunds", "TestWebhookRetry/timeout"], ["ci.yml / unit (go-test)"]).runner, "go");
  assert.equal(guessRunner(["checkout.spec.ts > applies coupon", "search.test.tsx > debounces input"], ["playwright / webkit", "playwright / chromium", "unit / vitest"]).runner, "vitest");
  assert.equal(guessRunner(["LoginViewModelTest.emitsError"], ["assembleRelease", "detekt", "connectedAndroidTest / api-30"]).runner, "gradle");
  assert.equal(guessRunner(["com.acme.PayTest.refunds"], ["build / mvn verify"]).runner, "maven");
  assert.equal(guessRunner(["tests/test_api.py::test_login"], ["CI / test"]).runner, "pytest");
  assert.equal(guessRunner(["Acme.Payments.Tests.RefundTests.Works"], []).runner, "dotnet");
  assert.equal(guessRunner(["./spec/models/user_spec.rb[1:1]"], []).runner, "rspec");
  const none = guessRunner(["smoke::boots"], ["build"]);
  assert.equal(none.runner, null);
  assert.deepEqual(guessRunner(["TestA/x"], []).ids, ["TestA/x"]);
  assert.equal(suggestShards(null), 2);
  assert.equal(suggestShards(18.9), 4);
  assert.equal(suggestShards(90), 8);
});
