// Explore's in-browser queries must give the rows `stackvitals sql` (DuckDB) gives for the SQL they print.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { QUESTIONS, columnsOf, run, toSql, type Query, type Row } from "../src/pages/explore/query";

const root = process.env.SV_REPO_ROOT || join(process.cwd(), "..");
const python = [join(root, ".venv", "Scripts", "python.exe"), join(root, ".venv", "bin", "python")].find(existsSync) || "python";

const iso = (d: number, h = 10) => new Date(Date.UTC(2026, 8, 1 + d, h, 7, 0)).toISOString().replace(/\.\d+Z$/, "Z");
const prs: Row[] = Array.from({ length: 23 }, (_, i) => ({
  number: 100 + i, status: i % 5 === 0 ? "OPEN" : "MERGED", author_kind: i % 7 === 3 ? "bot" : "person", role: i % 4 === 1 ? "outsider" : "insider",
  created_at: iso(i * 2), merged_at: i % 5 === 0 ? null : iso(i * 2 + 1, 23), pickup_s: i % 6 === 2 ? null : 600 + ((i * 7919) % 50000),
  additions: 10 + ((i * 37) % 300), deletions: (i * 13) % 90, draft: i % 9 === 0,
}));
const jobs: Row[] = Array.from({ length: 9 }, (_, i) => ({ workflow: `.github/workflows/w${i % 3}.yml`, job: `job ${i}`, state: i % 3 ? "ok" : "flaky",
  flake_events: (i * 5) % 11, failures: (i * 3) % 7, runs: 40 + i, flake_rate: ((i * 5) % 11) / (40 + i), prs_affected: i % 4, retry_minutes: i * 2.5 }));
const tests: Row[] = Array.from({ length: 6 }, (_, i) => ({ test_id: `t::case_${i}`, state: i % 2 ? "flaky" : "broken", failures: (i * 4) % 9, flake_events: i, runs: 30, message: i % 3 ? `it's ${i}` : null }));
const TABLES: Record<string, Row[]> = { prs, ci_jobs: jobs, tests };

const BUILT: Query[] = [
  { table: "prs", where: [{ col: "role", op: "!=", value: "insider" }], group: "status", aggs: [{ fn: "count" }, { fn: "avg", col: "additions" }, { fn: "max", col: "deletions" }] },
  { table: "prs", where: [{ col: "additions", op: ">=", value: "100" }, { col: "pickup_s", op: "set" }], select: ["number", "additions"], order: { col: "number", desc: true }, limit: 5 },
  { table: "prs", where: [{ col: "created_at", op: ">", value: "2026-09-20" }], group: "created_at", bucket: "month", aggs: [{ fn: "count" }, { fn: "sum", col: "pickup_s" }], order: { col: "month", desc: false } },
  { table: "prs", where: [{ col: "merged_at", op: "unset" }], select: ["number", "status"], order: { col: "number", desc: false } },
  { table: "tests", where: [{ col: "message", op: "contains", value: "IT'S" }], select: ["test_id", "message"], order: { col: "test_id", desc: false } },
  { table: "ci_jobs", where: [], aggs: [{ fn: "median", col: "retry_minutes" }, { fn: "min", col: "runs" }] },
  { table: "prs", where: [{ col: "draft", op: "=", value: "true" }], group: "created_at", bucket: "day", aggs: [{ fn: "count" }], order: { col: "day", desc: false } },
];

function duck(queries: string[]): Row[][] | null {
  const dir = mkdtempSync(join(tmpdir(), "sv-explore-"));
  try {
    mkdirSync(join(dir, "summary"));
    for (const [k, rows] of Object.entries(TABLES)) writeFileSync(join(dir, "summary", `${k}.jsonl`), rows.map((r) => JSON.stringify(r)).join("\n") + "\n");
    const script = `
import contextlib, io, json, sys, duckdb
from pathlib import Path
from stackvitals.core import sqlcli
out = []
for q in json.loads(sys.stdin.read()):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = sqlcli._run(duckdb, [("fixture", Path(sys.argv[1]))], q, True)
    out.append(json.loads(buf.getvalue()) if code == 0 else {"error": q})
print(json.dumps(out))
`;
    const r = spawnSync(python, ["-c", script, dir], { input: JSON.stringify(queries), encoding: "utf8", env: { ...process.env, PYTHONPATH: join(root, "src"), PYTHONIOENCODING: "utf-8" } });
    if (r.status !== 0) { console.log(r.stderr); return null; }
    return JSON.parse(r.stdout);
  } finally { rmSync(dir, { recursive: true, force: true }); }
}

// DuckDB's JSON prints dates as text and timestamps with a space; compare on the date and on numbers to 1e-6.
const norm = (v: unknown) => (v === null || v === undefined ? null : typeof v === "number" ? Math.round(v * 1e6) / 1e6
  : typeof v === "boolean" ? v : /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}/.test(String(v)) ? String(v).replace(" ", "T").slice(0, 19) : String(v));
const sortRows = (rows: unknown[][]) => rows.map((r) => JSON.stringify(r)).sort();

test("questions and built queries match DuckDB through stackvitals sql", (t) => {
  const qs = [...QUESTIONS.map((x) => x.q), ...BUILT];
  const sqls = qs.map((q) => toSql(q, columnsOf(TABLES[q.table]!)));
  const got = duck(sqls);
  if (!got) { t.skip("DuckDB (stackvitals[sql]) isn't installed here"); return; }
  qs.forEach((q, i) => {
    const mine = run(q, TABLES[q.table]!);
    const theirs = got[i] as unknown as Row[];
    assert.ok(Array.isArray(theirs), `SQL failed: ${sqls[i]}`);
    assert.equal(mine.rows.length, theirs.length, sqls[i]);
    const a = mine.rows.map((r) => mine.columns.map((c) => norm(r[c])));
    const b = theirs.map((r) => mine.columns.map((c) => norm(r[c])));
    // Ties can come back in either order; the row sets and the sort key's sequence must match.
    assert.deepEqual(sortRows(a), sortRows(b), sqls[i]);
    if (q.order) { const k = mine.columns.indexOf(q.order.col); assert.deepEqual(a.map((r) => r[k]), b.map((r) => r[k]), sqls[i]); }
  });
});

test("identifiers and values are quoted, so a value can't end the SQL", () => {
  const sql = toSql({ table: "tests", where: [{ col: "message", op: "=", value: "x'; drop table prs; --" }, { col: "odd col", op: "set" }], select: ["odd col"] }, columnsOf(tests));
  assert.match(sql, /'x''; drop table prs; --'/);
  assert.match(sql, /"odd col"/);
});
