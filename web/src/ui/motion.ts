// Motion helpers: every animation checks reduced motion (the OS setting or the app's own "calm" switch).
const sys = typeof matchMedia === "function" ? matchMedia("(prefers-reduced-motion: reduce)") : null;

export function reduced(): boolean {
  return !!sys?.matches || document.documentElement.classList.contains("calm");
}

export const easeOut = (t: number) => 1 - Math.pow(1 - t, 4);
export const easeInOut = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

// Runs step(0..1) over `ms`; returns a stop function. With reduced motion it jumps to the end.
export function tween(ms: number, step: (t: number) => void, done?: () => void, ease = easeOut): () => void {
  if (reduced()) { step(1); done?.(); return () => {}; }
  let start: number | null = null, id = 0, dead = false;
  const frame = (now: number) => {
    if (dead) return;
    if (start === null) start = now;
    const p = Math.min(1, (now - start) / ms);
    step(ease(p));
    if (p < 1) id = requestAnimationFrame(frame); else done?.();
  };
  id = requestAnimationFrame(frame);
  return () => { dead = true; cancelAnimationFrame(id); };
}

// The number of ms a CSS exit animation needs before an element can be removed.
export const EXIT_MS = () => (reduced() ? 0 : 320);
