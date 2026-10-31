# StackVitals web app

Preact + TypeScript, bundled by esbuild into `src/stackvitals/web/app/` with `src/stackvitals/web/index.html` beside it.
No CDN: Preact, uPlot and the IBM Plex fonts are bundled; their licences go to `app/LICENSES.md`.
The one design is Instrument (internal id "sheet"): `index.html` sets `html[data-design="sheet"]` and `src/styles/sheet.css` ships last in main.css.

## Build

```
cd web
npm ci
npm run build    # writes ../src/stackvitals/web/app/ and index.html (commit the output)
npm run check    # tsc --noEmit, strict
npm test         # GitHub client, setup steps and workflow generator (node:test, fake fetch; compares with Python)
npm run watch    # rebuild on save
npm run e2e      # browser tests on the committed build (installed Chrome; PLAYWRIGHT_CHANNEL= for bundled Chromium), writes e2e/results.json
```

Open `index.html?demo=1` for three demo repos, `index.html?pages=<site>/` for a Pages site, or `index.html?repo=owner/name`
for a repo's `stackvitals-data` branch.

## Layout

- `src/main.tsx` entry; `src/boot.ts` runs before paint (theme, favicon, splash)
- `src/app/` shell (`App.tsx`), hash router, route list (`routes.ts`), repo switcher, logo picker
- `src/data/` typed file shapes, sources (here, pages, branch), fetch cache and `useFiles`, repo store, formatting, write paths
- `src/ui/` design system; `src/charts/` scrub chart, sparkline, bars, metric hero and watchlist
- `src/github/` GitHub API client, token storage, sign-in (PKCE via `worker/relay`), workflow generator, setup steps
  (`SV_RELAY` and `SV_CLIENT_ID` at build time turn on Sign in with GitHub)
- `src/features/` shared logic across pages (installation health, decide sheet, vitals)
- `src/pages/<id>.tsx` one lazy module per route; `src/pages/<id>.css` loads with its page
- `src/styles/` global tokens and component styles; `demo/source.mjs` writes `app/demo/`

## Components

AppShell (sidebar, top bar, tab bar, More sheet), Page, Section, Columns, Card, GroupedList, ListRow, Stats/Stat, Button,
SegmentedControl, Toggle, Stepper, Field, TextInput, NumberInput, DateInput, Select, Chips, Sheet, Popover, Menu, InfoButton,
Pill, StatePill, ChangePill, CodeBlock, CopyButton, EmptyState, Skeleton, toast, Table, ScrubChart, MetricHero, Watchlist,
Sparkline, BarChart, Decide, Send, HealthStrip.

## Budgets (checked by tests/local/test_web_build.py)

- First screen (main.js, main.css with Instrument's styles, boot.js and preloaded chunks): at most 46 KB gzipped
  (44.8 KB measured). Pages and uPlot load lazily.
- Fonts: at most 90 KB (Plex Sans 400/600, Plex Sans Condensed 700, Plex Mono 400: 79 KB).
