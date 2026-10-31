// Buttons: filled, tinted (default) and plain, with a press scale and a loading state. An href makes it a link.
import type { ComponentChildren, JSX } from "preact";
import { Icon, type IconName } from "./icons";

export interface ButtonProps {
  variant?: "filled" | "tinted" | "plain" | "danger";
  size?: "sm" | "md" | "lg";
  icon?: IconName;
  iconEnd?: IconName;
  loading?: boolean;
  disabled?: boolean;
  wide?: boolean;
  href?: string;
  external?: boolean;
  label?: string;
  type?: "button" | "submit";
  onClick?: (e: JSX.TargetedMouseEvent<HTMLElement>) => void;
  children?: ComponentChildren;
  class?: string;
  pressed?: boolean;
  controls?: string;
  expanded?: boolean;
  haspopup?: "menu" | "dialog";
}

// Links from data open only on the web, mail or inside the app: https, http, mailto, relative and hash.
export function safeHref(h: string | undefined): string | undefined {
  if (!h || /[\u0000-\u001f]/.test(h)) return undefined;
  const scheme = /^\s*([a-z][a-z0-9+.-]*):/i.exec(h);
  if (scheme) return ["https", "http", "mailto"].includes(scheme[1]!.toLowerCase()) ? h : undefined;
  return h.startsWith("//") ? undefined : h;
}

export function Button(p: ButtonProps) {
  const cls = ["btn", "press", `btn-${p.variant || "tinted"}`, p.size && p.size !== "md" ? `btn-${p.size}` : "", p.wide ? "btn-wide" : "",
    p.loading ? "is-loading" : "", !p.children ? "btn-icon" : "", p.class || ""].filter(Boolean).join(" ");
  const inner = <>
    {p.loading ? <span class="spin" aria-hidden="true" /> : p.icon ? <Icon name={p.icon} /> : null}
    {p.children ? <span>{p.children}</span> : null}
    {p.iconEnd ? <Icon name={p.iconEnd} /> : null}
  </>;
  const href = safeHref(p.href);
  if (href && !p.disabled) {
    return <a class={cls} href={href} aria-label={p.label} onClick={p.onClick}
      {...(p.external ? { target: "_blank", rel: "noopener noreferrer" } : {})}>{inner}</a>;
  }
  return <button type={p.type || "button"} class={cls} aria-label={p.label} disabled={p.disabled || p.loading} aria-busy={p.loading || undefined}
    aria-pressed={p.pressed} aria-controls={p.controls} aria-expanded={p.expanded} aria-haspopup={p.haspopup} onClick={p.onClick}>{inner}</button>;
}
