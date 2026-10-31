// A table people can filter, sort and download; on phones each row becomes a stacked card with labels.
import type { ComponentChildren } from "preact";
import { useMemo, useState } from "preact/hooks";
import { csv } from "../data/format";
import { Button } from "./Button";
import { Select, TextInput } from "./controls";
import { Icon } from "./icons";
import { EmptyState } from "./bits";

export interface Column<R> {
  key: string; label: string; render?: (r: R) => ComponentChildren; raw?: (r: R) => unknown; num?: boolean; filter?: boolean;
  // The column that names the row: it heads each stacked card on phones.
  primary?: boolean;
  // Ids, versions and file names: kept on one line at desktop widths.
  nowrap?: boolean;
}

function download(name: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

const rowId = (r: unknown, i: number): string | number => {
  const o = r as Record<string, unknown>;
  return (o.id ?? o.key ?? o.number ?? o.n ?? o.pr ?? o.name ?? i) as string | number;
};

export function Table<R>({ rows, columns, name = "rows", empty, initialSort, limit = 50, search = true, caption }: {
  rows: R[] | null | undefined; columns: Column<R>[]; name?: string; empty?: ComponentChildren; initialSort?: { key: string; desc: boolean };
  limit?: number; search?: boolean; caption?: string;
}) {
  const [q, setQ] = useState("");
  const [sort, setSort] = useState(initialSort || null);
  const [picks, setPicks] = useState<Record<string, string>>({});
  const [shown, setShown] = useState(limit);
  const value = (c: Column<R>, r: R) => (c.raw ? c.raw(r) : (r as Record<string, unknown>)[c.key]);
  const filtered = useMemo(() => {
    const words = q.trim().toLowerCase();
    let out = (rows || []).filter((r) => (!words || columns.some((c) => String(value(c, r) ?? "").toLowerCase().includes(words)))
      && Object.entries(picks).every(([k, v]) => !v || String(value(columns.find((c) => c.key === k)!, r)) === v));
    if (sort) {
      const c = columns.find((x) => x.key === sort.key)!;
      out = [...out].sort((a, b) => {
        const x = value(c, a) as number | string | null, y = value(c, b) as number | string | null;
        if (x === y) return 0;
        if (x === null || x === undefined) return 1;
        if (y === null || y === undefined) return -1;
        return (x < y ? -1 : 1) * (sort.desc ? -1 : 1);
      });
    }
    return out;
  }, [rows, q, sort, picks]);
  if (!rows || !rows.length) return <>{empty || <EmptyState title="Nothing here yet." />}</>;
  const options = (c: Column<R>) => [...new Set(rows.map((r) => String(value(c, r) ?? "")).filter(Boolean))].sort();
  const tools = search && rows.length > 6;
  return <div class="table-wrap card">
    {tools ? <div class="table-tools">
      <span class="search-field"><Icon name="search" /><TextInput type="search" value={q} onInput={setQ} placeholder="Filter rows" label={`Filter ${caption || "rows"}`} /></span>
      {columns.filter((c) => c.filter).map((c) => <Select label={`Filter by ${c.label}`} value={picks[c.key] || ""}
        onChange={(v) => setPicks({ ...picks, [c.key]: v })}
        options={[{ value: "", label: `Any ${c.label.toLowerCase()}` }, ...options(c).map((o) => ({ value: o, label: o }))]} />)}
      <span class="table-count" aria-live="polite">{filtered.length} of {rows.length}</span>
      <Button size="sm" variant="plain" icon="down" onClick={() => download(`${name}.csv`, csv(filtered, columns))}>CSV</Button>
    </div> : null}
    <div class="table-scroll">
      <table class="table">
        {caption ? <caption class="sr">{caption}</caption> : null}
        <thead><tr>{columns.map((c) => <th scope="col" class={c.num ? "is-num" : ""} aria-sort={sort?.key === c.key ? (sort.desc ? "descending" : "ascending") : "none"}>
          <button type="button" class="th-btn" onClick={() => setSort({ key: c.key, desc: sort?.key === c.key ? !sort.desc : !!c.num })}>
            {c.label}<Icon name={sort?.key === c.key ? (sort.desc ? "down" : "up") : "chev"} class={sort?.key === c.key ? "is-on" : ""} /></button></th>)}</tr></thead>
        <tbody>{filtered.slice(0, shown).map((r, i) => <tr key={rowId(r, i)}>{columns.map((c) =>
          <td data-label={c.label} class={(c.num ? "is-num num" : "") + (c.primary ? " is-primary" : "") + (c.nowrap ? " is-nowrap" : "")}>{c.render ? c.render(r) : String(value(c, r) ?? "–")}</td>)}</tr>)}</tbody>
      </table>
    </div>
    {filtered.length > shown ? <div class="table-more"><Button variant="plain" onClick={() => setShown(shown + limit)}>Show {Math.min(limit, filtered.length - shown)} more of {filtered.length - shown}</Button></div> : null}
  </div>;
}
