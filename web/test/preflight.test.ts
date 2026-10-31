// "Check a planned pull request": the browser port gives the same file kinds, areas and gap sentences as flow/preflight.py.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { areas, basis, check, kinds, parsePaths, type Habits, type Published } from "../src/pages/prs/preflight";

const root = process.env.SV_REPO_ROOT || join(process.cwd(), "..");
const python = [join(root, ".venv", "Scripts", "python.exe"), join(root, ".venv", "bin", "python")].find(existsSync) || "python";

const HABITS: Habits = { scope: "whole repo", merged_prs: 105, include: { tests: 0.64, docs: 0.18, changelog: 0.71 }, size: { median_lines: 86, p75_lines: 210, p90_lines: 520 } };
const CASES: [string[], number][] = [
  [["src/app.ts"], 180],
  [["src/app.ts", "src/app.test.ts", "CHANGELOG.md"], 600],
  [["internal/ledger/post.go", "internal/ledger/post_test.go", "docs/ledger.md"], 40],
  [["lib/x.py", "tests/test_x.py", "changelog.d/123.bugfix.rst", "README.rst", "package-lock.json"], 521],
  [["README.md"], 520],
  [["a/b/c/d.kt", "news/1.feature", "spec/foo_spec.rb", "Docs/guide.adoc"], 1],
];

test("parsePaths splits on lines, commas and spaces and drops ./", () => {
  assert.deepEqual(parsePaths("./src/a.ts, src/b.ts\n/src/c.ts  src/a.ts\n"), ["src/a.ts", "src/b.ts", "src/c.ts"]);
});

test("the port matches flow/preflight.py", (t) => {
  const script = `
import json, sys
from stackvitals.flow.preflight import _kinds, gaps
from stackvitals.flow.knowledge import _areas
h = json.loads(sys.argv[1])
out = []
for paths, lines in json.loads(sys.argv[2]):
    out.append({"kinds": sorted(_kinds(paths)), "areas": sorted(_areas(paths)), "gaps": gaps({"paths": paths, "add": lines}, h)})
print(json.dumps(out))`;
  const run = spawnSync(python, ["-c", script, JSON.stringify(HABITS), JSON.stringify(CASES)], { cwd: root, encoding: "utf-8", env: { ...process.env, PYTHONPATH: join(root, "src") } });
  if (run.status !== 0) { t.skip(`python not available: ${run.stderr.slice(0, 200)}`); return; }
  const want = JSON.parse(run.stdout) as { kinds: string[]; areas: string[]; gaps: { what: string; why: string }[] }[];
  CASES.forEach(([paths, lines], i) => {
    assert.deepEqual([...kinds(paths)].sort(), want[i]!.kinds, `kinds ${paths}`);
    assert.deepEqual(areas(paths), want[i]!.areas, `areas ${paths}`);
    assert.deepEqual(check(paths, lines, HABITS).gaps, want[i]!.gaps, `gaps ${paths}`);
  });
});

test("size reads usual, bigger than most, or unusually big", () => {
  assert.equal(check([], 80, HABITS).size, "usual");
  assert.equal(check([], 300, HABITS).size, "big");
  assert.equal(check([], 521, HABITS).size, "unusual");
  assert.equal(check([], null, HABITS).size, null);
  // No files named: habits are expected, never reported missing.
  assert.equal(check([], 80, HABITS).rows.find((r) => r.what === "tests")!.verdict, "expected");
  assert.equal(check([], 80, HABITS).gaps.length, 0);
});

// Folder-scoped: flow.json's published per-folder habits (from flow/build.py) checked in the browser give the CLI's
// `flow preflight` answer for a planned PR in one folder; across folders the estimate is labelled and pools disjoint PRs exactly.
const FOLDER_SCRIPT = `
import json, sys
from datetime import datetime, timedelta, timezone
from stackvitals.flow.build import build
from stackvitals.flow.preflight import gaps, norms, preflight
now = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
def merged(n, paths, lines):
    t = (now - timedelta(days=n % 300 + 1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"t": "pr", "n": n, "st": "MERGED", "cr": t, "mg": t, "cl": t, "au": "alice", "at": "User", "as": "MEMBER",
            "rq": [], "ev": [], "cm": [], "paths": paths, "add": lines, "del": 0}
prs = [merged(n, ["src/app/a.ts"] + (["src/app/a.test.ts"] if n % 4 else []), 12 * n) for n in range(1, 31)]
prs += [merged(n, ["lib/core/b.py", "CHANGELOG.md"] + (["docs/b.md"] if n % 2 else []), 7 * n) for n in range(40, 58)]
prs += [merged(n, ["tools/x.sh"], 5) for n in range(60, 64)]
asks = {n: [["tests", "src/app"]] for n in range(1, 14)} | {n: [["docs", "src/app"]] for n in range(14, 18)}
h = build({"open": [], "closed": prs}, {}, now, owner="o", asks=asks)["habits"]
out = []
for paths, lines in json.loads(sys.argv[1]):
    cli = norms(prs, paths, now)
    out.append({"scope": cli["scope"], "merged_prs": cli["merged_prs"], "include": cli["include"], "size": cli["size"],
                "gaps": gaps({"paths": paths, "add": lines}, cli), "asks": preflight(prs, asks, paths, now)["asks"]})
print(json.dumps({"habits": h, "cli": out}))`;
const TWO: [string[], number] = [["src/app/x.ts", "lib/core/y.py"], 100];
const FOLDER_CASES: [string[], number][] = [
  [["src/app/new.ts"], 400],
  [["src/app/new.ts", "src/app/new.test.ts"], 50],
  [["lib/core/c.py"], 200],
  [["lib/core/c.py", "lib/core/test_c.py"], 10],
  [["tools/y.sh"], 30],
  [["brand/new/file.ts"], 30],
];

test("folder-scoped checks match the CLI's flow preflight", (t) => {
  const run = spawnSync(python, ["-c", FOLDER_SCRIPT, JSON.stringify([...FOLDER_CASES, TWO])], { cwd: root, encoding: "utf-8", env: { ...process.env, PYTHONPATH: join(root, "src") } });
  if (run.status !== 0) { t.skip(`python not available: ${run.stderr.slice(0, 200)}`); return; }
  const { habits, cli } = JSON.parse(run.stdout) as { habits: Published; cli: (Habits & { gaps: unknown[]; asks: unknown[] })[] };
  assert.ok(habits.folders?.some((f) => f.area === "src/app"), "src/app is published");
  FOLDER_CASES.forEach(([paths, lines], i) => {
    const want = cli[i]!, b = basis(paths, habits, ["src/app", "lib/core", "(root)", "docs", "tools"]);
    // "tools" has merged history but too little to publish: the CLI also falls back to the whole repo there.
    assert.equal(b.h.scope, want.scope, `scope ${paths}`);
    assert.equal(b.h.merged_prs, want.merged_prs, `merged ${paths}`);
    assert.deepEqual(b.h.include, want.include, `include ${paths}`);
    assert.deepEqual(b.h.size, want.size, `size ${paths}`);
    assert.deepEqual(check(paths, lines, b.h).gaps, want.gaps, `gaps ${paths}`);
    if (b.kind === "folder") assert.deepEqual(b.asks, want.asks.slice(0, 3), `asks ${paths}`);
  });
  assert.equal(basis(["src/app/new.ts"], habits).kind, "folder");
  assert.equal(basis(["brand/new/file.ts"], habits).kind, "repo");
  // Two folders: labelled an estimate; with no PR in both, counts and shares equal the CLI's pooled ones.
  const two = basis(TWO[0], habits, ["src/app", "lib/core"]), pooled = cli[FOLDER_CASES.length]!;
  assert.equal(two.kind, "folders");
  assert.equal(two.h.scope, pooled.scope);
  assert.equal(two.h.merged_prs, pooled.merged_prs);
  assert.deepEqual(two.h.include, pooled.include);
});
