// Help: the StackVitals docs, bundled at build time and loaded only here. Sections, search over titles, headings and
// text, an article view with its table of contents (links between docs stay in the app), and the reference tables.
import "./help.css";
import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import type { ComponentChildren, JSX } from "preact";
import type { PageProps } from "../app/routes";
import type { AppJson } from "../data/types";
import { store, useStore } from "../data/store";
import { markdown, type Heading } from "../features/markdown";
import { Button } from "../ui/Button";
import { EmptyState, Skeleton } from "../ui/bits";
import { Icon } from "../ui/icons";
import { GroupedList, ListRow, Page } from "../ui/Page";
import { AutoTable, COMMANDS, CommandTable, PrintTable, printed } from "./help/commands";

interface Entry { doc: string; h?: string; title: string; summary: string; group: number }
interface Doc { id: string; file: string; title: string; group: number; chunk: string; headings: [number, string, string][] }
interface Index { groups: string[]; entries: Entry[]; docs: Doc[] }

const BLOB = "https://github.com/stackvitals/stackvitals/blob/main/docs/";
const base = document.querySelector<HTMLScriptElement>('script[type="module"][src]')?.src || location.href;
const files = new Map<string, Promise<unknown>>();
const get = <T,>(name: string): Promise<T | null> => {
  if (!files.has(name)) files.set(name, fetch(new URL(name, base).href).then((r) => (r.ok ? r.json() : null), () => null));
  return files.get(name) as Promise<T | null>;
};
// Typed search survives opening an article and coming back.
const query = store("");

function useLoad<T>(load: () => Promise<T | null>, deps: unknown[]): T | null | undefined {
  const [v, setV] = useState<{ k: string; v: T | null } | null>(null);
  const k = JSON.stringify(deps);
  useEffect(() => { let live = true; load().then((x) => { if (live) setV({ k, v: x }); }); return () => { live = false; }; }, [k]);
  return v && v.k === k ? v.v : undefined;
}

// The reference sections under the guides: each a heading, a one-line description and its table.
function Ref({ id, title, count, desc, children }: { id: string; title: string; count?: number; desc: ComponentChildren; children: ComponentChildren }) {
  return <section class="help-group help-cta help-ref" aria-labelledby={id}>
    <h2 id={id} class="help-group-h">{title}{count ? <span>{count}</span> : null}</h2>
    <p class="help-desc">{desc}</p>
    {children}
  </section>;
}

function Reference({ app }: { app: AppJson | null }) {
  const pages = printed(app);
  return <>
    <Ref id="hg-a" title="Done in the app" desc="These used to need a command. Now they take a click here; the last two columns say what each path does.">
      <AutoTable />
    </Ref>
    <Ref id="hg-c" title="Commands" count={COMMANDS.length}
      desc={<>Everything else runs where the table says, after <code class="code-inline">pip install stackvitals</code>; every command takes <code class="code-inline">--help</code>. Filter by use or by where it runs.</>}>
      <CommandTable />
    </Ref>
    {pages.length ? <Ref id="hg-p" title="Printable pages" count={pages.length} desc="Written beside the app by the last run. Weekly snapshots stay in the history folder beside them on the data branch.">
      <PrintTable rows={pages} />
    </Ref> : null}
  </>;
}

const href = (doc: string, h?: string) => `#/help/${doc}${h ? "#" + h : ""}`;
const clip = (s: string, n = 110) => (s.length <= n ? s : s.slice(0, s.lastIndexOf(" ", n)) + "…");

function Hi({ text, q }: { text: string; q: string }) {
  const i = q ? text.toLowerCase().indexOf(q) : -1;
  return i < 0 ? <>{text}</> : <>{text.slice(0, i)}<mark>{text.slice(i, i + q.length)}</mark>{text.slice(i + q.length)}</>;
}

interface Hit { doc: string; h?: string; title: string; where: string; text: string; rank: number }

function search(ix: Index, bodies: Record<string, string> | null, q: string): Hit[] {
  const out: Hit[] = [], seen = new Set<string>();
  const name = (id: string) => ix.docs.find((d) => d.id === id)?.title || id;
  const add = (h: Hit) => { const k = h.doc + "#" + (h.h || ""); if (!seen.has(k)) { seen.add(k); out.push(h); } };
  for (const e of ix.entries) if (e.title.toLowerCase().includes(q)) add({ doc: e.doc, ...(e.h ? { h: e.h } : {}), title: e.title, where: ix.groups[e.group] || "", text: clip(e.summary), rank: 0 });
  for (const d of ix.docs) for (const [, t, id] of d.headings) if (t.toLowerCase().includes(q)) add({ doc: d.id, h: id, title: t, where: name(d.id), text: "", rank: 1 });
  for (const e of ix.entries) if (e.summary.toLowerCase().includes(q)) add({ doc: e.doc, ...(e.h ? { h: e.h } : {}), title: e.title, where: ix.groups[e.group] || "", text: clip(e.summary), rank: 2 });
  for (const [id, body] of Object.entries(bodies || {})) {
    const i = body.toLowerCase().indexOf(q);
    if (i < 0 || seen.has(id + "#")) continue;
    const text = body.slice(Math.max(0, i - 70), i + 110).replace(/\]\([^)]*\)|[`*#>|[\]]|-{3,}/g, "").replace(/\s+/g, " ").trim();
    add({ doc: id, title: name(id), where: "In the text", text: (i > 70 ? "…" : "") + text + "…", rank: 3 });
  }
  return out.sort((a, b) => a.rank - b.rank).slice(0, 40);
}

function Home({ ix, app }: { ix: Index; app: AppJson | null }) {
  const q = useStore(query), needle = q.trim().toLowerCase();
  // Text search needs every doc's body: loaded once, on the first search.
  const bodies = useLoad(async () => needle.length < 2 ? null
    : Object.assign({}, ...(await Promise.all([...new Set(ix.docs.map((d) => d.chunk))].map((c) => get<Record<string, string>>(`help/${c}.json`))))), [needle.length >= 2]);
  const hits = useMemo(() => (needle ? search(ix, bodies ?? null, needle) : []), [needle, bodies]);
  return <Page title="Help" subtitle={`${ix.docs.length} guides and references, from install to how each number is worked out.`}>
    <label class="search-field help-search"><Icon name="search" />
      <input class="input" type="search" placeholder="Search the docs" aria-label="Search the docs" value={q} onInput={(e) => query.set(e.currentTarget.value)} /></label>
    {needle ? <section class="help-results" aria-live="polite" aria-label="Search results">
      {hits.length ? <GroupedList label="Results">{hits.map((h) => <ListRow href={href(h.doc, h.h)} title={<Hi text={h.title} q={needle} />}
        subtitle={<><span class="help-where">{h.where}</span>{h.text ? <> · <Hi text={h.text} q={needle} /></> : null}</>} />)}</GroupedList>
        : bodies === undefined ? <Skeleton lines={3} /> : <EmptyState icon="search" title={`Nothing matches "${q.trim()}"`}>Try a module name, a connector or a setting.</EmptyState>}
    </section> : <>
      <div class="help-grid">{ix.groups.map((g, i) => {
        const list = ix.entries.filter((e) => e.group === i);
        return list.length ? <section class="help-group" aria-labelledby={`hg-${i}`}><h2 id={`hg-${i}`} class="help-group-h">{g}<span>{list.length}</span></h2>
          <GroupedList label={g}>{list.map((e) => <ListRow href={href(e.doc, e.h)} title={e.title} subtitle={clip(e.summary, 96)} />)}</GroupedList></section> : null;
      })}</div>
      <Reference app={app} />
      <section class="help-group help-cta" aria-labelledby="hg-x"><h2 id="hg-x" class="help-group-h">Still stuck?</h2>
        <GroupedList label="Still stuck?">
          <ListRow icon="setup" href="#/setup" title="Run setup again" subtitle="Five short steps; it checks what is already there." />
          <ListRow icon="help" href="https://github.com/stackvitals/stackvitals/issues" external title="Ask on GitHub" subtitle="Open an issue; questions are welcome." />
        </GroupedList></section>
    </>}
  </Page>;
}

function Article({ ix, id, anchor }: { ix: Index; id: string; anchor: string }) {
  const doc = ix.docs.find((d) => d.id === id);
  const bodies = useLoad(() => (doc ? get<Record<string, string>>(`help/${doc.chunk}.json`) : Promise.resolve(null)), [doc?.chunk]);
  const box = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState("");
  const docs = useMemo(() => Object.fromEntries(ix.docs.map((d) => [d.file, d.id])), [ix]);
  const titles = useMemo(() => Object.fromEntries(ix.docs.map((d) => [d.id, d.title])), [ix]);
  const out = useMemo(() => (doc && bodies?.[doc.id] !== undefined ? markdown(bodies[doc.id]!, { file: doc.file, docs, titles }) : null), [bodies, doc?.id]);
  const toc = (out?.headings || []).filter((h) => h.level === 2 || h.level === 3);
  const go = (to: string, smooth = true) => {
    const el = document.getElementById("h-" + to);
    if (!el) return;
    el.scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "start" });
    el.classList.remove("is-flash"); void el.offsetWidth; el.classList.add("is-flash");
  };
  useEffect(() => { if (out && anchor) requestAnimationFrame(() => go(anchor, false)); }, [out, anchor]);
  // The heading being read, for the table of contents.
  useEffect(() => {
    if (!out) return;
    let raf = 0;
    const onScroll = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(() => {
      let cur = "";
      for (const h of toc) { const el = document.getElementById("h-" + h.id); if (el && el.getBoundingClientRect().top < 140) cur = h.id; else if (el) break; }
      setActive(cur);
    }); };
    onScroll();
    addEventListener("scroll", onScroll, { passive: true });
    return () => { removeEventListener("scroll", onScroll); cancelAnimationFrame(raf); };
  }, [out]);
  // Links to a heading of this doc scroll there without leaving the page.
  const onClick = (e: JSX.TargetedMouseEvent<HTMLElement>) => {
    const a = (e.target as HTMLElement).closest("a");
    const h = a?.getAttribute("href") || "";
    const same = `#/help/${id}#`;
    if (!h.startsWith(same) || e.metaKey || e.ctrlKey) return;
    e.preventDefault();
    history.replaceState(history.state, "", h);
    go(h.slice(same.length));
  };
  if (!doc) return <Page title="Not found"><EmptyState icon="search" title="There's no doc by that name." action={<Button variant="filled" href="#/help">All help</Button>} /></Page>;
  const tocList = (h: Heading) => <li class={h.level === 3 ? "is-sub" : ""}><a href={href(id, h.id)} aria-current={active === h.id ? "location" : undefined}>{h.text}</a></li>;
  return <Page title={doc.title} subtitle={<span class="help-crumb"><a href="#/help">Help</a><Icon name="right" />{ix.groups[doc.group]}</span>}
    toolbar={<Button variant="plain" icon="external" href={BLOB + doc.file + (anchor ? "#" + anchor : "")} external>Open on GitHub</Button>}>
    {!out ? <Skeleton lines={8} /> : <div class={"help-article" + (toc.length > 2 ? " has-toc" : "")} onClick={onClick}>
      {toc.length > 2 ? <nav class="help-toc" aria-label="On this page"><details open={matchMedia("(min-width: 1101px)").matches}><summary>On this page</summary><ul>{toc.map(tocList)}</ul></details></nav> : null}
      <article class="md" ref={box} dangerouslySetInnerHTML={{ __html: out.html }} />
      <footer class="help-foot"><a class="help-back" href="#/help"><Icon name="left" />All help</a>
        <Button variant="plain" icon="external" href={BLOB + doc.file} external>Open on GitHub</Button></footer>
    </div>}
  </Page>;
}

export default function Help({ app, route }: PageProps) {
  const ix = useLoad(() => get<Index>("help/index.json"), []);
  const [id = "", anchor = ""] = (route.rest[0] || "").split("#");
  if (ix === undefined) return <Page title="Help"><Skeleton lines={6} /></Page>;
  if (!ix) return <Page title="Help"><EmptyState icon="warn" title="The docs didn't load.">Reload the page, or read them on <a href={BLOB} target="_blank" rel="noopener noreferrer">GitHub</a>.</EmptyState></Page>;
  return id ? <Article ix={ix} id={id} anchor={anchor} /> : <Home ix={ix} app={app} />;
}
