// Clicking the logo opens all ten marks; picking one changes it everywhere (sidebar, favicon, splash) and is remembered.
import { useEffect, useRef, useState } from "preact/hooks";
import type { LogoDef } from "../brand/mark";
import { LogoMark } from "../brand/Logo";
import { useStore } from "../data/store";
import { logo, setLogo } from "../data/theme";
import { toast } from "../ui/bits";
import { Popover } from "../ui/Popover";

export function LogoButton({ withName }: { withName?: boolean }) {
  const [open, setOpen] = useState(false);
  const btn = useRef<HTMLButtonElement>(null);
  const chosen = useStore(logo).id;
  // The nine other marks load the first time the picker opens.
  const [all, setAll] = useState<LogoDef[] | null>(null);
  useEffect(() => { if (open && !all) import("../brand/logos").then((m) => setAll(m.LOGOS)).catch(() => setAll([])); }, [open]);
  return <>
    <button ref={btn} type="button" class="brand press" aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen(!open)}
      aria-label="StackVitals. Choose the logo">
      <LogoMark />{withName ? <span class="brand-name">StackVitals</span> : null}
    </button>
    <Popover open={open} onClose={() => setOpen(false)} anchor={btn} label="Choose a logo" align="start" width={560} sheetOnPhone>
      <p class="logo-hint">Pick the mark you like; it changes the sidebar, the browser tab and the splash.</p>
      <div class="logo-grid" role="radiogroup" aria-label="Logos" onKeyDown={(e) => {
        const items = [...e.currentTarget.querySelectorAll<HTMLElement>("button")];
        const i = items.indexOf(document.activeElement as HTMLElement);
        const cols = getComputedStyle(e.currentTarget).gridTemplateColumns.split(" ").length;
        const d = ({ ArrowRight: 1, ArrowLeft: -1, ArrowDown: cols, ArrowUp: -cols } as Record<string, number>)[e.key];
        if (d && i >= 0) { e.preventDefault(); items[Math.max(0, Math.min(items.length - 1, i + d))]?.focus(); }
      }}>
        {(all || []).map((l) => <button type="button" role="radio" aria-checked={l.id === chosen} class="logo-opt press"
          onClick={() => { setLogo(l); toast(`Logo set to ${l.name}`); }} title={l.note}>
          <LogoMark def={l} size={44} /><span class="logo-name">{l.name}</span><span class="logo-note">{l.note}</span>
        </button>)}
      </div>
    </Popover>
  </>;
}
