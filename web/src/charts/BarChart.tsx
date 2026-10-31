// Vertical SVG bars with labels; hover, focus or arrow keys pick a bar and report it, like the scrub chart.
import { useState } from "preact/hooks";
import type { Kind } from "../data/format";
import { fmt } from "../data/format";

export interface Bar { label: string; value: number; tone?: "good" | "bad" | "watch" | "accent" | "neutral" }

export function BarChart({ bars, kind = "count", height = 220, onPick, label }: {
  bars: Bar[]; kind?: Kind; height?: number; onPick?: (i: number | null) => void; label: string;
}) {
  const [at, setAt] = useState<number | null>(null);
  const max = Math.max(1, ...bars.map((b) => b.value));
  const pick = (i: number | null) => { setAt(i); onPick?.(i); };
  return <div class="bars" role="listbox" aria-label={label} tabIndex={0} style={{ height: `${height}px` }}
    aria-activedescendant={at === null ? undefined : `bar-${at}`}
    onKeyDown={(e) => {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      e.preventDefault();
      const d = e.key === "ArrowRight" ? 1 : -1;
      pick(at === null ? (d > 0 ? 0 : bars.length - 1) : Math.max(0, Math.min(bars.length - 1, at + d)));
    }} onBlur={() => pick(null)} onMouseLeave={() => pick(null)}>
    {bars.map((b, i) => <div id={`bar-${i}`} role="option" aria-selected={at === i} class={"bar" + (at === i ? " is-on" : "")}
      aria-label={`${b.label}: ${fmt(kind, b.value)}`} onMouseEnter={() => pick(i)} onClick={() => pick(i)}>
      <span class="bar-value num" aria-hidden="true">{fmt(kind, b.value)}</span>
      <span class="bar-track" aria-hidden="true"><span class={`bar-fill tone-${b.tone || "accent"}`} style={{ height: `${(b.value / max) * 100}%`, transitionDelay: `${i * 40}ms` }} /></span>
      <span class="bar-label" aria-hidden="true">{b.label.split("/").map((part, j) => j ? <>/<wbr />{part}</> : part)}</span>
    </div>)}
  </div>;
}
