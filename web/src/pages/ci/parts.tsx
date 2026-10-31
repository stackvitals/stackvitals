// CI Health building blocks: a table under its own heading strip, a framed panel with an action bar, label/value facts,
// this week against the four before as a table, and the confirm/dispute tally.
import type { ComponentChildren } from "preact";
import { pct } from "../../data/format";
import type { CiChange, CiJson } from "../../data/types";
import { EmptyState, Pill } from "../../ui/bits";
import { Card } from "../../ui/Page";
import { Table } from "../../ui/Table";

// A table (or any block) with a visible heading on its frame.
export function Framed({ title, note, action, children }: { title: string; note?: ComponentChildren; action?: ComponentChildren; children: ComponentChildren }) {
  return <div class="ci-tbl"><div class="ci-tbl-h"><h3>{title}</h3>{note ? <span class="ci-tbl-note">{note}</span> : null}
    {action ? <span class="ci-tbl-act">{action}</span> : null}</div>{children}</div>;
}

// A framed card: a heading strip (title, then an optional state), the body, then an optional action bar.
export function Panel({ title, state, bar, children, class: cls }: { title: string; state?: ComponentChildren; bar?: ComponentChildren; children?: ComponentChildren; class?: string }) {
  return <section class={"ci-panel" + (cls ? " " + cls : "")}>
    <div class="ci-panel-h"><h3>{title}</h3>{state ? <span class="ci-panel-state">{state}</span> : null}</div>
    {children ? <div class="ci-panel-b">{children}</div> : null}
    {bar ? <div class="ci-bar" role="group" aria-label={`${title}: actions`}>{bar}</div> : null}
  </section>;
}

export type Fact = [string, ComponentChildren];
// Label/value rows; a falsy row is left out.
export function Facts({ rows }: { rows: (Fact | null | false | undefined)[] }) {
  return <dl class="ci-facts">{rows.filter((r): r is Fact => !!r).map(([k, v]) => <div class="ci-fact"><dt>{k}</dt><dd>{v}</dd></div>)}</dl>;
}

// This week against the four before, as the digest reads it: what moved beyond noise and what held.
export function ThisWeek({ changes }: { changes: CiChange[] }) {
  const run = changes.filter((c) => !c.note && !c.shown_with);
  if (!run.length) return <Card><EmptyState icon="clock" title="Too few runs this week to compare.">This week is set against the four weeks before once there are enough runs.</EmptyState></Card>;
  const fmt = (c: CiChange, v: number | null | undefined, base?: boolean) => (v === null || v === undefined ? "–"
    : c.unit === "share" ? pct(v) : c.unit === "count" ? `${v}${base ? " a week" : ""}` : `${(+v).toFixed(1)} ${c.unit}`);
  const size = (c: CiChange) => (!c.detectable ? "–" : c.unit === "share" ? `${Math.round(c.detectable * 100)} points`
    : `${c.detectable >= 3 ? Math.round(c.detectable) : c.detectable.toFixed(1)}×`);
  const rows = run.map((c, i) => ({ id: c.metric || String(i), c }));
  return <Framed title="This week against the four before" note="As the weekly digest reads it.">
    <Table name="this-week" caption="This week against the four weeks before" search={false} rows={rows} columns={[
      { key: "label", label: "Measure", primary: true, raw: (r) => r.c.label, render: (r) => <span class="ci-cap">{r.c.label}</span> },
      { key: "now", label: "This week", num: true, raw: (r) => r.c.now, render: (r) => fmt(r.c, r.c.now) },
      { key: "base", label: "Four weeks before", num: true, raw: (r) => r.c.base, render: (r) => fmt(r.c, r.c.base, true) },
      { key: "moved", label: "Moved", raw: (r) => (r.c.changed ? r.c.direction || "moved" : "steady"),
        render: (r) => (r.c.changed ? <Pill tone="watch" icon={r.c.direction === "up" ? "up" : "down"}>{r.c.direction === "up" ? "Rose" : "Fell"}</Pill>
          : <Pill tone="neutral" icon={null}>Steady within noise</Pill>) },
      { key: "detectable", label: "Smallest change it would catch", raw: (r) => r.c.detectable ?? null, render: (r) => size(r.c) },
    ]} />
  </Framed>;
}

export function Feedback({ fb }: { fb: NonNullable<CiJson["verdict_feedback"]> }) {
  const rows = Object.entries(fb).map(([state, c]) => ({ state, ...c }));
  return <Framed title="Confirmed and disputed calls" note="From your team's /stackvitals confirm and dispute commands.">
    <Table name="verdict-feedback" caption="Verdict feedback" search={false} rows={rows} columns={[
      { key: "state", label: "What it said", primary: true, render: (r) => <span class="ci-cap">{r.state === "unknown" ? "not in the findings" : r.state}</span> },
      { key: "confirmed", label: "Confirmed", num: true }, { key: "disputed", label: "Disputed", num: true },
      { key: "share", label: "Right", num: true, render: (r) => pct(r.share) },
      { key: "range", label: "Likely range", raw: (r) => r.low, render: (r) => `${pct(r.low)} to ${pct(r.high)}` }]} />
  </Framed>;
}

// A plain on-page jump (smooth unless reduced motion is asked for).
export function jump(id: string) {
  const el = document.getElementById(id);
  if (!el) return;
  el.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
}
