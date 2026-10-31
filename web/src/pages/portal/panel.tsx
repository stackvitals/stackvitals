// A framed card with a header strip (title, then a short note), its body and an action bar at the foot; and label/value facts.
// Used by Portal, Where you stand and Explore.
import "./panel.css";
import type { ComponentChildren } from "preact";

export function Panel({ title, meta, tone, foot, flush, children, class: cls, id }: {
  title: ComponentChildren; meta?: ComponentChildren; tone?: "good" | "watch" | "bad"; foot?: ComponentChildren; flush?: boolean;
  children?: ComponentChildren; class?: string; id?: string;
}) {
  return <section class={"pn" + (tone ? ` pn-${tone}` : "") + (cls ? " " + cls : "")} id={id}>
    <header class="pn-strip"><h3 class="pn-title">{title}</h3>{meta ? <span class="pn-meta">{meta}</span> : null}</header>
    {children ? <div class={"pn-body" + (flush ? " is-flush" : "")}>{children}</div> : null}
    {foot ? <footer class="pn-foot">{foot}</footer> : null}
  </section>;
}

export type Fact = [string, ComponentChildren] | null | false | undefined;
export function Facts({ rows, cols }: { rows: Fact[]; cols?: number }) {
  return <dl class={"pn-facts" + (cols ? ` cols-${cols}` : "")}>{rows.filter((r): r is [string, ComponentChildren] => !!r).map(([k, v]) =>
    <div class="pn-fact"><dt>{k}</dt><dd>{v}</dd></div>)}</dl>;
}

// Numbered steps, each a heading, a line on what it does and its action.
export function Steps({ items }: { items: { title: string; text: ComponentChildren; action?: ComponentChildren; done?: boolean }[] }) {
  return <ol class="pn-steps">{items.map((s, i) => <li class={s.done ? "is-done" : ""}>
    <span class="pn-step-n num" aria-hidden="true">{i + 1}</span>
    <div class="pn-step-text"><p class="pn-step-h">{s.title}</p><div class="pn-step-p">{s.text}</div></div>
    {s.action ? <div class="pn-step-act">{s.action}</div> : null}
  </li>)}</ol>;
}
