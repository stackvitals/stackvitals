// The one mark the first screen needs: the default, or the chosen one remembered with its drawing (the other nine load with the picker).
export interface LogoDef { id: string; name: string; note: string; body: string }

export const s = (d: string, c = "F", w = 2.6, extra = "") =>
  `<path d="${d}" fill="none" stroke="${c}" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round"${extra}/>`;

export const STRATA: LogoDef = { id: "strata", name: "Strata", note: "Stacked layers, the top one lit",
  body: s("M6.5 20.5 16 25.3l9.5-4.8") + s("M6.5 15.6 16 20.4l9.5-4.8") + `<path d="M16 5.8 25.5 10.6 16 15.4 6.5 10.6Z" fill="A"/>` };

export const DEFAULT_LOGO = STRATA.id;
export const LOGO_KEY = "sv:logo";
export const LOGO_DEF_KEY = "sv:logo-def";

const ATTRS = new Set(["d", "x", "y", "width", "height", "rx", "cx", "cy", "r", "fill", "stroke", "stroke-width", "stroke-linecap",
  "stroke-linejoin", "opacity", "transform", "stroke-dasharray"]);
const ELEMENT = /^<(path|rect|circle)((?:\s+[a-z-]+="[^"<>&]*")*)\s*\/>/;

// Only self-closing path, rect and circle elements with allowlisted attributes and plain values.
function plainShapes(body: string): boolean {
  let rest = body.trim();
  if (!rest) return false;
  while (rest) {
    const m = ELEMENT.exec(rest);
    if (!m) return false;
    for (const a of m[2]!.matchAll(/([a-z-]+)="([^"]*)"/g)) if (!ATTRS.has(a[1]!) || /url\(|:|\\/i.test(a[2]!)) return false;
    rest = rest.slice(m[0].length).trimStart();
  }
  return true;
}

// A remembered drawing is used only if it parses as plain shapes; anything else gets the default logo.
export function asLogo(value: unknown): LogoDef {
  const d = value as LogoDef | null;
  const ok = d && typeof d.id === "string" && typeof d.name === "string" && typeof d.body === "string" && plainShapes(d.body);
  return ok ? { id: d.id, name: d.name, note: String(d.note || ""), body: d.body } : STRATA;
}

// The full SVG markup; colours are CSS vars in the page and fixed hex in the favicon.
export function logoSvg(def: LogoDef, colors = { T: "var(--logo-tile)", F: "var(--logo-fg)", A: "var(--logo-acc)" }, tile = true): string {
  const body = def.body.replace(/"(T|F|A)"/g, (_, k: "T" | "F" | "A") => `"${colors[k]}"`);
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">${tile ? `<rect width="32" height="32" rx="8" fill="${colors.T}"/>` : ""}${body}</svg>`;
}

export const FAVICON_COLORS = { T: "#2160C4", F: "#FFFFFF", A: "#7CF0B6" };

export function faviconUrl(def: LogoDef): string {
  return "data:image/svg+xml," + encodeURIComponent(logoSvg(def, FAVICON_COLORS));
}
