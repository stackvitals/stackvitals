// A metric over time, as every chart, watchlist row and headline reads it.
import type { ComponentChildren } from "preact";
import { dateLabel, fmt, type Better, type Kind } from "../data/format";
import type { InfoContent } from "../ui/bits";

export type Period = "week" | "month" | "day";
export interface Point { label: string; value: number; n?: number }
export interface Metric {
  id: string; name: string; sub?: ComponentChildren; kind: Kind; better: Better; period: Period; points: Point[];
  meaning?: (v: number, p: Point) => string; info?: InfoContent;
}

export const RANGES: Record<Period, { n: number; label: string; aria: string }[]> = {
  week: [{ n: 4, label: "4W", aria: "4 weeks" }, { n: 8, label: "8W", aria: "8 weeks" }, { n: 12, label: "12W", aria: "12 weeks" }],
  month: [{ n: 3, label: "3M", aria: "3 months" }, { n: 6, label: "6M", aria: "6 months" }, { n: 12, label: "12M", aria: "12 months" }],
  day: [{ n: 30, label: "30D", aria: "30 days" }, { n: 60, label: "60D", aria: "60 days" }, { n: 90, label: "90D", aria: "90 days" }],
};

// Builds points from [date, value] pairs, dropping missing values.
export function points(rows: [string, number | null | undefined, ...unknown[]][] | undefined): Point[] {
  return (rows || []).filter((r) => r[1] !== null && r[1] !== undefined && !Number.isNaN(r[1])).map((r) => ({ label: dateLabel(String(r[0])), value: r[1] as number }));
}

export function slice(m: Metric, n: number): Point[] {
  return m.points.slice(-n);
}

export function whenText(p: Period, label: string): string {
  return p === "week" ? `Week of ${label}` : label;
}

export function niceTicks(lo: number, hi: number, count: number): number[] {
  const span = hi - lo;
  if (!(span > 0)) return [lo];
  const raw = span / count, mag = Math.pow(10, Math.floor(Math.log10(raw))), nm = raw / mag;
  const step = (nm < 1.5 ? 1 : nm < 3 ? 2 : nm < 7 ? 5 : 10) * mag, out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}

export function yRange(vals: number[], kind: Kind): [number, number] {
  if (!vals.length) return [0, 1];
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = (hi - lo) * 0.3 || Math.abs(hi) * 0.1 || 1;
  let a = Math.max(0, lo - pad), b = hi + pad;
  if (kind === "share") b = Math.min(1, b);
  if (a === b) b = a + 1;
  return [a, b];
}

export function axisText(kind: Kind, v: number, step: number): string {
  if (kind === "share") return (step < 0.01 ? (v * 100).toFixed(1) : String(Math.round(v * 100))) + "%";
  if (kind === "percent") return `${+v.toFixed(1)}%`;
  if (kind === "secs") return v >= 60 ? `${+(v / 60).toFixed(1)}m` : `${Math.round(v)}s`;
  if (kind === "hours") return `${+v.toFixed(1)}h`;
  return fmt("count", v);
}
