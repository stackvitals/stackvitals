// Page layout: a large title that hands over to the compact bar on scroll, sections with real h2 headings,
// cards and iOS inset grouped lists.
import type { ComponentChildren } from "preact";
import { useEffect, useRef } from "preact/hooks";
import { store } from "../data/store";
import { Icon, type IconName } from "./icons";

// The shell's top bar reads these: the page title and whether the large title has scrolled away.
export const pageTitle = store<{ title: string; compact: boolean }>({ title: "", compact: false });

export function Page({ title, subtitle, toolbar, children, wide }: {
  title: string; subtitle?: ComponentChildren; toolbar?: ComponentChildren; children?: ComponentChildren; wide?: boolean;
}) {
  const h1 = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    pageTitle.set({ title, compact: false });
    const el = h1.current;
    if (!el || typeof IntersectionObserver !== "function") return;
    // The compact title shows once the large one is under the top bar (56 px).
    const io = new IntersectionObserver(([e]) => pageTitle.set({ title, compact: !e!.isIntersecting }), { rootMargin: "-56px 0px 0px 0px" });
    io.observe(el);
    return () => io.disconnect();
  }, [title]);
  return <div class={"page" + (wide ? " page-wide" : "")}>
    <header class="page-head">
      <div class="page-titles">
        <h1 ref={h1} class="large-title">{title}</h1>
        {subtitle ? <p class="page-sub">{subtitle}</p> : null}
      </div>
      {toolbar ? <div class="page-tools">{toolbar}</div> : null}
    </header>
    {children}
  </div>;
}

let sid = 0;
export function Section({ title, description, action, info, children, id, class: cls }: {
  title: string; description?: ComponentChildren; action?: ComponentChildren; info?: ComponentChildren;
  children?: ComponentChildren; id?: string; class?: string;
}) {
  const hid = useRef(id ? `${id}-h` : `sec-${++sid}`);
  return <section class={"section" + (cls ? " " + cls : "")} id={id} aria-labelledby={hid.current}>
    <div class="section-head">
      <div class="section-titles">
        <h2 id={hid.current} class="section-title">{title}{info}</h2>
        {description ? <p class="section-desc">{description}</p> : null}
      </div>
      {action ? <div class="section-action">{action}</div> : null}
    </div>
    <div class="section-body">{children}</div>
  </section>;
}

// Two or three sections side by side on wide screens, one column on phones.
export function Columns({ children, ratio }: { children?: ComponentChildren; ratio?: "even" | "lead" }) {
  return <div class={"columns" + (ratio === "lead" ? " columns-lead" : "")}>{children}</div>;
}

export function Card({ children, pad = true, class: cls, tone }: { children?: ComponentChildren; pad?: boolean; class?: string; tone?: "good" | "bad" | "watch" | "accent" }) {
  return <div class={"card" + (pad ? " card-pad" : "") + (tone ? ` tone-${tone}` : "") + (cls ? " " + cls : "")}>{children}</div>;
}

export function GroupedList({ children, label }: { children?: ComponentChildren; label?: string }) {
  return <ul class="glist card" aria-label={label}>{children}</ul>;
}

export interface ListRowProps {
  title: ComponentChildren; subtitle?: ComponentChildren; leading?: ComponentChildren; icon?: IconName;
  trailing?: ComponentChildren; detail?: ComponentChildren; href?: string; external?: boolean; onClick?: () => void;
  label?: string; selected?: boolean; mono?: boolean;
}

export function ListRow(p: ListRowProps) {
  const body = <>
    {p.icon ? <span class="row-icon"><Icon name={p.icon} /></span> : p.leading ? <span class="row-lead">{p.leading}</span> : null}
    <span class="row-text">
      <span class={"row-title" + (p.mono ? " mono" : "")}>{p.title}</span>
      {p.subtitle ? <span class="row-sub">{p.subtitle}</span> : null}
    </span>
    {p.trailing ? <span class="row-trail">{p.trailing}</span> : null}
    {p.href || p.onClick ? <Icon name={p.external ? "external" : "right"} class="row-chev" /> : null}
  </>;
  const cls = "row" + (p.selected ? " is-selected" : "");
  return <li class="glist-item">
    {p.href ? <a class={cls + " row-action press"} href={p.href} aria-label={p.label} {...(p.external ? { target: "_blank", rel: "noopener noreferrer" } : {})}>{body}</a>
      : p.onClick ? <button type="button" class={cls + " row-action press"} aria-label={p.label} aria-pressed={p.selected} onClick={p.onClick}>{body}</button>
        : <div class={cls}>{body}</div>}
    {p.detail ? <div class="row-detail">{p.detail}</div> : null}
  </li>;
}

// A grid of figures: label, value and a note under it.
export function Stats({ children }: { children?: ComponentChildren }) {
  return <div class="stats card">{children}</div>;
}
export function Stat({ label, value, note, info }: { label: string; value: ComponentChildren; note?: ComponentChildren; info?: ComponentChildren }) {
  return <div class="stat"><div class="stat-label">{label}{info}</div><div class="stat-value num">{value}</div>{note ? <div class="stat-note">{note}</div> : null}</div>;
}
