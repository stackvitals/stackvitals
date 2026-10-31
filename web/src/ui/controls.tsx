// Form controls: segmented control with a sliding thumb, toggle switch, stepper and labelled fields.
import type { ComponentChildren, JSX } from "preact";
import { useLayoutEffect, useRef, useState } from "preact/hooks";
import { Icon } from "./icons";

export interface SegOption<T extends string | number> { value: T; label: ComponentChildren; aria?: string }

export function SegmentedControl<T extends string | number>({ options, value, onChange, label, size, scroll }: {
  options: SegOption<T>[]; value: T; onChange: (v: T) => void; label: string; size?: "sm"; scroll?: boolean;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [thumb, setThumb] = useState<{ x: number; w: number; ready: boolean }>({ x: 0, w: 0, ready: false });
  useLayoutEffect(() => {
    const place = () => {
      const el = box.current?.querySelector<HTMLElement>('[aria-checked="true"]');
      if (el) setThumb((t) => ({ x: el.offsetLeft, w: el.offsetWidth, ready: t.ready || t.w > 0 }));
    };
    place();
    const ro = typeof ResizeObserver === "function" ? new ResizeObserver(place) : null;
    if (box.current) ro?.observe(box.current);
    return () => ro?.disconnect();
  }, [value, options.length]);
  const onKey = (e: JSX.TargetedKeyboardEvent<HTMLDivElement>) => {
    const i = options.findIndex((o) => o.value === value);
    const d = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (!d) return;
    e.preventDefault();
    const next = options[(i + d + options.length) % options.length]!;
    onChange(next.value);
    requestAnimationFrame(() => box.current?.querySelector<HTMLElement>('[aria-checked="true"]')?.focus());
  };
  return <div class={"seg" + (size === "sm" ? " seg-sm" : "") + (scroll ? " seg-scroll" : "")} role="radiogroup" aria-label={label} ref={box} onKeyDown={onKey}>
    <span class={"seg-thumb" + (thumb.ready ? " is-ready" : "")} aria-hidden="true" style={{ width: `${thumb.w}px`, transform: `translateX(${thumb.x}px)` }} />
    {options.map((o) => <button type="button" role="radio" aria-checked={o.value === value} aria-label={o.aria} tabIndex={o.value === value ? 0 : -1}
      class="seg-opt" onClick={() => onChange(o.value)}>{o.label}</button>)}
  </div>;
}

export function Toggle({ checked, onChange, label, labelledBy, disabled }: { checked: boolean; onChange: (v: boolean) => void; label?: string; labelledBy?: string; disabled?: boolean }) {
  return <button type="button" role="switch" class="switch" aria-checked={checked} aria-label={label} aria-labelledby={labelledBy}
    disabled={disabled} onClick={() => onChange(!checked)}><span class="switch-knob" aria-hidden="true" /></button>;
}

export function Stepper({ value, onChange, min = 0, max = Infinity, step = 1, unit, label }: {
  value: number; onChange: (v: number) => void; min?: number; max?: number; step?: number; unit?: string; label: string;
}) {
  const clamp = (v: number) => Math.min(max, Math.max(min, Math.round(v / step) * step));
  const [draft, setDraft] = useState<string | null>(null);
  return <div class="stepper" role="group" aria-label={label}>
    <button type="button" class="press" aria-label={`Less ${label}`} disabled={value <= min} onClick={() => onChange(clamp(value - step))}>−</button>
    <input type="number" inputMode="decimal" aria-label={label} value={draft ?? String(value)} style={{ width: `max(60px, calc(${(draft ?? String(value)).length}ch + 26px))` }} min={min} max={Number.isFinite(max) ? max : undefined} step={step}
      onInput={(e) => setDraft(e.currentTarget.value)}
      onBlur={() => { if (draft !== null && draft !== "" && !Number.isNaN(+draft)) onChange(clamp(+draft)); setDraft(null); }}
      onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }} />
    {unit ? <span class="stepper-unit">{unit}</span> : null}
    <button type="button" class="press" aria-label={`More ${label}`} disabled={value >= max} onClick={() => onChange(clamp(value + step))}>+</button>
  </div>;
}

let fid = 0;
// A labelled field; pass the control as a render function to get the input id.
export function Field({ label, hint, error, children }: { label: string; hint?: ComponentChildren; error?: string | null; children: (id: string) => ComponentChildren }) {
  const id = useRef(`f-${++fid}`).current;
  return <div class={"field" + (error ? " has-error" : "")}>
    <label class="field-label" for={id}>{label}</label>
    {children(id)}
    {error ? <p class="field-error" role="alert"><Icon name="warn" />{error}</p> : hint ? <p class="field-hint">{hint}</p> : null}
  </div>;
}

type InputBase = { id?: string; value: string; onInput: (v: string) => void; placeholder?: string; disabled?: boolean };

export function TextInput(p: InputBase & { type?: "text" | "password" | "search" | "url" | "date"; mono?: boolean; maxLength?: number; autoFocus?: boolean; label?: string }) {
  return <input id={p.id} class={"input" + (p.mono ? " mono" : "")} type={p.type || "text"} value={p.value} placeholder={p.placeholder} disabled={p.disabled}
    maxLength={p.maxLength} autoComplete="off" spellcheck={false} aria-label={p.label} autoFocus={p.autoFocus} onInput={(e) => p.onInput(e.currentTarget.value)} />;
}

export function DateInput(p: InputBase & { min?: string }) {
  return <input id={p.id} class="input" type="date" value={p.value} min={p.min} disabled={p.disabled} onInput={(e) => p.onInput(e.currentTarget.value)} />;
}

export function NumberInput({ id, value, onInput, unit, min, max, step }: { id?: string; value: number; onInput: (v: number) => void; unit?: string; min?: number; max?: number; step?: number }) {
  return <span class="input-unit">
    <input id={id} class="input num" type="number" inputMode="decimal" value={String(value)} min={min} max={max} step={step}
      onInput={(e) => { const v = e.currentTarget.valueAsNumber; if (!Number.isNaN(v)) onInput(v); }} />
    {unit ? <span class="unit">{unit}</span> : null}
  </span>;
}

export function Select<T extends string>({ id, value, onChange, options, label }: { id?: string; value: T; onChange: (v: T) => void; options: { value: T; label: string }[]; label?: string }) {
  return <span class="select"><select id={id} class="input" value={value} aria-label={label} onChange={(e) => onChange(e.currentTarget.value as T)}>
    {options.map((o) => <option value={o.value}>{o.label}</option>)}
  </select><Icon name="chev" /></span>;
}

// A list of short strings (logins, globs): chips with remove buttons and an input that adds on Enter or comma.
export function Chips({ id, values, onChange, placeholder, label }: { id?: string; values: string[]; onChange: (v: string[]) => void; placeholder?: string; label: string }) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const parts = draft.split(",").map((s) => s.trim()).filter((s) => s && !values.includes(s));
    if (parts.length) onChange([...values, ...parts]);
    setDraft("");
  };
  return <div class="chips">
    {values.map((v) => <span class="chip">{v}<button type="button" class="chip-x press" aria-label={`Remove ${v}`} onClick={() => onChange(values.filter((x) => x !== v))}><Icon name="x" /></button></span>)}
    <input id={id} class="chip-input" value={draft} placeholder={placeholder || "Add"} aria-label={`Add to ${label}`}
      onInput={(e) => setDraft(e.currentTarget.value)} onBlur={add}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(); }
        else if (e.key === "Backspace" && !draft && values.length) onChange(values.slice(0, -1));
      }} />
  </div>;
}
