// Small shared pieces: status pills (icon plus text, never colour alone), change pills, the info button and its
// explanation sheet, code blocks with copy, empty states, skeletons and toasts.
import type { ComponentChildren } from "preact";
import { useEffect, useRef, useState } from "preact/hooks";
import { store, useStore } from "../data/store";
import { deltaText, sameReading, toneOf, type Better, type Kind } from "../data/format";
import { Button } from "./Button";
import { Icon, type IconName } from "./icons";
import { Portal } from "./Portal";
import { Sheet } from "./Sheet";

export const DOCS = "https://github.com/stackvitals/stackvitals/blob/main/docs/";

export type PillTone = "good" | "bad" | "watch" | "neutral" | "accent";
const TONE_ICON: Record<PillTone, IconName> = { good: "check", bad: "warn", watch: "clock", neutral: "dot", accent: "dot" };

export function Pill({ tone = "neutral", icon, children, solid }: { tone?: PillTone; icon?: IconName | null; children?: ComponentChildren; solid?: boolean }) {
  const name = icon === null ? null : icon || TONE_ICON[tone];
  return <span class={`pill pill-${tone}${solid ? " is-solid" : ""}`}>{name ? <Icon name={name} /> : null}<span>{children}</span></span>;
}

// The state words the files use, as pills.
const STATE: Record<string, [PillTone, string]> = {
  flaky: ["bad", "Flaky"], broken: ["bad", "Failing"], suspect: ["watch", "Suspect"], fixed: ["good", "Fixed"], ok: ["good", "OK"],
  miss: ["bad", "Missed"], heads_up: ["watch", "Heads up"], elite: ["good", "Elite"], high: ["good", "High"], medium: ["watch", "Medium"],
  low: ["bad", "Low"], gold: ["good", "Gold"], silver: ["neutral", "Silver"], bronze: ["watch", "Bronze"],
};
export function StatePill({ value }: { value?: string | null }) {
  if (!value) return null;
  const [tone, word] = STATE[value] || ["neutral", value.replace(/_/g, " ")];
  return <Pill tone={tone}>{word}</Pill>;
}

// Arrow, amount and tone of a change; the label says it in words for screen readers.
export function ChangePill({ kind, from, to, better }: { kind: Kind; from: number; to: number; better: Better }) {
  const same = sameReading(kind, from, to);
  const tone = toneOf(better, kind, from, to);
  const dir = same ? "flat" : to > from ? "up" : "down";
  const amount = deltaText(kind, from, to);
  const said = same ? "No change" : `${dir === "up" ? "Up" : "Down"} ${amount}${tone !== "neutral" ? `, ${tone === "good" ? "better" : "worse"}` : ""}`;
  return <span class={`change change-${tone}`} role="img" aria-label={said} title={said}><Icon name={dir} /><span aria-hidden="true">{same ? "Flat" : amount}</span></span>;
}

export interface InfoContent { title: string; body: ComponentChildren; facts?: [string, ComponentChildren][]; doc?: string }

// The (i) button: opens a sheet that explains a number, with facts and a "Learn more" link.
export function InfoButton({ info, label }: { info: InfoContent; label?: string }) {
  const [open, setOpen] = useState(false);
  return <>
    <button type="button" class="info-btn press" aria-label={label || `How ${info.title} works`} onClick={(e) => { e.stopPropagation(); setOpen(true); }}>
      <Icon name="info" /></button>
    <Sheet open={open} onClose={() => setOpen(false)} title={info.title} size="sm"
      footer={<>{info.doc ? <Button variant="plain" href={info.doc[0] == "#" ? info.doc : DOCS + info.doc} external={info.doc[0] != "#"} iconEnd="external">Learn more</Button> : null}
        <Button variant="filled" onClick={() => setOpen(false)}>Done</Button></>}>
      <div class="info-body">{info.body}</div>
      {info.facts?.length ? <dl class="facts">{info.facts.map(([k, v]) => <div class="fact"><dt>{k}</dt><dd class="num">{v}</dd></div>)}</dl> : null}
    </Sheet>
  </>;
}

export async function copyText(text: string): Promise<boolean> {
  try { await navigator.clipboard.writeText(text); return true; } catch { return false; }
}

export function CopyButton({ text, label = "Copy", small }: { text: string; label?: string; small?: boolean }) {
  const [done, setDone] = useState(false);
  return <Button variant="tinted" size={small ? "sm" : "md"} icon={done ? "check" : "copy"}
    onClick={async () => { const ok = await copyText(text); setDone(ok); toast(ok ? "Copied" : "Copy failed: select the text instead", ok ? "good" : "bad"); setTimeout(() => setDone(false), 1600); }}>
    {done ? "Copied" : label}</Button>;
}

// Monospace is used only here: commands, config and prompts.
export function CodeBlock({ code, title, inline, note }: { code: string; title?: string; inline?: boolean; note?: ComponentChildren }) {
  if (inline) {
    return <div class="cmd-wrap"><div class="cmd"><code tabIndex={0}>{code}</code><CopyButton text={code} small /></div>{note ? <p class="cmd-note">{note}</p> : null}</div>;
  }
  return <div class="code"><div class="code-head"><span>{title || "Code"}</span><CopyButton text={code} small /></div><pre tabIndex={0}><code>{code}</code></pre>
    {note ? <p class="cmd-note">{note}</p> : null}</div>;
}

export function EmptyState({ icon = "about", title, children, action }: { icon?: IconName; title: string; children?: ComponentChildren; action?: ComponentChildren }) {
  return <div class="empty"><span class="empty-icon"><Icon name={icon} /></span><p class="empty-title">{title}</p>
    {children ? <div class="empty-body">{children}</div> : null}{action ? <div class="empty-action">{action}</div> : null}</div>;
}

export function Skeleton({ lines = 3, chart }: { lines?: number; chart?: boolean }) {
  return <div class="skeleton" aria-busy="true" aria-label="Loading">
    {chart ? <div class="sk sk-chart" /> : null}
    {Array.from({ length: lines }, (_, i) => <div class="sk sk-line" style={{ width: `${92 - i * 13}%` }} />)}
  </div>;
}

export function PageSkeleton() {
  return <div class="page" aria-busy="true"><div class="sk sk-title" /><div class="sk sk-sub" /><Skeleton chart lines={4} /></div>;
}

// Toasts: one at a time, announced politely.
const toasts = store<{ id: number; text: string; tone: "good" | "bad" | "neutral" } | null>(null);
let tid = 0;
export function toast(text: string, tone: "good" | "bad" | "neutral" = "good"): void {
  toasts.set({ id: ++tid, text, tone });
}

export function ToastHost() {
  const t = useStore(toasts);
  const [shown, setShown] = useState(false);
  const timer = useRef(0);
  useEffect(() => {
    if (!t) return;
    setShown(true);
    clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setShown(false), 2800);
  }, [t?.id]);
  return <Portal><div class={"toast" + (shown ? " is-open" : "") + (t ? ` toast-${t.tone}` : "")} role="status" aria-live="polite">
    {t ? <><Icon name={t.tone === "bad" ? "warn" : "check"} /><span>{t.text}</span></> : null}</div></Portal>;
}
