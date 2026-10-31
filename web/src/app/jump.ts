// ?at=<id> on a link (Help's links into a page): scroll to that part once it has rendered and settled, since pages
// and their sections load lazily. Used by the pages that have such a part, so the first screen stays light.
import { useEffect } from "preact/hooks";
import { useStore } from "../data/store";
import { route } from "./router";

let stopAt: (() => void) | null = null;
function jumpAt(id: string) {
  stopAt?.();
  let wait = 0, most = 0;
  const jump = () => {
    stop();
    document.getElementById(id)?.scrollIntoView({ block: "start", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  };
  // Waits for 250 ms without changes, or at most a second once the part is there.
  const go = () => {
    if (!document.getElementById(id)) return;
    clearTimeout(wait); wait = setTimeout(jump, 250);
    most ||= setTimeout(jump, 1000);
  };
  const mo = new MutationObserver(go), cap = setTimeout(() => stop(), 10000);
  const stop = () => { mo.disconnect(); clearTimeout(cap); clearTimeout(wait); clearTimeout(most); stopAt = null; };
  mo.observe(document.body, { childList: true, subtree: true });
  stopAt = stop;
  go();
}

export function useJump(): void {
  const at = useStore(route).query.get("at");
  useEffect(() => { if (at) jumpAt(at); return () => stopAt?.(); }, [at]);
}
