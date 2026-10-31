// Explore's tools: ready questions and a query builder that run on the summary tables in this browser, each with the
// same query as SQL for the SQL explorer or `stackvitals sql`.
import { useEffect, useState } from "preact/hooks";
import { table } from "../../data/files";
import { useStore } from "../../data/store";
import { current } from "../../data/repos";
import { Button } from "../../ui/Button";
import { CodeBlock, CopyButton, EmptyState, Skeleton } from "../../ui/bits";
import { Field, SegmentedControl, Select, TextInput } from "../../ui/controls";
import { Table, type Column } from "../../ui/Table";
import { Panel } from "../portal/panel";
import { FNS, OPS, QUESTIONS, columnsOf, explorerTable, isSecs, run, toSql, type Agg, type Bucket, type ColInfo, type Cond, type Fn, type Query, type Result, type Row } from "./query";

// Each table's rows, loaded once per repo.
const cache = new Map<string, Promise<Row[] | null>>();
export function useRows(name: string | null): Row[] | null | undefined {
  const repo = useStore(current);
  const [rows, setRows] = useState<Row[] | null | undefined>(undefined);
  useEffect(() => {
    if (!name) { setRows(null); return; }
    let live = true;
    const key = `${repo.id}|${name}`;
    if (!cache.has(key)) cache.set(key, table<Row>(name, repo.source));
    setRows(undefined);
    cache.get(key)!.then((r) => live && setRows(r));
    return () => { live = false; };
  }, [repo.id, name]);
  return rows;
}

const label = (c: string) => (c === "rows" ? "Rows" : c.replace(/_s$/, " (seconds)").replace(/_/g, " ").replace(/^./, (x) => x.toUpperCase()));
function cell(v: unknown, c: string): string {
  if (v === null || v === undefined || v === "") return "–";
  if (typeof v === "number") return /_hours$/.test(c) ? `${v.toLocaleString()} h` : Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString(undefined, { maximumFractionDigits: 3 });
  if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(v)) return v.slice(0, 16).replace("T", " ");
  return Array.isArray(v) ? v.join(", ") : String(v);
}

export function ResultTable({ res, name }: { res: Result; name: string }) {
  const cols: Column<Row>[] = res.columns.map((c, i) => ({ key: c, label: label(c), primary: i === 0,
    num: res.rows.some((r) => typeof r[c] === "number"), nowrap: /(_id|^job|^workflow|_at)$/.test(c) || res.rows.every((r) => String(r[c] ?? "").length <= 12), raw: (r: Row) => r[c] as unknown, render: (r: Row) => cell(r[c], c) }));
  return <Table name={name} rows={res.rows.map((r, i) => ({ ...r, __i: i }))} columns={cols} limit={25}
    empty={<EmptyState icon="explore" title="No rows match.">Loosen a filter or pick another table.</EmptyState>} />;
}

// The query as one shell line for `stackvitals sql`.
const shell = (sql: string) => `"${sql.replace(/\s*\n\s*/g, " ").replace(/(["\\$`])/g, "\\$1")}"`;
export const sqlCommand = (repo: string, sql: string) => `stackvitals sql --repo ${repo} ${shell(sql)}`;

function Ways({ repo, sql, explorer, explorerSql }: { repo: string; sql: string; explorer: string | null; explorerSql: string }) {
  const [show, setShow] = useState(false);
  return <>
    {explorer ? <Button variant="tinted" href={`${explorer}#sql=${encodeURIComponent(explorerSql)}`} external iconEnd="external">Open in the SQL explorer</Button> : null}
    <Button variant="plain" expanded={show} onClick={() => setShow(!show)} iconEnd={show ? "up" : "down"}>{show ? "Hide the SQL" : "Show the SQL"}</Button>
    <CopyButton text={sqlCommand(repo, sql)} label="Copy as a command" />
    {show ? <div class="ex-sql"><CodeBlock title="SQL" code={sql} /></div> : null}
  </>;
}

export function Questions({ repo, explorer, tables }: { repo: string; explorer: string | null; tables: string[] }) {
  const ok = QUESTIONS.map((x, i) => ({ ...x, i })).filter((x) => tables.includes(x.q.table));
  const [pick, setPick] = useState(ok[0]?.i ?? 0);
  const q = QUESTIONS[pick]!;
  const rows = useRows(ok.length ? q.q.table : null);
  if (!ok.length) return <Panel title="No question fits these tables"><p>The ready questions read prs, ci_jobs and tests; use the query builder below on the tables here.</p></Panel>;
  const cols = rows ? columnsOf(rows) : [];
  const res = rows ? run(q.q, rows, cols) : null;
  const sql = toSql(q.q, cols);
  return <div class="ex-ask">
    <div class="ex-qs" role="group" aria-label="Questions">{ok.map((x) => <button type="button" class={"ex-q press" + (x.i === pick ? " is-on" : "")} aria-pressed={x.i === pick} onClick={() => setPick(x.i)}>
      <span class="ex-q-t">{x.title}</span><span class="ex-q-s">{x.about}</span></button>)}</div>
    <Panel title={q.title} meta={res ? `${res.rows.length.toLocaleString()} rows from ${q.q.table}` : q.q.table} class="ex-result"
      foot={<Ways repo={repo} sql={sql} explorer={explorer} explorerSql={toSql(q.q, cols, explorerTable(q.q.table))} />}>
      {rows === undefined ? <Skeleton lines={4} /> : rows === null ? <EmptyState icon="explore" title={`No ${q.q.table} table here.`} /> : <ResultTable res={res!} name={q.title.toLowerCase().replace(/\W+/g, "-")} />}
    </Panel>
  </div>;
}

const LIMITS = ["10", "20", "50", "100", "500"];
const blank = (): Cond => ({ col: "", op: "=", value: "" });

export function Builder({ repo, explorer, tables, start }: { repo: string; explorer: string | null; tables: string[]; start: string }) {
  const [name, setName] = useState(start);
  useEffect(() => { setName(start); reset(); }, [start]);
  const [where, setWhere] = useState<Cond[]>([]);
  const [group, setGroup] = useState("");
  const [bucket, setBucket] = useState<Bucket>("week");
  const [fn, setFn] = useState<Fn | "">("");
  const [col, setCol] = useState("");
  const [order, setOrder] = useState("");
  const [desc, setDesc] = useState<"desc" | "asc">("desc");
  const [limit, setLimit] = useState("50");
  const rows = useRows(name || null);
  function reset() { setWhere([]); setGroup(""); setFn(""); setCol(""); setOrder(""); }
  const cols: ColInfo[] = rows ? columnsOf(rows) : [];
  const plain = cols.filter((c) => !rows?.some((r) => Array.isArray(r[c.name]) || (r[c.name] !== null && typeof r[c.name] === "object")));
  const nums = cols.filter((c) => c.kind === "number");
  const g = plain.find((c) => c.name === group);
  const aggs: Agg[] = group || fn ? [{ fn: "count" }, ...(fn && (fn === "count" || col) ? [{ fn: fn as Fn, col: col || undefined }] : [])] : [];
  const conds = where.filter((c) => c.col && (c.op === "set" || c.op === "unset" || (c.value ?? "") !== ""));
  const base: Query = { table: name, where: conds, group: group || null, bucket: g?.kind === "date" ? bucket : null, aggs };
  const outCols = rows ? run({ ...base, limit: 1 }, rows, cols).columns : [];
  const q: Query = { ...base, order: order && outCols.includes(order) ? { col: order, desc: desc === "desc" } : null, limit: Number(limit) };
  const res = rows ? run(q, rows, cols) : null;
  const sql = toSql(q, cols);
  const setCond = (i: number, c: Partial<Cond>) => setWhere(where.map((x, j) => (i === j ? { ...x, ...c } : x)));
  const colOpts = (list: ColInfo[]) => list.map((c) => ({ value: c.name, label: c.name }));
  return <div class="ex-build">
    <Panel title="Query" meta={rows ? `${rows.length.toLocaleString()} rows, ${cols.length} columns in ${name}` : name}>
      <div class="ex-form">
        <Field label="Table">{(id) => <Select id={id} value={name} onChange={(v) => { setName(v); reset(); }} options={tables.map((t) => ({ value: t, label: t }))} />}</Field>
        <Field label="Group by" hint="One row per value; leave it off to list rows.">{(id) => <Select id={id} value={group} onChange={setGroup}
          options={[{ value: "", label: "No grouping" }, ...colOpts(plain)]} />}</Field>
        {g?.kind === "date" ? <div class="field"><span class="field-label">Dates by</span><SegmentedControl label="Dates by" value={bucket} onChange={setBucket}
          options={[{ value: "day", label: "Day" }, { value: "week", label: "Week" }, { value: "month", label: "Month" }]} /></div> : null}
        <Field label="Measure" hint={group ? "Rows are always counted; add one more figure." : "Adding one sums up the whole table in one row."}>{(id) => <Select id={id} value={fn}
          onChange={(v) => { setFn(v); if (v && v !== "count" && !nums.some((c) => c.name === col)) setCol(nums[0]?.name || ""); }}
          options={[{ value: "", label: group ? "Rows only" : "None: list rows" }, ...FNS.filter((f) => f.value === "count" || nums.length).map((f) => ({ value: f.value, label: f.label }))]} />}</Field>
        {fn ? <Field label="Of" hint={isSecs(col) ? "Seconds, shown in hours." : undefined}>{(id) => <Select id={id} value={col} onChange={setCol}
          options={fn === "count" ? colOpts(plain) : colOpts(nums)} />}</Field> : null}
        <Field label="Sort by">{(id) => <Select id={id} value={order} onChange={setOrder} options={[{ value: "", label: "As stored" }, ...outCols.map((c) => ({ value: c, label: label(c) }))]} />}</Field>
        {order ? <div class="field"><span class="field-label">Order</span><SegmentedControl label="Order" value={desc} onChange={setDesc}
          options={[{ value: "desc", label: "Largest first" }, { value: "asc", label: "Smallest first" }]} /></div> : null}
        <Field label="At most">{(id) => <Select id={id} value={limit} onChange={setLimit} options={LIMITS.map((l) => ({ value: l, label: `${l} rows` }))} />}</Field>
      </div>
      <div class="ex-filters">
        <p class="ex-sub">Filters</p>
        {where.map((c, i) => { const info = plain.find((x) => x.name === c.col); const needs = c.op !== "set" && c.op !== "unset";
          return <div class="ex-filter">
            <Select label={`Filter ${i + 1}: column`} value={c.col} onChange={(v) => setCond(i, { col: v, value: "" })} options={[{ value: "", label: "Column" }, ...colOpts(plain)]} />
            <Select label={`Filter ${i + 1}: test`} value={c.op} onChange={(v) => setCond(i, { op: v })} options={OPS.filter((o) => info?.kind === "number" || info?.kind === "date" || !/[<>]/.test(o.value))} />
            {needs ? (info?.values.length && c.op !== "contains" && info.kind !== "number" && info.kind !== "date"
              ? <Select label={`Filter ${i + 1}: value`} value={c.value || ""} onChange={(v) => setCond(i, { value: v })} options={[{ value: "", label: "Value" }, ...info.values.map((v) => ({ value: v, label: v }))]} />
              : <TextInput label={`Filter ${i + 1}: value`} value={c.value || ""} onInput={(v) => setCond(i, { value: v })} placeholder={info?.kind === "date" ? "2026-01-31" : "Value"} />) : <span />}
            <Button size="sm" variant="plain" icon="x" label={`Remove filter ${i + 1}`} onClick={() => setWhere(where.filter((_, j) => j !== i))} />
          </div>; })}
        {where.length < 4 ? <Button size="sm" variant="tinted" icon="plus" onClick={() => setWhere([...where, blank()])} disabled={!rows}>Add a filter</Button> : null}
      </div>
    </Panel>
    <Panel title="Result" meta={res ? `${res.rows.length.toLocaleString()} rows` : ""} class="ex-result"
      foot={rows ? <Ways repo={repo} sql={sql} explorer={explorer} explorerSql={toSql(q, cols, explorerTable(name))} /> : null}>
      {rows === undefined ? <Skeleton lines={4} /> : rows === null ? <EmptyState icon="explore" title={`No ${name} table here.`} /> : <ResultTable res={res!} name={`${name}-query`} />}
    </Panel>
  </div>;
}
