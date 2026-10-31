// The app shell: a fixed sidebar with grouped sections and badges, a top bar with the compact title and the repo
// switcher, the page (lazy, with a transition), and on phones a bottom tab bar with a "More" sheet.
import type { FunctionComponent } from "preact";
import { useEffect, useState } from "preact/hooks";
import { useApp } from "../data/files";
import { current, demoMode } from "../data/repos";
import { useStore } from "../data/store";
import { SideHealth } from "../features/Health";
import { welcome } from "../github/token";
import { PageSkeleton, ToastHost, EmptyState } from "../ui/bits";
import { Button } from "../ui/Button";
import { Icon } from "../ui/icons";
import { pageTitle } from "../ui/Page";
import { Sheet } from "../ui/Sheet";
import { Brand } from "./Brand";
import { Profile } from "./Profile";
import { href, route, type Route } from "./router";
import { ROUTES, TABS, routeById, type PageProps, type RouteDef } from "./routes";

const pageCss = new Set((document.querySelector<HTMLMetaElement>('meta[name="sv-page-css"]')?.content || "").split(",").filter(Boolean));
const cssLoads = new Map<string, Promise<void>>();
// The folder main.js was served from (app/), wherever the page itself sits; its ?v= release tag goes on page styles too.
const base = document.querySelector<HTMLScriptElement>('script[type="module"][src]')?.src || location.href;
const release = new URL(base, location.href).search;
// A page's own stylesheet, loaded with its code so the first screen stays light.
function loadCss(id: string): Promise<void> {
  if (!pageCss.has(id)) return Promise.resolve();
  if (!cssLoads.has(id)) {
    cssLoads.set(id, new Promise((done) => {
      const link = Object.assign(document.createElement("link"), { rel: "stylesheet", href: new URL(`pages/${id}.css`, base).href + release });
      link.onload = link.onerror = () => done();
      document.head.appendChild(link);
    }));
  }
  return cssLoads.get(id)!;
}

const modules = new Map<string, FunctionComponent<PageProps>>();

// The Welcome screen loads only when shown: no data beside the page, ?welcome, or a sign-in coming back.
let WelcomeMod: FunctionComponent | null = null;
function WelcomeHost() {
  const [, setTick] = useState(0);
  useEffect(() => { if (!WelcomeMod) Promise.all([import("../pages/welcome"), loadCss("welcome")]).then(([m]) => { WelcomeMod = m.default; setTick(1); }); }, []);
  return WelcomeMod ? <WelcomeMod /> : <PageSkeleton />;
}

function PageHost({ r, def, app }: { r: Route; def: RouteDef | undefined; app: PageProps["app"] }) {
  const [, setTick] = useState(0);
  const [failed, setFailed] = useState<string | null>(null);
  const repo = useStore(current);
  useEffect(() => {
    if (!def || modules.has(def.id)) return;
    let live = true;
    setFailed(null);
    Promise.all([def.load(), loadCss(def.id)]).then(([m]) => { modules.set(def.id, m.default); if (live) setTick((n) => n + 1); },
      () => { if (live) setFailed(def.id); });
    return () => { live = false; };
  }, [def?.id]);
  if (!def) return <div class="page"><EmptyState icon="search" title="This page doesn't exist." action={<Button href="#/" variant="filled">Go to Overview</Button>} /></div>;
  if (failed === def.id) return <div class="page"><EmptyState icon="warn" title="This part of the app didn't load.">Reload the page; if it keeps failing, the files on this site may be from an older run.</EmptyState></div>;
  const Mod = modules.get(def.id);
  if (!Mod) return <PageSkeleton />;
  // A new key replays the entrance when the page, the item or the repo changes.
  return <div class="page-enter" key={`${repo.id}|${r.page}|${r.rest.join("/")}`}><Mod app={app} route={r} /></div>;
}

function NavItem({ def, active, app }: { def: RouteDef; active: boolean; app: PageProps["app"] }) {
  const b = def.badge?.(app);
  const off = def.module && app && !def.module.split("|").some((m) => app.modules?.[m]);
  return <a class={"nav-item press" + (off ? " is-off" : "")} href={href(def.id)} aria-current={active ? "page" : undefined}
    title={off ? `${def.label}: not set up for this repo` : undefined}>
    <Icon name={def.icon} /><span class="nav-label">{def.label}</span>
    {b ? <span class={`badge badge-${b.tone} num`} aria-label={`${b.n} ${b.label}`}>{b.n}</span> : null}
  </a>;
}

export function App() {
  const r = useStore(route);
  const app = useApp();
  const repo = useStore(current);
  const title = useStore(pageTitle);
  const [more, setMore] = useState(false);
  const def = routeById(r.page);
  useEffect(() => {
    const s = document.getElementById("splash");
    if (s) { s.classList.add("is-gone"); setTimeout(() => s.remove(), 450); }
  }, []);
  useEffect(() => { setMore(false); }, [r.page]);
  const groups = [...new Set(ROUTES.map((x) => x.group))];
  const inMore = !TABS.includes(r.page);
  const greet = useStore(welcome);
  const greeting = !demoMode && (greet || (repo.id === "here" && app === null));
  // The tab names the screen that shows: Welcome, or the page and the repo it is about.
  // The page id on <html> lets the sheet design colour each module's markers, sheets included.
  useEffect(() => { document.documentElement.dataset.page = greeting ? "welcome" : r.page; }, [greeting, r.page]);
  useEffect(() => { document.title = greeting ? "Welcome · StackVitals" : app === undefined ? "StackVitals" : `${def?.label || "Not found"} · ${repo.label} · StackVitals`; }, [greeting, app === undefined, def?.id, repo.label]);
  if (greeting) return <><WelcomeHost /><ToastHost /></>;
  return <div class="app">
    <a class="skip" href="#main" onClick={(e) => { e.preventDefault(); document.getElementById("main")?.focus(); }}>Skip to content</a>
    <aside class="sidebar" aria-label="Sections">
      <div class="side-brand"><Brand withName /></div>
      <nav class="side-nav" aria-label="Sections">
        {groups.map((g) => <div class="nav-group" role="group" aria-label={g}>
          <div class="nav-group-label" aria-hidden="true">{g}</div>
          {ROUTES.filter((x) => x.group === g).map((x) => <NavItem def={x} active={x.id === r.page} app={app ?? null} />)}
        </div>)}
      </nav>
      <div class="side-foot"><SideHealth app={app} />{demoMode ? <p class="side-demo">Demo data for three example repos.</p> : null}</div>
    </aside>
    <div class="main-col">
      <header class={"topbar" + (title.compact ? " is-compact" : "")}>
        <span class="topbar-logo"><Brand /></span>
        <span class="topbar-title" aria-hidden={!title.compact}>{title.title}</span>
        <Profile />
      </header>
      <main id="main" tabIndex={-1}>
        {demoMode ? <div class="demo-banner"><Icon name="play" /><span>You are looking at demo data. <a href={location.pathname}>Open your own repo</a></span></div> : null}
        {app === undefined ? <PageSkeleton /> : <PageHost r={r} def={def} app={app} />}
      </main>
    </div>
    <nav class="tabbar" aria-label="Sections">
      {TABS.map((id) => { const d = routeById(id)!; return <a class="tab press" href={href(id)} aria-current={r.page === id ? "page" : undefined}><Icon name={d.icon} /><span>{d.short || d.label}</span></a>; })}
      <button type="button" class="tab press" aria-haspopup="dialog" aria-expanded={more} aria-current={inMore ? "page" : undefined} onClick={() => setMore(true)}>
        <Icon name={inMore && def ? def.icon : "more"} /><span>{inMore && def ? (def.short || def.label).split(" ")[0] : "More"}</span></button>
    </nav>
    <Sheet open={more} onClose={() => setMore(false)} title="More" size="sm">
      {groups.map((g) => { const items = ROUTES.filter((x) => x.group === g && !TABS.includes(x.id)); return items.length ? <div class="more-group">
        <h3 class="more-label">{g}</h3>
        <div class="more-grid">{items.map((x) => { const b = x.badge?.(app ?? null); return <a class="more-item press" href={href(x.id)} aria-current={x.id === r.page ? "page" : undefined}
          onClick={() => setMore(false)}><Icon name={x.icon} /><span>{x.label}</span>{b ? <span class={`badge badge-${b.tone} num`}>{b.n}</span> : null}</a>; })}</div>
      </div> : null; })}
    </Sheet>
    <ToastHost />
  </div>;
}
