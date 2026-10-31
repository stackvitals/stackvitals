// Renders children into a node at the end of <body>, outside any transformed or scrolling parent.
import { render, type ComponentChildren } from "preact";
import { useLayoutEffect, useRef } from "preact/hooks";

export function Portal({ children }: { children: ComponentChildren }) {
  const host = useRef<HTMLDivElement | null>(null);
  if (!host.current && typeof document !== "undefined") host.current = document.createElement("div");
  useLayoutEffect(() => {
    const el = host.current!;
    el.className = "layer";
    document.body.appendChild(el);
    return () => { render(null, el); el.remove(); };
  }, []);
  useLayoutEffect(() => { render(<>{children}</>, host.current!); });
  return null;
}
