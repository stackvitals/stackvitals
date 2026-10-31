// A tiny SVG trend line; the dashed line marks where the range started.
import type { Tone } from "../data/format";

export function Sparkline({ values, tone = "neutral", width = 84, height = 32, label }: { values: number[]; tone?: Tone; width?: number; height?: number; label?: string }) {
  if (values.length < 2) return <svg class="spark" width={width} height={height} aria-hidden="true" />;
  const lo = Math.min(...values), hi = Math.max(...values), span = hi - lo || 1;
  const pts = values.map((v, i) => [(i / (values.length - 1)) * width, height - 3 - ((v - lo) / span) * (height - 6)] as const);
  const d = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join("");
  return <svg class={`spark spark-${tone}`} viewBox={`0 0 ${width} ${height}`} width={width} height={height} preserveAspectRatio="none"
    role={label ? "img" : undefined} aria-label={label} aria-hidden={label ? undefined : "true"}>
    <path class="spark-base" d={`M0 ${pts[0]![1].toFixed(1)}H${width}`} vector-effect="non-scaling-stroke" />
    <path class="spark-line" d={d} pathLength={1} vector-effect="non-scaling-stroke" />
  </svg>;
}
