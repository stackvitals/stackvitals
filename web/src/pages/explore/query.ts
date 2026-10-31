// A small query engine over the summary tables, run in the browser: filter, group (by a value, or a date's day, week or
// month), count and aggregate, sort and limit. Each query also prints as DuckDB SQL that gives the same rows (a test compares).
export type Row = Record<string, unknown>;
export type Op = "=" | "!=" | ">" | ">=" | "<" | "<=" | "contains" | "set" | "unset";
export interface Cond { col: string; op: Op; value?: string }
export type Fn = "count" | "sum" | "avg" | "median" | "min" | "max";
export interface Agg { fn: Fn; col?: string }
export type Bucket = "day" | "week" | "month";
// A computed column: its SQL and the same value in JS (questions only; the builder uses plain columns).
export interface Derived { as: string; sql: string; f: (r: Row) => unknown }
export interface Query {
  table: string; where: Cond[]; group?: string | null; bucket?: Bucket | null; aggs?: Agg[];
  select?: (string | Derived)[]; order?: { col: string; desc: boolean } | null; limit?: number;
}
export interface Result { columns: string[]; rows: Row[] }

export const OPS: { value: Op; label: string }[] = [{ value: "=", label: "is" }, { value: "!=", label: "is not" }, { value: ">", label: "more than" },
  { value: ">=", label: "at least" }, { value: "<", label: "less than" }, { value: "<=", label: "at most" }, { value: "contains", label: "contains" },
  { value: "set", label: "has a value" }, { value: "unset", label: "is empty" }];
export const FNS: { value: Fn; label: string }[] = [{ value: "median", label: "Median" }, { value: "avg", label: "Average" }, { value: "sum", label: "Sum" },
  { value: "min", label: "Smallest" }, { value: "max", label: "Largest" }, { value: "count", label: "Count with a value" }];

// Columns named *_s hold seconds: aggregates on them read in hours, rounded to 0.1.
export const isSecs = (col?: string) => !!col && /_s$/.test(col);
const isDate = (v: unknown) => typeof v === "string" && /^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$/.test(v);

export interface ColInfo { name: string; kind: "number" | "date" | "text" | "bool"; values: string[] }
// Each column's kind from its values, and its distinct values when there are few (for pick lists).
export function columnsOf(rows: Row[]): ColInfo[] {
  const names: string[] = [];
  for (const r of rows) for (const k of Object.keys(r)) if (!names.includes(k)) names.push(k);
  return names.map((name) => {
    const vals = rows.map((r) => r[name]).filter((v) => v !== null && v !== undefined && v !== "");
    const kind = vals.length && vals.every((v) => typeof v === "number") ? "number" : vals.length && vals.every((v) => typeof v === "boolean") ? "bool"
      : vals.length && vals.every(isDate) ? "date" : "text";
    const distinct = [...new Set(vals.filter((v) => typeof v !== "object").map(String))].sort();
    return { name, kind, values: distinct.length <= 40 ? distinct : [] };
  });
}

export const ident = (s: string) => (/^[a-z_][a-z0-9_]*$/.test(s) ? s : `"${s.replace(/"/g, '""')}"`);
const lit = (v: string, num: boolean) => (num && v.trim() !== "" && Number.isFinite(Number(v)) ? String(Number(v)) : `'${v.replace(/'/g, "''")}'`);
export const alias = (a: Agg) => (a.fn === "count" && !a.col ? "rows" : `${a.fn}_${isSecs(a.col) ? a.col!.replace(/_s$/, "_hours") : a.col}`);

// DuckDB's round(): half away from zero.
export function round(x: number, d: number): number {
  const m = 10 ** d;
  return Math.sign(x) * Math.round(Math.abs(x) * m + 1e-9) / m;
}

function bucketOf(v: unknown, b: Bucket): string | null {
  if (!isDate(v)) return null;
  const t = new Date(String(v).length === 10 ? `${v}T00:00:00Z` : String(v));
  if (Number.isNaN(t.getTime())) return null;
  const d = new Date(Date.UTC(t.getUTCFullYear(), t.getUTCMonth(), b === "month" ? 1 : t.getUTCDate()));
  if (b === "week") d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7));
  return d.toISOString().slice(0, 10);
}

function cmp(a: unknown, b: unknown): number {
  if (a === b) return 0;
  if (a === null || a === undefined) return 1;
  if (b === null || b === undefined) return -1;
  return typeof a === "number" && typeof b === "number" ? a - b : String(a) < String(b) ? -1 : 1;
}

const ms = (v: unknown) => new Date(String(v).length === 10 ? `${v}T00:00:00Z` : String(v)).getTime();
function test(r: Row, c: Cond, kind?: ColInfo["kind"]): boolean {
  const num = kind === "number", date = kind === "date";
  const v = r[c.col];
  const empty = v === null || v === undefined || v === "";
  if (c.op === "set") return !empty;
  if (c.op === "unset") return v === null || v === undefined;
  if (empty) return false;
  const w = c.value ?? "";
  if (c.op === "contains") return String(v).toLowerCase().includes(w.toLowerCase());
  const x: number | string = num ? Number(v) : date && c.op !== "=" && c.op !== "!=" ? ms(v) : String(v);
  const y: number | string = num ? Number(w) : date && c.op !== "=" && c.op !== "!=" ? ms(w) : w;
  if ((num || typeof y === "number") && !Number.isFinite(y as number)) return false;
  switch (c.op) {
    case "=": return x === y;
    case "!=": return x !== y;
    case ">": return x > y;
    case ">=": return x >= y;
    case "<": return x < y;
    default: return x <= y;
  }
}

function median(xs: number[]): number | null {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b), m = s.length >> 1;
  return s.length % 2 ? s[m]! : (s[m - 1]! + s[m]!) / 2;
}

function aggregate(rows: Row[], a: Agg): number | null {
  if (a.fn === "count") return a.col ? rows.filter((r) => r[a.col!] !== null && r[a.col!] !== undefined).length : rows.length;
  const xs = rows.map((r) => r[a.col!]).filter((v): v is number => typeof v === "number");
  if (!xs.length) return null;
  const v = a.fn === "sum" ? xs.reduce((s, x) => s + x, 0) : a.fn === "avg" ? xs.reduce((s, x) => s + x, 0) / xs.length
    : a.fn === "median" ? median(xs)! : a.fn === "min" ? Math.min(...xs) : Math.max(...xs);
  if (isSecs(a.col)) return round(v / 3600, 1);
  return a.fn === "avg" || a.fn === "median" ? round(v, 2) : v;
}

export function run(q: Query, data: Row[], cols: ColInfo[] = columnsOf(data)): Result {
  const kind = (c: string) => cols.find((x) => x.name === c)?.kind;
  const kept = data.filter((r) => q.where.every((c) => test(r, c, kind(c.col))));
  let rows: Row[], columns: string[];
  if (q.group || (q.aggs && q.aggs.length)) {
    const aggs = q.aggs?.length ? q.aggs : [{ fn: "count" as const }];
    const key = q.group ? (q.bucket ? q.bucket : q.group) : null;
    const groups = new Map<string, { k: unknown; rows: Row[] }>();
    for (const r of kept) {
      const k = q.group ? (q.bucket ? bucketOf(r[q.group], q.bucket) : r[q.group] ?? null) : null;
      const id = JSON.stringify(k);
      if (!groups.has(id)) groups.set(id, { k, rows: [] });
      groups.get(id)!.rows.push(r);
    }
    if (!q.group && !groups.size) groups.set("null", { k: null, rows: [] });
    columns = [...(key ? [key] : []), ...aggs.map(alias)];
    rows = [...groups.values()].map((g) => ({ ...(key ? { [key]: g.k } : {}), ...Object.fromEntries(aggs.map((a) => [alias(a), aggregate(g.rows, a)])) }));
  } else {
    const sel = q.select?.length ? q.select : cols.map((c) => c.name);
    columns = sel.map((s) => (typeof s === "string" ? s : s.as));
    rows = kept.map((r) => Object.fromEntries(sel.map((s) => (typeof s === "string" ? [s, r[s] ?? null] : [s.as, s.f(r)]))));
  }
  if (q.order) {
    const o = q.order;
    rows = rows.map((r, i) => ({ r, i })).sort((a, b) => {
      const x = a.r[o.col], y = b.r[o.col];
      // Nulls last either way, as DuckDB orders them.
      if (x === null || x === undefined) return y === null || y === undefined ? a.i - b.i : 1;
      if (y === null || y === undefined) return -1;
      return (o.desc ? -cmp(x, y) : cmp(x, y)) || a.i - b.i;
    }).map((x) => x.r);
  }
  return { columns, rows: q.limit ? rows.slice(0, q.limit) : rows };
}

function aggSql(a: Agg): string {
  if (a.fn === "count") return a.col ? `count(${ident(a.col)})` : "count(*)";
  const inner = `${a.fn}(${ident(a.col!)})`;
  return isSecs(a.col) ? `round(${inner} / 3600, 1)` : a.fn === "avg" || a.fn === "median" ? `round(${inner}, 2)` : inner;
}

// The same query as DuckDB SQL, for the SQL explorer and `stackvitals sql`.
export function toSql(q: Query, cols: ColInfo[] = [], table = q.table): string {
  const num = (c: string) => cols.find((x) => x.name === c)?.kind === "number";
  const date = (c: string) => cols.find((x) => x.name === c)?.kind === "date";
  const where = q.where.map((c) => {
    const col = ident(c.col);
    if (c.op === "set") return `${col} is not null${num(c.col) ? "" : ` and cast(${col} as varchar) <> ''`}`;
    if (c.op === "unset") return `${col} is null`;
    if (c.op === "contains") return `contains(lower(cast(${col} as varchar)), ${lit((c.value || "").toLowerCase(), false)})`;
    const v = c.value ?? "";
    const op = c.op === "!=" ? "<>" : c.op;
    if (num(c.col)) return `${col} ${op} ${lit(v, true)}`;
    if (date(c.col) && op !== "=" && op !== "<>") return `cast(${col} as timestamp) ${op} cast(${lit(v, false)} as timestamp)`;
    return `cast(${col} as varchar) ${op} ${lit(v, false)}`;
  });
  let select: string, group = "";
  if (q.group || (q.aggs && q.aggs.length)) {
    const aggs = q.aggs?.length ? q.aggs : [{ fn: "count" as const }];
    const g = q.group ? (q.bucket ? `cast(date_trunc('${q.bucket}', cast(${ident(q.group)} as timestamp)) as date) as ${q.bucket}` : ident(q.group)) : null;
    select = [...(g ? [g] : []), ...aggs.map((a) => `${aggSql(a)} as ${ident(alias(a))}`)].join(", ");
    if (q.group) group = "\ngroup by 1";
  } else {
    select = q.select?.length ? q.select.map((s) => (typeof s === "string" ? ident(s) : `${s.sql} as ${ident(s.as)}`)).join(", ") : "*";
  }
  const order = q.order ? `\norder by ${ident(q.order.col)}${q.order.desc ? " desc" : ""}` : "";
  return `select ${select}\nfrom ${ident(table)}${where.length ? `\nwhere ${where.join("\n  and ")}` : ""}${group}${order}${q.limit ? `\nlimit ${q.limit}` : ""}`;
}

// The explorer names DevLake-shaped tables without their prefix; `stackvitals sql` keeps the file name.
export const explorerTable = (t: string) => t.replace(/^devlake_/, "");

export interface Question { title: string; about: string; q: Query; hours?: string[] }
export const QUESTIONS: Question[] = [
  { title: "Pull requests merged per week, with median pickup", about: "People's pull requests only; pickup is opened to first review.",
    q: { table: "prs", where: [{ col: "merged_at", op: "set" }, { col: "author_kind", op: "=", value: "person" }], group: "merged_at", bucket: "week",
      aggs: [{ fn: "count" }, { fn: "median", col: "pickup_s" }], order: { col: "week", desc: false } } },
  { title: "Insiders and outside contributors", about: "Pull requests, how many merged and the median pickup, by the author's role.",
    q: { table: "prs", where: [{ col: "author_kind", op: "=", value: "person" }], group: "role",
      aggs: [{ fn: "count" }, { fn: "count", col: "merged_at" }, { fn: "median", col: "pickup_s" }], order: { col: "rows", desc: true } } },
  { title: "Flakiest CI jobs", about: "Jobs that failed and then passed on the same code most often.",
    q: { table: "ci_jobs", where: [], select: ["workflow", "job", "state", "flake_events", "failures", "runs", "flake_rate", "prs_affected", "retry_minutes"],
      order: { col: "flake_events", desc: true }, limit: 20 } },
  { title: "Tests that fail most", about: "Failures, flakes and the latest message for each test.",
    q: { table: "tests", where: [], select: ["test_id", "state", "failures", "flake_events", "runs", "message"], order: { col: "failures", desc: true }, limit: 20 } },
  { title: "Biggest open pull requests", about: "Open pull requests by lines changed.",
    q: { table: "prs", where: [{ col: "status", op: "=", value: "OPEN" }],
      select: ["number", "author_kind", "role", { as: "lines", sql: "additions + deletions", f: (r) => (typeof r.additions === "number" && typeof r.deletions === "number" ? r.additions + r.deletions : null) }, "created_at"],
      order: { col: "lines", desc: true }, limit: 20 } },
];
