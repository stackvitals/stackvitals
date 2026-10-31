// One 24 px line icon set, drawn with currentColor.
const P = {
  overview: '<path d="M4 11.5 12 5l8 6.5V19a1 1 0 0 1-1 1h-4.5v-5h-5v5H5a1 1 0 0 1-1-1z"/>',
  insights: '<path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.6 10.8c.6.5 1 1.2 1.1 2V16h5v-.2c.1-.8.5-1.5 1.1-2A6 6 0 0 0 12 3z"/>',
  ci: '<circle cx="12" cy="12" r="8.5"/><path d="m8.5 12.3 2.4 2.4 4.8-5"/>',
  prs: '<circle cx="6.5" cy="6" r="2.2"/><circle cx="6.5" cy="18" r="2.2"/><circle cx="17.5" cy="18" r="2.2"/><path d="M6.5 8.2v7.6M17.5 15.8V10a3 3 0 0 0-3-3H11m2-2.5L10.5 7 13 9.5"/>',
  delivery: '<path d="M20.5 3.5 3.5 10.6l6.8 2.6 2.6 6.8zM10.3 13.2l4.2-4.2"/>',
  community: '<circle cx="9" cy="8.5" r="3.2"/><path d="M3.5 19c.6-3 2.8-4.8 5.5-4.8s4.9 1.8 5.5 4.8"/><circle cx="16.8" cy="9.5" r="2.5"/><path d="M15.6 14.4c2.4-.2 4.3 1.3 4.9 4.1"/>',
  deps: '<path d="M12 3 4 7.5v9L12 21l8-4.5v-9zM4 7.5l8 4.5 8-4.5M12 12v9"/>',
  investment: '<path d="M12 3a9 9 0 1 0 9 9h-9z"/><path d="M15 3.5A9 9 0 0 1 20.5 9H15z"/>',
  portal: '<rect x="4" y="4" width="7" height="7" rx="1.8"/><rect x="13" y="4" width="7" height="7" rx="1.8"/><rect x="4" y="13" width="7" height="7" rx="1.8"/><rect x="13" y="13" width="7" height="7" rx="1.8"/>',
  explore: '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/>',
  activity: '<path d="M12 7v5l3 2"/><circle cx="12" cy="12" r="8.5"/>',
  about: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5M12 7.6v.1"/>',
  setup: '<path d="M5 12.5 9.5 17 19 7.5"/><path d="M4 4h16v16H4z" opacity=".35"/>',
  connections: '<path d="M9 7V3M15 7V3M7 7h10v4a5 5 0 0 1-10 0zM12 16v5"/>',
  agents: '<rect x="5" y="8" width="14" height="11" rx="3"/><path d="M12 8V4.5M9.5 13v1M14.5 13v1M2.5 13v2M21.5 13v2"/>',
  settings: '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
  help: '<circle cx="12" cy="12" r="8.5"/><path d="M9.6 9.5a2.5 2.5 0 1 1 3.4 2.3c-.6.3-1 .8-1 1.5v.4M12 16.6v.1"/>',
  more: '<circle cx="6" cy="12" r="1.3"/><circle cx="12" cy="12" r="1.3"/><circle cx="18" cy="12" r="1.3"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/>',
  fair: '<path d="M8 6.5a3.5 3.5 0 0 1 6.3 1.2M8.5 3v1.2M3.8 7.8H5M4.9 4.4l.9.9"/><path d="M7.5 19h9a3.5 3.5 0 0 0 .4-7 5 5 0 0 0-9.6 1.2A3 3 0 0 0 7.5 19z"/>',
  rain: '<path d="M7.5 15h9a3.5 3.5 0 0 0 .4-7 5 5 0 0 0-9.6 1.2A3 3 0 0 0 7.5 15z"/><path d="m9 18-1 2.5M13 18l-1 2.5M17 18l-1 2.5"/>',
  off: '<circle cx="12" cy="12" r="8.5"/><path d="M8 12h8"/>',
  up: '<path d="M12 19V5M6 11l6-6 6 6"/>',
  down: '<path d="M12 5v14M6 13l6 6 6-6"/>',
  flat: '<path d="M5 12h14"/>',
  chev: '<path d="m7 10 5 5 5-5"/>',
  right: '<path d="m10 7 5 5-5 5"/>',
  left: '<path d="m14 7-5 5 5 5"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  copy: '<rect x="8" y="8" width="12" height="12" rx="2.5"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
  warn: '<path d="M12 4 2.8 19.5h18.4z"/><path d="M12 10v4.5M12 17.2v.1"/>',
  refresh: '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3M19.5 4.5v4h-4"/>',
  external: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/>',
  play: '<path d="M8 5.5v13l10.5-6.5z"/>',
  bolt: '<path d="M13 3 5 13.5h6l-1 7.5 8-10.5h-6z"/>',
  moon: '<path d="M19.5 14.5A8 8 0 0 1 9.5 4.5a8 8 0 1 0 10 10z"/>',
  trash: '<path d="M5 7h14M10 7V4.5h4V7M7 7l1 13h8l1-13"/>',
  lock: '<rect x="5" y="10.5" width="14" height="10" rx="2.5"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
  dot: '<circle cx="12" cy="12" r="4"/>',
  // The standard information mark: a ring with a dotted i, as in Material info_outline and Lucide info.
  info: '<circle cx="12" cy="12" r="9.25"/><path d="M12 11v5.75M12 7.6v.01"/>',
} as const;

export type IconName = keyof typeof P;

export function Icon({ name, size, class: cls }: { name: IconName; size?: number; class?: string }) {
  return <svg class={"ic" + (cls ? " " + cls : "")} viewBox="0 0 24 24" width={size} height={size} aria-hidden="true" focusable="false"
    dangerouslySetInnerHTML={{ __html: P[name] }} />;
}
