// How numbers read: hours as "3.5 h" or "2.1 days", shares as percentages, times as "12 min ago".
type N = number | null | undefined;
const missing = (x: N): x is null | undefined => x === null || x === undefined || Number.isNaN(x);

export function hours(h: N): string {
  if (missing(h)) return "–";
  if (h >= 48) return `${(h / 24).toFixed(1)} days`;
  if (h >= 1) return `${h.toFixed(1)} h`;
  return `${Math.round(h * 60)} min`;
}

export function secs(s: N): string {
  if (missing(s)) return "–";
  if (s >= 3600) return hours(s / 3600);
  if (s >= 60) return `${Math.round(s / 60)} min`;
  return `${Math.round(s)} s`;
}

export function pct(x: N, digits = 0): string {
  return missing(x) ? "–" : `${(x * 100).toFixed(digits)}%`;
}

export function count(n: number, one: string, many = one + "s"): string {
  return `${n.toLocaleString("en-US")} ${n === 1 ? one : many}`;
}

export function day(stamp: string | null | undefined): string {
  return stamp ? String(stamp).slice(0, 10) : "–";
}

export function parseStamp(stamp: string | null | undefined): number {
  return stamp ? Date.parse(String(stamp).replace(" UTC", "Z").replace(" ", "T")) : NaN;
}

export function ago(stamp: string | null | undefined, now = Date.now()): string {
  if (!stamp) return "never";
  const t = parseStamp(stamp);
  if (Number.isNaN(t)) return String(stamp);
  const m = Math.round((now - t) / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m} min ago`;
  if (m < 48 * 60) return `${Math.round(m / 60)} h ago`;
  return `${Math.round(m / 1440)} days ago`;
}

export function short(text: unknown, n = 80): string {
  const s = String(text ?? "");
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
// "2026-10-12" as "Oct 12"; "2026-10" or "26/10" as "Oct".
export function dateLabel(s: string): string {
  let m = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (m) return `${MONTHS[+m[2]! - 1]} ${+m[3]!}`;
  m = s.match(/^(\d{4})-(\d{2})$/);
  if (m) return MONTHS[+m[2]! - 1]!;
  m = s.match(/^(\d{2})\/(\d{2})$/);
  if (m) return MONTHS[+m[2]! - 1]!;
  return s;
}

export function csv<R>(rows: R[], columns: { label: string; key: string; raw?: (r: R) => unknown }[]): string {
  const esc = (v: unknown) => {
    let s = v === null || v === undefined ? "" : typeof v === "object" ? JSON.stringify(v) : String(v);
    // Text a spreadsheet would run as a formula is kept as text.
    if (typeof v === "string" && /^[=+\-@\t\r]/.test(s)) s = `'${s}`;
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [columns.map((c) => esc(c.label)).join(","), ...rows.map((r) => columns.map((c) => esc(c.raw ? c.raw(r) : (r as Record<string, unknown>)[c.key])).join(","))].join("\n");
}

// Value kinds the charts and watchlists format with.
export type Kind = "share" | "secs" | "hours" | "count" | "percent";

export function fmt(kind: Kind, v: N): string {
  if (missing(v)) return "–";
  switch (kind) {
    case "share": return pct(v);
    case "percent": return `${v.toFixed(1)}%`;
    case "secs": return secs(v);
    case "hours": return hours(v);
    default: return Math.round(v).toLocaleString("en-US");
  }
}

// The change between two values in words: "8 pts", "2 min", "12".
export function deltaText(kind: Kind, a: number, b: number): string {
  const d = Math.abs(b - a);
  if (kind === "share") { const p = Math.round(d * 100); return `${p} ${p === 1 ? "pt" : "pts"}`; }
  if (kind === "percent") return `${d.toFixed(1)} pts`;
  return fmt(kind, d);
}

// Two values that read the same once formatted count as no change.
export function sameReading(kind: Kind, a: number, b: number): boolean {
  return a === b || Number(deltaText(kind, a, b).replace(/[^0-9.]/g, "")) === 0;
}

export type Better = "up" | "down" | null;
export type Tone = "good" | "bad" | "neutral";

export function toneOf(better: Better, kind: Kind, a: number, b: number): Tone {
  if (!better || sameReading(kind, a, b)) return "neutral";
  return (better === "up") === b > a ? "good" : "bad";
}
