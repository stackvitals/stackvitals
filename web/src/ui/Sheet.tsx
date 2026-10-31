// Sheet: a bottom sheet on phones and a centred modal on wider screens. Focus is trapped and returned, Escape closes,
// the page behind stops scrolling, and on touch the sheet can be swiped down to close.
import type { ComponentChildren, JSX } from "preact";
import { useEffect, useRef, useState } from "preact/hooks";
import { Icon } from "./icons";
import { EXIT_MS } from "./motion";
import { Portal } from "./Portal";

const stack: symbol[] = [];
let seq = 0;
let locks = 0;
function lock(on: boolean): void {
  locks += on ? 1 : -1;
  document.documentElement.classList.toggle("is-locked", locks > 0);
}

export const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

// Keeps a closing overlay mounted until its exit animation ends.
export function usePresence(open: boolean): { mounted: boolean; shown: boolean } {
  const [mounted, setMounted] = useState(open);
  const [shown, setShown] = useState(false);
  useEffect(() => {
    if (open) {
      setMounted(true);
      const id = requestAnimationFrame(() => requestAnimationFrame(() => setShown(true)));
      return () => cancelAnimationFrame(id);
    }
    setShown(false);
    const t = setTimeout(() => setMounted(false), EXIT_MS());
    return () => clearTimeout(t);
  }, [open]);
  return { mounted, shown };
}

export interface SheetProps {
  open: boolean; onClose: () => void; title: string; description?: ComponentChildren; children?: ComponentChildren;
  footer?: ComponentChildren; size?: "sm" | "md" | "lg"; hideTitle?: boolean;
}

export function Sheet(p: SheetProps) {
  const { mounted, shown } = usePresence(p.open);
  if (!mounted) return null;
  return <Portal><SheetBody {...p} shown={shown} /></Portal>;
}

function SheetBody({ open, onClose, title, description, children, footer, size = "md", hideTitle, shown }: SheetProps & { shown: boolean }) {
  const box = useRef<HTMLDivElement>(null);
  const me = useRef(Symbol("sheet"));
  const tid = useRef(`sheet-t-${++seq}`).current;
  const back = useRef<HTMLElement | null>(null);
  const [drag, setDrag] = useState(0);
  const start = useRef<{ y: number; t: number } | null>(null);
  const close = useRef(onClose);
  close.current = onClose;

  useEffect(() => {
    back.current = document.activeElement as HTMLElement | null;
    stack.push(me.current);
    lock(true);
    const first = box.current?.querySelector<HTMLElement>("[data-autofocus]") || box.current?.querySelector<HTMLElement>(".sheet-content " + FOCUSABLE.split(",")[0]) || box.current;
    first?.focus({ preventScroll: true });
    const onKey = (e: KeyboardEvent) => {
      if (stack[stack.length - 1] !== me.current) return;
      if (e.key === "Escape") { e.preventDefault(); close.current(); return; }
      if (e.key !== "Tab" || !box.current) return;
      const f = [...box.current.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((x) => x.offsetParent !== null);
      if (!f.length) { e.preventDefault(); return; }
      const a = f[0]!, z = f[f.length - 1]!;
      if (e.shiftKey && (document.activeElement === a || document.activeElement === box.current)) { e.preventDefault(); z.focus(); }
      else if (!e.shiftKey && document.activeElement === z) { e.preventDefault(); a.focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      stack.splice(stack.indexOf(me.current), 1);
      lock(false);
      if (back.current?.isConnected) back.current.focus({ preventScroll: true });
    };
  }, []);

  // Swipe down from the grabber or the header to close (touch and pen only).
  const down = (e: JSX.TargetedPointerEvent<HTMLElement>) => {
    if (e.pointerType === "mouse" || !matchMedia("(max-width: 640px)").matches) return;
    if ((e.target as HTMLElement).closest("button")) return;
    start.current = { y: e.clientY, t: performance.now() };
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const move = (e: JSX.TargetedPointerEvent<HTMLElement>) => { if (start.current) setDrag(Math.max(0, e.clientY - start.current.y)); };
  const up = (e: JSX.TargetedPointerEvent<HTMLElement>) => {
    if (!start.current) return;
    const dy = e.clientY - start.current.y, v = dy / Math.max(1, performance.now() - start.current.t);
    start.current = null;
    if (dy > 110 || v > 0.6) close.current();
    setDrag(0);
  };

  const state = shown && open ? " is-open" : "";
  return <div class={"overlay" + state}>
    <div class="scrim" onClick={() => close.current()} aria-hidden="true" />
    <div ref={box} class={`sheet sheet-${size}${drag ? " is-dragging" : ""}`} role="dialog" aria-modal="true" aria-labelledby={tid} tabIndex={-1}
      style={drag ? { transform: `translateY(${drag}px)` } : undefined}>
      <div class="sheet-head" onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up}>
        <span class="grabber" aria-hidden="true" />
        <div class={"sheet-titles" + (hideTitle ? " sr" : "")}>
          <h2 id={tid} class="sheet-title">{title}</h2>
          {description ? <p class="sheet-desc">{description}</p> : null}
        </div>
        <button type="button" class="close-x press" aria-label="Close" onClick={() => close.current()}><Icon name="x" /></button>
      </div>
      <div class="sheet-content">{children}</div>
      {footer ? <div class="sheet-foot">{footer}</div> : null}
    </div>
  </div>;
}
