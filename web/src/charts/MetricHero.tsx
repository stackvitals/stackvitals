// The headline chart: metric name, a big number that follows the crosshair, the change since the range started,
// what the number means, the range control, and the scrub chart. Paired with a Watchlist that picks the metric.
import type { ComponentChildren } from "preact";
import { useEffect, useRef, useState } from "preact/hooks";
import { fmt, toneOf } from "../data/format";
import { prefs } from "../data/store";
import { ChangePill, InfoButton } from "../ui/bits";
import { SegmentedControl } from "../ui/controls";
import { tween } from "../ui/motion";
import { RANGES, slice, whenText, type Metric } from "./metric";
import { ScrubChart } from "./ScrubChart";
import { Sparkline } from "./Sparkline";

// The range picked for each period, shared by every hero and watchlist on the page.
export function useRange(): [Record<string, number>, (period: string, n: number) => void] {
  const [r, setR] = useState<Record<string, number>>(() => prefs.get("ranges", { week: 12, month: 6, day: 90 }));
  return [r, (period, n) => { const next = { ...r, [period]: n }; setR(next); prefs.set("ranges", next); }];
}

function BigNumber({ text }: { text: string }) {
  // The unit is set smaller than the digits: "78%" reads as 78 and a small %.
  const m = text.match(/^([^\d–-]*)([\d.,–-]+)(.*)$/);
  if (!m) return <>{text}</>;
  return <>{m[1]}{m[2]}{m[3] ? <small>{m[3]}</small> : null}</>;
}

export function MetricHero({ metric, ranges, setRange, height = 300, extra }: {
  metric: Metric; ranges: Record<string, number>; setRange: (period: string, n: number) => void; height?: number; extra?: ComponentChildren;
}) {
  const opts = RANGES[metric.period];
  const n = ranges[metric.period] || opts[opts.length - 1]!.n;
  const pts = slice(metric, n);
  const [at, setAt] = useState<number | null>(null);
  const [shown, setShown] = useState<number | null>(null);
  const last = pts.length - 1;
  const i = at === null ? last : Math.min(at, last);
  const p = pts[i];
  const first = pts[0];
  // Count up to a new value when the metric or range changes (not while scrubbing).
  const prev = useRef<{ id: string; v: number } | null>(null);
  useEffect(() => {
    if (!p) return;
    const from = prev.current && prev.current.id === metric.id && at === null ? prev.current.v : null;
    prev.current = { id: metric.id, v: p.value };
    if (from === null || at !== null || from === p.value) { setShown(p.value); return; }
    return tween(480, (t) => setShown(from + (p.value - from) * t));
  }, [metric.id, p?.value, at]);
  if (!p || !first) return null;
  const tone = toneOf(metric.better, metric.kind, first.value, pts[last]!.value);
  const visible = opts.filter((o) => o.n < metric.points.length || o === opts.find((x) => x.n >= metric.points.length));
  const span = metric.period === "week" ? "weeks" : metric.period === "month" ? "months" : "days";
  return <div class="hero">
    <div class="hero-head">
      <div class="hero-figure">
        <div class="hero-name"><span>{metric.name}</span>{metric.info ? <InfoButton info={metric.info} /> : null}</div>
        <div class="hero-num num"><BigNumber text={fmt(metric.kind, at === null ? (shown ?? p.value) : p.value)} /></div>
        <div class="hero-meta">
          {pts.length > 1 ? <ChangePill kind={metric.kind} from={first.value} to={p.value} better={metric.better} /> : null}
          <span class="hero-date">{at === null ? (pts.length > 1 ? `over ${pts.length} ${span}` : whenText(metric.period, p.label)) : `${whenText(metric.period, p.label)}, vs ${first.label}`}</span>
        </div>
        {metric.meaning ? <p class="hero-meaning">{metric.meaning(p.value, p)}</p> : null}
      </div>
      {visible.length > 1 ? <div class="hero-tools"><SegmentedControl label="Time range" value={Math.min(n, visible[visible.length - 1]!.n)}
        onChange={(v) => setRange(metric.period, v)} options={visible.map((o) => ({ value: o.n, label: o.label, aria: o.aria }))} /></div> : null}
    </div>
    <p class="sr" aria-live="polite">{metric.name}: {fmt(metric.kind, pts[last]!.value)} now{pts.length > 1 ? `, ${fmt(metric.kind, first.value)} ${pts.length} ${span} ago` : ""}.</p>
    {pts.length > 1 ? <ScrubChart labels={pts.map((x) => x.label)} series={[pts.map((x) => x.value)]} kind={metric.kind}
      tone={tone === "neutral" ? "neutral" : tone} base={first.value} height={height} label={`${metric.name} over ${pts.length} ${span}`}
      flag={(k) => whenText(metric.period, pts[k]?.label || "")} onScrub={setAt} reveal={`${metric.id}:${n}`} />
      : <p class="hero-note">One {metric.period} of history so far; the chart draws once there are two.</p>}
    {extra}
  </div>;
}

export interface WatchItem {
  id: string; name: string; sub?: ComponentChildren; value: string; values?: number[];
  change?: ComponentChildren; trailing?: ComponentChildren; info?: Metric["info"];
}

export function metricItem(m: Metric, n: number): WatchItem {
  const pts = slice(m, n), a = pts[0], b = pts[pts.length - 1];
  return { id: m.id, name: m.name, sub: m.sub, value: fmt(m.kind, b?.value), values: pts.map((x) => x.value), info: m.info,
    change: a && b && pts.length > 1 ? <ChangePill kind={m.kind} from={a.value} to={b.value} better={m.better} /> : null };
}

// Stocks-style rows: name, sparkline, value and change. Picking a row charts it in the hero.
export function Watchlist({ items, selected, onSelect, label, tones }: {
  items: WatchItem[]; selected?: string; onSelect?: (id: string) => void; label: string; tones?: Record<string, "good" | "bad" | "neutral">;
}) {
  return <ul class="watch card" aria-label={label}>
    {items.map((m) => {
      const sel = m.id === selected;
      const body = <>
        <span class="watch-name"><b>{m.name}</b>{m.sub ? <small>{m.sub}</small> : null}</span>
        {m.values && m.values.length > 1 ? <Sparkline values={m.values} tone={tones?.[m.id] || "neutral"} /> : m.trailing ? <span class="watch-trail">{m.trailing}</span> : <span />}
        <span class="watch-val"><b class="num">{m.value}</b>{m.change}</span>
      </>;
      return <li class={"watch-row" + (sel ? " is-selected" : "")}>
        {onSelect && m.values && m.values.length > 1
          ? <button type="button" class="watch-main press" aria-pressed={sel} onClick={() => onSelect(m.id)} aria-label={`${m.name}, ${m.value}. Show on the chart`}>{body}</button>
          : <div class="watch-main">{body}</div>}
        {m.info ? <InfoButton info={m.info} /> : null}
      </li>;
    })}
  </ul>;
}

export function trendTones(ms: Metric[], ranges: Record<string, number>): Record<string, "good" | "bad" | "neutral"> {
  const out: Record<string, "good" | "bad" | "neutral"> = {};
  for (const m of ms) {
    const pts = slice(m, ranges[m.period] || 12);
    out[m.id] = pts.length > 1 ? toneOf(m.better, m.kind, pts[0]!.value, pts[pts.length - 1]!.value) : "neutral";
  }
  return out;
}
