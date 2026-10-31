// Runs before paint (in head) and again right after the splash: theme, motion, favicon and the splash mark.
import { LOGO_DEF_KEY, asLogo, faviconUrl, logoSvg } from "./brand/mark";

function read(key: string): unknown {
  try { const v = localStorage.getItem(key); return v === null ? null : JSON.parse(v); } catch { return null; }
}

const root = document.documentElement;
const theme = read("sv:theme");
// Light by default whatever the system says; dark only when the viewer chose it.
root.dataset.theme = theme === "dark" ? "dark" : "light";
if (read("sv:calm") === true) root.classList.add("calm");
// Preloads the first-screen fonts (beside boot.js, unversioned like the stylesheet's own URLs for them).
if (!document.getElementById("sv-font")) {
  const at = new URL(document.querySelector<HTMLScriptElement>('script[src*="boot.js"]')?.src || "app/boot.js", location.href);
  for (const [i, n] of ["plex-sans-400", "plex-sans-condensed-700"].entries()) {
    const l = Object.assign(document.createElement("link"), { rel: "preload", as: "font", type: "font/woff2", crossOrigin: "anonymous", href: new URL(`fonts/${n}.woff2`, at).href });
    if (!i) l.id = "sv-font";
    document.head.appendChild(l);
  }
}
const logo = asLogo(read(LOGO_DEF_KEY));
const icon = document.getElementById("favicon") as HTMLLinkElement | null;
if (icon) icon.href = faviconUrl(logo);
const splash = document.getElementById("splash-mark");
if (splash && !splash.firstChild) splash.innerHTML = logoSvg(logo);
