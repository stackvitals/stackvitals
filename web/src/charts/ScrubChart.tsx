// The scrub chart (uPlot, loaded in its own chunk): an area or line that draws in, a crosshair that reports the point
// under the finger, mouse or arrow keys, and a dashed line where the range started.
import type uPlot from "uplot";
import { useEffect, useRef, useState } from "preact/hooks";
import type { Kind } from "../data/format";
import { useStore } from "../data/store";
import { cssVar, paint } from "../data/theme";
import { reduced, tween, easeInOut } from "../ui/motion";
import { axisText, niceTicks, yRange } from "./metric";

let lib: Promise<typeof uPlot> | null = null;
const load = () => (lib ||= import("uplot").then((m) => m.default));

export type ChartTone = "good" | "bad" | "neutral" | "accent";
export interface ScrubChartProps {
  labels: string[]; series: number[][]; kind: Kind; tone?: ChartTone; height?: number; type?: "area" | "line";
  base?: number | null; onScrub?: (i: number | null) => void; label: string; flag?: (i: number) => string;
  // Changing this replays the draw-in (a new range or metric).
  reveal?: string;
}

const TONE_VAR: Record<ChartTone, string> = { good: "--good", bad: "--bad", neutral: "--ink", accent: "--accent" };
const MULTI = ["--accent", "--ink-2", "--watch"];

function rgba(color: string, a: number): string {
  const m = color.match(/^#([0-9a-f]{6})$/i);
  if (m) { const n = parseInt(m[1]!, 16); return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`; }
  const d = color.match(/\d+(\.\d+)?/g);
  return d ? `rgba(${d[0]},${d[1]},${d[2]},${a})` : color;
}

export function ScrubChart(p: ScrubChartProps) {
  const wrap = useRef<HTMLDivElement>(null);
  const host = useRef<HTMLDivElement>(null);
  const flagEl = useRef<HTMLDivElement>(null);
  const plot = useRef<uPlot | null>(null);
  const props = useRef(p);
  props.current = p;
  const reveal = useRef(1);
  const stopAnim = useRef<() => void>(() => {});
  const keyIdx = useRef<number | null>(null);
  const [ready, setReady] = useState(false);
  const tick = useStore(paint);

  // (Re)build the plot when the shape, colours or data change.
  useEffect(() => {
    let dead = false;
    load().then((U) => {
      if (dead || !host.current || !wrap.current) return;
      plot.current?.destroy();
      const P = props.current;
      const n = P.labels.length;
      const multi = P.series.length > 1;
      // Instrument sets the series order (--chart-1..3) and axis font (--chart-font); the fallbacks cover them being unset.
      const color = (i: number) => multi ? cssVar(`--chart-${(i % 3) + 1}`) || cssVar(MULTI[i % 3]!) : cssVar(TONE_VAR[P.tone || "neutral"]);
      const ink2 = cssVar("--ink-2"), ink3 = cssVar("--ink-3"), line = cssVar("--line"), surface = cssVar("--surface");
      const all = P.series.flat();
      const yr = yRange(all, P.kind);
      const base = P.type === "line" || multi ? null : P.base;
      const path = U.paths.spline ? U.paths.spline() : U.paths.linear!();
      const paths: uPlot.Series.PathBuilder = (u, si, i0, i1) => {
        const out = path(u, si, i0, i1);
        if (out && reveal.current < 1) {
          const c = new Path2D();
          c.rect(0, 0, u.bbox.left + u.bbox.width * reveal.current, u.ctx.canvas.height);
          out.clip = c;
        }
        return out;
      };
      const font = cssVar("--chart-font") || '600 12.5px "Plus Jakarta Sans", system-ui, sans-serif';
      const flat = cssVar("--chart-area") === "flat";
      const dpr = devicePixelRatio || 1;
      const u = new U({
        width: wrap.current.clientWidth, height: P.height || 300, padding: [26, 4, 0, 22], legend: { show: false },
        cursor: {
          x: true, y: false, drag: { x: false, y: false, setScale: false },
          points: { size: 12, width: 3, stroke: () => surface, fill: (_u, si) => color(si - 1) },
        },
        scales: { x: { time: false, range: () => [0, Math.max(1, n - 1)] }, y: { range: () => yr } },
        axes: [
          { stroke: ink2, font, grid: { show: false }, ticks: { show: false }, gap: 8, size: 32,
            splits: (uu) => { const w = uu.bbox.width / dpr, max = Math.max(2, Math.floor(w / 70)), step = Math.ceil(n / max), out: number[] = [];
              for (let i = n - 1; i >= 0; i -= step) out.unshift(i); return out; },
            values: (_u, sp) => sp.map((i) => P.labels[Math.round(i)] || "") },
          { side: 1, stroke: ink2, font, ticks: { show: false }, gap: 8, size: 56, grid: { stroke: line, width: 1 },
            splits: () => niceTicks(yr[0], yr[1], 4), values: (_u, sp) => sp.map((v) => axisText(P.kind, v, sp.length > 1 ? sp[1]! - sp[0]! : 1)) },
        ],
        series: [{}, ...P.series.map((_, i) => ({
          stroke: color(i), width: multi ? 2.25 : 2.75, dash: multi ? [[], [8, 5], [2, 4]][i % 3] : undefined, paths, points: { show: n === 1 },
          fill: multi || P.type === "line" ? undefined : flat ? rgba(color(i), 0.08) : (uu: uPlot) => {
            const g = uu.ctx.createLinearGradient(0, uu.bbox.top, 0, uu.bbox.top + uu.bbox.height);
            g.addColorStop(0, rgba(color(i), 0.22)); g.addColorStop(1, rgba(color(i), 0));
            return g;
          },
        }))],
        hooks: {
          drawAxes: [(uu) => {
            if (base === null || base === undefined) return;
            const y = Math.round(uu.valToPos(base, "y", true)) + 0.5, ctx = uu.ctx;
            ctx.save(); ctx.setLineDash([3 * dpr, 4 * dpr]); ctx.strokeStyle = ink3; ctx.lineWidth = dpr;
            ctx.beginPath(); ctx.moveTo(uu.bbox.left, y); ctx.lineTo(uu.bbox.left + uu.bbox.width, y); ctx.stroke(); ctx.restore();
          }],
          setCursor: [(uu) => onCursor(uu)],
        },
      }, [P.labels.map((_, i) => i), ...P.series], host.current);
      plot.current = u;
      bindTouch(u);
      setReady(true);
    });
    return () => { dead = true; };
  }, [p.labels.join("|"), p.series.map((s) => s.join(",")).join("|"), p.tone, p.kind, p.type, p.height, tick]);

  // Draw-in whenever the reveal key changes.
  useEffect(() => {
    if (!ready || !plot.current) return;
    stopAnim.current();
    if (reduced()) { reveal.current = 1; plot.current.redraw(true, false); return; }
    reveal.current = 0;
    stopAnim.current = tween(820, (t) => { reveal.current = t; plot.current?.redraw(true, false); }, () => { reveal.current = 1; }, easeInOut);
  }, [ready, p.reveal]);

  useEffect(() => () => { stopAnim.current(); plot.current?.destroy(); plot.current = null; }, []);

  useEffect(() => {
    if (!wrap.current || typeof ResizeObserver !== "function") return;
    const ro = new ResizeObserver(() => { const w = wrap.current?.clientWidth; if (w && plot.current) plot.current.setSize({ width: w, height: props.current.height || 300 }); });
    ro.observe(wrap.current);
    return () => ro.disconnect();
  }, []);

  function onCursor(u: uPlot) {
    const idx = u.cursor.idx, left = u.cursor.left, f = flagEl.current, P = props.current;
    if (idx === null || idx === undefined || left === undefined || left < 0) {
      f?.classList.remove("is-on");
      P.onScrub?.(null);
      return;
    }
    if (f && wrap.current) {
      const wr = wrap.current.getBoundingClientRect(), or = u.over.getBoundingClientRect();
      f.textContent = P.flag ? P.flag(idx) : P.labels[idx] || "";
      const x = or.left - wr.left + u.valToPos(idx, "x"), half = f.offsetWidth / 2;
      f.style.left = `${Math.max(half, Math.min(wr.width - half, x))}px`;
      f.classList.add("is-on");
    }
    P.onScrub?.(idx);
  }

  function bindTouch(u: uPlot) {
    const o = u.over;
    const at = (e: TouchEvent) => { const r = o.getBoundingClientRect(), t = e.touches[0]; if (t) u.setCursor({ left: Math.max(0, Math.min(r.width, t.clientX - r.left)), top: r.height / 2 }); };
    o.addEventListener("touchstart", at, { passive: true });
    o.addEventListener("touchmove", at, { passive: true });
    o.addEventListener("touchend", () => u.setCursor({ left: -10, top: -10 }));
  }

  const onKey = (e: KeyboardEvent) => {
    if (!plot.current || (e.key !== "ArrowLeft" && e.key !== "ArrowRight" && e.key !== "Home" && e.key !== "End")) return;
    e.preventDefault();
    const n = props.current.labels.length;
    const k = keyIdx.current;
    keyIdx.current = e.key === "Home" ? 0 : e.key === "End" ? n - 1 : k === null ? n - 1 : Math.max(0, Math.min(n - 1, k + (e.key === "ArrowLeft" ? -1 : 1)));
    plot.current.setCursor({ left: plot.current.valToPos(keyIdx.current, "x"), top: 10 });
  };
  const onBlur = () => { keyIdx.current = null; plot.current?.setCursor({ left: -10, top: -10 }); };

  return <div class="scrub" ref={wrap} tabIndex={0} role="group" aria-roledescription="chart"
    aria-label={`${p.label}. Use the left and right arrow keys to move through the points.`} onKeyDown={onKey} onBlur={onBlur}
    style={{ height: `${p.height || 300}px` }}>
    {!ready ? <div class="sk sk-chart" style={{ height: "100%" }} /> : null}
    <div ref={host} class="scrub-plot" />
    <div ref={flagEl} class="scrub-flag" aria-hidden="true" />
  </div>;
}
