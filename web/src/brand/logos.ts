// Ten StackVitals marks on a 32 px tile; T = tile, F = foreground, A = accent. Loaded only with the logo picker.
import { DEFAULT_LOGO, STRATA, s, type LogoDef } from "./mark";

export const LOGOS: LogoDef[] = [
  STRATA,
  { id: "ascent", name: "Ascent", note: "Three bars climbing",
    body: `<rect x="7" y="17" width="4.6" height="8" rx="2.2" fill="F"/><rect x="13.7" y="12" width="4.6" height="13" rx="2.2" fill="F"/><rect x="20.4" y="7" width="4.6" height="18" rx="2.2" fill="A"/>` },
  { id: "gauge", name: "Gauge", note: "A dial reading high",
    body: s("M9.6 23.4A9 9 0 1 1 22.4 23.4", "F", 2.6, ' opacity=".4"') + s("M9.6 23.4A9 9 0 0 1 22.4 10.6", "A", 2.8) +
      s("M16 17 20.6 12.4", "F", 2.4) + `<circle cx="16" cy="17" r="2.3" fill="F"/>` },
  { id: "ring", name: "Segments", note: "A ring of checks, most of them green",
    body: `<circle cx="16" cy="16" r="9" fill="none" stroke="F" stroke-width="3" opacity=".35" stroke-dasharray="5.07 2" transform="rotate(-81 16 16)"/>` +
      `<circle cx="16" cy="16" r="9" fill="none" stroke="A" stroke-width="3" stroke-dasharray="5.07 2 5.07 2 5.07 2 5.07 2 5.07 30" transform="rotate(-81 16 16)"/>` +
      `<circle cx="16" cy="16" r="3" fill="F"/>` },
  { id: "iso", name: "Iso block", note: "An isometric stack, top face lit",
    body: `<path d="M16 6 25 10.5 16 15 7 10.5Z" fill="A"/><path d="M7 10.5 16 15v11l-9-4.5Z" fill="F"/><path d="M16 15l9-4.5v11L16 26Z" fill="F" opacity=".72"/>` +
      s("M7 16 16 20.5 25 16", "T", 1.4) },
  { id: "cross", name: "Vital cross", note: "Five tiles, the heart one lit",
    body: `<rect x="13" y="5.5" width="6" height="6" rx="1.8" fill="F"/><rect x="5.5" y="13" width="6" height="6" rx="1.8" fill="F"/>` +
      `<rect x="13" y="13" width="6" height="6" rx="1.8" fill="A"/><rect x="20.5" y="13" width="6" height="6" rx="1.8" fill="F"/><rect x="13" y="20.5" width="6" height="6" rx="1.8" fill="F"/>` },
  { id: "mono", name: "Monogram", note: "S and V, the V in green",
    body: s("M14.6 10.5h-4.4a2.8 2.8 0 0 0 0 5.6h2.6a2.8 2.8 0 0 1 0 5.6H7.6") + s("M17.4 10.5 21 21.7l3.6-11.2", "A") },
  { id: "keystone", name: "Keystone", note: "A package holding layered lines",
    body: s("M16 5.8 24.8 10.9v10.2L16 26.2l-8.8-5.1V10.9Z", "F", 2.2) + s("M11.6 13.4h8.8", "A", 2.6) + s("M11.6 17h8.8") + s("M11.6 20.6h8.8", "F", 2.6, ' opacity=".55"') },
  { id: "beacon", name: "Beacon", note: "Layers with a signal rising above",
    body: s("M7 19.8 16 24.4l9-4.6") + s("M7 14.8 16 19.4l9-4.6") + `<circle cx="16" cy="9" r="3.3" fill="A"/>` },
  { id: "summit", name: "Summit", note: "Three chevrons pointing up",
    body: s("M8.5 24 16 18.4 23.5 24", "F", 2.6, ' opacity=".55"') + s("M8.5 18.6 16 13 23.5 18.6") + s("M8.5 13.2 16 7.6 23.5 13.2", "A", 2.8) },
];

export function logoById(id: string | null | undefined): LogoDef {
  return LOGOS.find((l) => l.id === id) || LOGOS.find((l) => l.id === DEFAULT_LOGO)!;
}
