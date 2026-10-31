// Structured blocks shared by Delivery, Pull Requests and Investment: a table under its own heading strip, a framed
// panel with an action bar, label/value facts and a "from your machine" panel that says why it can't run here.
import "./blocks.css";
import type { ComponentChildren } from "preact";

// A table (or any block) with a visible heading on its frame.
export function Framed({ title, note, action, children, class: cls }: { title: string; note?: ComponentChildren; action?: ComponentChildren; children: ComponentChildren; class?: string }) {
  return <div class={"blk-tbl" + (cls ? " " + cls : "")}><div class="blk-tbl-h"><h3>{title}</h3>{note ? <span class="blk-tbl-note">{note}</span> : null}
    {action ? <span class="blk-tbl-act">{action}</span> : null}</div>{children}</div>;
}

// A heading inside a section, for a group of figures or panels.
export function SubHead({ title, note }: { title: string; note?: ComponentChildren }) {
  return <h3 class="blk-h">{title}{note ? <span class="blk-h-note">{note}</span> : null}</h3>;
}

// A framed card: a heading strip (title, then an optional state), the body, then an optional action bar.
export function Panel({ title, state, bar, children, class: cls, tone }: { title: ComponentChildren; state?: ComponentChildren; bar?: ComponentChildren;
  children?: ComponentChildren; class?: string; tone?: "good" | "watch" | "bad" }) {
  return <section class={"blk-panel" + (tone ? ` blk-${tone}` : "") + (cls ? " " + cls : "")}>
    <div class="blk-panel-h"><h3>{title}</h3>{state ? <span class="blk-panel-state">{state}</span> : null}</div>
    {children ? <div class="blk-panel-b">{children}</div> : null}
    {bar ? <div class="blk-bar" role="group">{bar}</div> : null}
  </section>;
}

export type Fact = [string, ComponentChildren];
// Label/value rows; a falsy row is left out.
export function Facts({ rows, class: cls }: { rows: (Fact | null | false | undefined)[]; class?: string }) {
  const shown = rows.filter((r): r is Fact => !!r);
  return shown.length ? <dl class={"blk-facts" + (cls ? " " + cls : "")}>{shown.map(([k, v]) => <div class="blk-fact"><dt>{k}</dt><dd>{v}</dd></div>)}</dl> : null;
}

// A state as a mark and a word (Instrument draws the mark over the base small dot).
export function Mark({ tone, children }: { tone: "good" | "watch" | "bad" | "neutral" | "accent"; children: ComponentChildren }) {
  return <span class={`blk-mark blk-mark-${tone}`}><i aria-hidden="true" />{children}</span>;
}

// Something that truly has to run on the user's machine: what it does, why it can't run in the app, what it needs.
export function Machine({ title, does, why, needs, children }: { title: string; does: ComponentChildren; why: ComponentChildren; needs: ComponentChildren; children: ComponentChildren }) {
  return <Panel title={title} state={<Mark tone="neutral">From your machine</Mark>} class="blk-machine">
    <Facts rows={[["What it does", does], ["Why not in the app", why], ["What it needs", needs]]} />
    <div class="blk-machine-cmd">{children}</div>
  </Panel>;
}
