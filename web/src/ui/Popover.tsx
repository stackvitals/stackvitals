// Popover anchored to a button (flips above when there is no room, stays on screen), and a keyboard-navigable Menu.
// On phones it can turn into a bottom sheet instead.
import type { ComponentChildren, JSX, RefObject } from "preact";
import { useEffect, useLayoutEffect, useRef, useState } from "preact/hooks";
import { Icon, type IconName } from "./icons";
import { Portal } from "./Portal";
import { FOCUSABLE, Sheet, usePresence } from "./Sheet";

export const isPhone = () => typeof matchMedia === "function" && matchMedia("(max-width: 640px)").matches;

export interface PopoverProps {
  open: boolean; onClose: () => void; anchor: RefObject<HTMLElement>; label: string; children?: ComponentChildren;
  align?: "start" | "end"; width?: number; sheetOnPhone?: boolean;
}

export function Popover(p: PopoverProps) {
  const { mounted, shown } = usePresence(p.open);
  const [phone] = useState(isPhone);
  if (p.sheetOnPhone && phone) return <Sheet open={p.open} onClose={p.onClose} title={p.label} size="sm">{p.children}</Sheet>;
  if (!mounted) return null;
  return <Portal><PopBody {...p} shown={shown} /></Portal>;
}

function PopBody({ open, onClose, anchor, label, children, align = "end", width = 320, shown }: PopoverProps & { shown: boolean }) {
  const box = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number; up: boolean; maxH: number } | null>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useLayoutEffect(() => {
    const place = () => {
      const a = anchor.current?.getBoundingClientRect();
      if (!a || !box.current) return;
      const h = box.current.offsetHeight, w = Math.min(width, innerWidth - 16), gap = 8;
      const below = innerHeight - a.bottom - gap - 8, above = a.top - gap - 8;
      const up = h > below && above > below;
      let left = align === "end" ? a.right - w : a.left;
      left = Math.max(8, Math.min(innerWidth - w - 8, left));
      setPos({ top: up ? Math.max(8, a.top - gap - Math.min(h, above)) : a.bottom + gap, left, up, maxH: Math.max(160, up ? above : below) });
    };
    place();
    addEventListener("resize", place);
    addEventListener("scroll", place, true);
    return () => { removeEventListener("resize", place); removeEventListener("scroll", place, true); };
  }, []);
  useEffect(() => {
    // Modal: focus moves in (to the box until lazy content arrives), Tab stays inside, Escape closes, focus goes back to the button.
    const first = () => box.current?.querySelector<HTMLElement>('[aria-checked="true"], [role^="menuitem"], ' + FOCUSABLE);
    (first() || box.current)?.focus({ preventScroll: true });
    const grow = new MutationObserver(() => { if (document.activeElement === box.current) first()?.focus({ preventScroll: true }); });
    if (box.current) grow.observe(box.current, { childList: true, subtree: true });
    const onDown = (e: PointerEvent) => {
      const t = e.target as Node;
      if (!box.current?.contains(t) && !anchor.current?.contains(t)) close.current();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); close.current(); return; }
      if (e.key !== "Tab" || !box.current) return;
      const f = [...box.current.querySelectorAll<HTMLElement>(FOCUSABLE + ', [role^="menuitem"]')].filter((x) => x.offsetParent !== null);
      if (!f.length) { e.preventDefault(); return; }
      const a = f[0]!, z = f[f.length - 1]!, at = document.activeElement;
      if (e.shiftKey && (at === a || at === box.current)) { e.preventDefault(); z.focus(); }
      else if (!e.shiftKey && (at === z || !box.current.contains(at))) { e.preventDefault(); a.focus(); }
    };
    document.addEventListener("pointerdown", onDown, true);
    document.addEventListener("keydown", onKey);
    return () => {
      grow.disconnect();
      document.removeEventListener("pointerdown", onDown, true); document.removeEventListener("keydown", onKey);
      const at = document.activeElement;
      if (!at || at === document.body || box.current?.contains(at)) anchor.current?.focus({ preventScroll: true });
    };
  }, []);
  const style: JSX.CSSProperties = pos ? { top: `${pos.top}px`, left: `${pos.left}px`, width: `${Math.min(width, innerWidth - 16)}px`, maxHeight: `${pos.maxH}px` }
    : { top: "-9999px", left: "0px", width: `${width}px` };
  return <div ref={box} class={"popover" + (pos?.up ? " is-up" : "") + (shown && open && pos ? " is-open" : "") + (align === "start" ? " from-start" : "")}
    role="dialog" aria-modal="true" aria-label={label} tabIndex={-1} style={style}>{children}</div>;
}

// Arrow keys, Home and End move between the items of a menu.
export function Menu({ label, children }: { label: string; children?: ComponentChildren }) {
  const onKey = (e: JSX.TargetedKeyboardEvent<HTMLDivElement>) => {
    const items = [...e.currentTarget.querySelectorAll<HTMLElement>('[role^="menuitem"]:not([disabled])')];
    const i = items.indexOf(document.activeElement as HTMLElement);
    const go = (n: number) => { e.preventDefault(); items[(n + items.length) % items.length]?.focus(); };
    if (e.key === "ArrowDown") go(i + 1);
    else if (e.key === "ArrowUp") go(i - 1);
    else if (e.key === "Home") go(0);
    else if (e.key === "End") go(items.length - 1);
  };
  return <div role="menu" aria-label={label} class="menu" onKeyDown={onKey}>{children}</div>;
}

export function MenuItem({ icon, leading, title, subtitle, checked, onSelect, trailing, danger }: {
  icon?: IconName; leading?: ComponentChildren; title: ComponentChildren; subtitle?: ComponentChildren; checked?: boolean;
  onSelect: () => void; trailing?: ComponentChildren; danger?: boolean;
}) {
  return <button type="button" role={checked === undefined ? "menuitem" : "menuitemradio"} aria-checked={checked} tabIndex={-1}
    class={"menu-item press" + (danger ? " is-danger" : "")} onClick={onSelect}>
    {icon ? <span class="menu-icon"><Icon name={icon} /></span> : leading}
    <span class="menu-text"><b>{title}</b>{subtitle ? <small>{subtitle}</small> : null}</span>
    {trailing}{checked ? <Icon name="check" class="menu-check" /> : null}
  </button>;
}

export function MenuLabel({ children }: { children?: ComponentChildren }) {
  return <div class="menu-label" role="presentation">{children}</div>;
}
export function MenuSep() { return <div class="menu-sep" role="separator" />; }
