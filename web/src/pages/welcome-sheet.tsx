// The Instrument design's Welcome: a self-drawing schematic, then Connect, demo, open by name and settings as framed panels.
import type { ComponentChildren } from "preact";
import { useEffect, useRef, useState } from "preact/hooks";
import { Appearance } from "../app/Profile";
import { LogoMark } from "../brand/Logo";
import { calm } from "../data/theme";
import { useStore } from "../data/store";
import { Abilities, AccountBar, lastCheck, useTokenCheck } from "../features/connect";
import { RepoPicker } from "../features/connectRepos";
import { tokenPageUrl } from "../github/caps";
import { authConfig } from "../github/config";
import { authorizeUrl } from "../github/oauth";
import { openEntry, openSetup } from "../github/open";
import { canRemember, type Account } from "../github/token";
import { Pill } from "../ui/bits";
import { Button } from "../ui/Button";
import { pickRepo, useByName, type WelcomeState } from "./welcome";
// This module injects its own stylesheet with the Welcome screen.
import css from "./welcome-sheet.css" with { type: "text" };

if (!document.getElementById("sv-welcome-sheet-css")) document.head.appendChild(Object.assign(document.createElement("style"), { id: "sv-welcome-sheet-css", textContent: css }));

// The schematic's marks: failing (triangle), slow (clock), kept (checked square).
const bad = (x: number, y: number) => `<path class="s-mk s-mk-bad" transform="translate(${x} ${y})" d="M0 -6.5 6.5 5H-6.5z"/>`;
const slow = (x: number, y: number) => `<g transform="translate(${x} ${y})"><circle class="s-mk s-mk-warn" r="6.5"/><path class="s-mk-g" d="M0 -3.8V0H2.8"/></g>`;
const kept = (x: number, y: number) => `<g transform="translate(${x} ${y})"><rect class="s-mk s-mk-ok" x="-5.5" y="-5.5" width="11" height="11"/><path class="s-mk-g" d="M-3 0l2 2.2 4-4.4"/></g>`;
const t = (s: string) => `style="--t:${s}s" pathLength="1"`;
const f = (s: string) => `style="--t:${s}s"`;
const callout = (x: number, y: number, n: number, s: number, hx: number, hy: number, cx: number, cy: number) =>
  `<circle class="s-dt s-f" ${f(String(s))} cx="${x}" cy="${y}" r="2.4"/><path class="s-hl s-d" ${t(String(s))} d="M${x} ${y} ${hx} ${hy}"/>` +
  `<circle class="s-hl s-d" ${t((s + .1).toFixed(1))} cx="${cx}" cy="${cy}" r="12"/><text class="s-cn s-f" ${f((s + .2).toFixed(1))} x="${cx}" y="${cy + 4.5}" text-anchor="middle">${n}</text>`;

// Wide: four boxes in a row with dimension lines above and below.
const WIDE = `
<rect class="s-bx s-d" ${t(".9")} x="1" y="80" width="198" height="56"/>
<text class="s-lbl s-f" ${f("1.3")} x="100" y="113" text-anchor="middle">your repo</text>
<path class="s-live s-d" ${t("1.35")} d="M199 108H264"/><path class="s-ah s-f" ${f("1.6")} d="M258 103.5 267 108l-9 4.5z"/>
<rect class="s-bx s-d" ${t("1.4")} x="267" y="80" width="198" height="56"/>
<text class="s-lbl s-f" ${f("1.75")} x="366" y="113" text-anchor="middle">GitHub Actions run</text>
<path class="s-live s-d" ${t("1.8")} d="M465 108H530"/><path class="s-ah s-f" ${f("2.05")} d="M524 103.5 533 108l-9 4.5z"/>
<rect class="s-bx s-d" ${t("1.85")} x="533" y="80" width="198" height="56"/>
<text class="s-lbl s-f" ${f("2.2")} x="632" y="113" text-anchor="middle"><tspan class="s-mono">stackvitals-data</tspan> branch</text>
<path class="s-live s-d" ${t("2.25")} d="M731 108H798"/><path class="s-ah s-f" ${f("2.5")} d="M792 103.5 801 108l-9 4.5z"/>
<rect class="s-appfill" x="801" y="80" width="198" height="56"/>
<rect class="s-bx s-d" ${t("2.3")} x="801" y="80" width="198" height="56"/>
<text class="s-lbl s-applbl s-f" ${f("2.65")} x="900" y="113" text-anchor="middle">this app</text>
<path class="s-hl s-d" ${t("2.5")} d="M267 74V28M733 74V28"/>
<path class="s-hl s-d" ${t("2.65")} d="M267 36H392M608 36H733"/>
<path class="s-hl s-d" ${t("2.8")} d="M261 42 273 30M727 42 739 30"/>
<text class="s-dim s-f" ${f("2.85")} x="500" y="40" text-anchor="middle">every night, in Actions</text>
<path class="s-hl s-d" ${t("2.6")} d="M1 142V206M999 142V206"/>
<path class="s-hl s-d" ${t("2.75")} d="M1 198H372M628 198H999"/>
<path class="s-hl s-d" ${t("2.9")} d="M-5 204 7 192M993 204 1005 192"/>
<text class="s-dim s-f" ${f("2.95")} x="500" y="202" text-anchor="middle">no server, no account</text>
${callout(366, 136, 1, 3, 386, 158, 396, 167)}${callout(632, 136, 2, 3.1, 652, 158, 662, 167)}${callout(900, 136, 3, 3.2, 920, 158, 930, 167)}
<g class="s-rm-hide"><rect class="s-bar-bad s-cyc-a" x="268" y="131" width="196" height="4"/><rect class="s-bar-warn s-cyc-b" x="268" y="131" width="196" height="4"/></g>
<g class="s-rm-only"><rect class="s-bar-bad" x="268" y="131" width="98" height="4"/><rect class="s-bar-warn" x="366" y="131" width="98" height="4"/></g>
<g class="s-cyc-a"><g class="s-sh-a">${bad(426, 167)}<text class="s-sl s-bad" x="440" y="171.5">1 flaky test</text></g></g>
<g class="s-cyc-b"><g class="s-sh-b">${slow(426, 167)}<text class="s-sl s-warn" x="440" y="171.5">1 slow check</text></g></g>
<rect class="s-bar-ok s-grow" ${f("3.3")} x="534" y="131" width="196" height="4"/>
<g class="s-f" ${f("3.5")}>${kept(692, 167)}<text class="s-sl s-ok" x="706" y="171.5">182 days kept</text></g>`;

// Phones: the same chain stacked, callouts on the left.
const TALL = `
<rect class="s-bx s-d" ${t(".9")} x="60" y="2" width="200" height="52"/>
<text class="s-lbl s-f" ${f("1.2")} x="160" y="33" text-anchor="middle">your repo</text>
<path class="s-live s-d" ${t("1.25")} d="M160 54V105"/><path class="s-ah s-f" ${f("1.45")} d="M155.5 99 160 108l4.5-9z"/>
<rect class="s-bx s-d" ${t("1.3")} x="60" y="108" width="200" height="52"/>
<text class="s-lbl s-f" ${f("1.6")} x="160" y="139" text-anchor="middle">GitHub Actions run</text>
<path class="s-live s-d" ${t("1.65")} d="M160 160V211"/><path class="s-ah s-f" ${f("1.85")} d="M155.5 205 160 214l4.5-9z"/>
<rect class="s-bx s-d" ${t("1.7")} x="60" y="214" width="200" height="52"/>
<text class="s-lbl s-f" ${f("2")} x="160" y="245" text-anchor="middle"><tspan class="s-mono s-mono-sm">stackvitals-data</tspan> branch</text>
<path class="s-live s-d" ${t("2.05")} d="M160 266V317"/><path class="s-ah s-f" ${f("2.25")} d="M155.5 311 160 320l4.5-9z"/>
<rect class="s-appfill" x="60" y="320" width="200" height="52"/>
<rect class="s-bx s-d" ${t("2.1")} x="60" y="320" width="200" height="52"/>
<text class="s-lbl s-applbl s-f" ${f("2.4")} x="160" y="351" text-anchor="middle">this app</text>
<path class="s-hl s-d" ${t("2.4")} d="M266 108H316M266 266H316"/>
<path class="s-hl s-d" ${t("2.55")} d="M308 108V266"/>
<path class="s-hl s-d" ${t("2.7")} d="M302 114 314 102M302 272 314 260"/>
<text class="s-dim s-f" ${f("2.75")} transform="translate(326 187) rotate(90)" text-anchor="middle">every night</text>
${callout(60, 134, 1, 2.8, 34, 134, 22, 134)}${callout(60, 240, 2, 2.9, 34, 240, 22, 240)}${callout(60, 346, 3, 3, 34, 346, 22, 346)}
<text class="s-dim s-f" ${f("3.2")} x="160" y="398" text-anchor="middle">no server, no account</text>
<g class="s-rm-hide"><rect class="s-bar-bad s-cyc-a" x="61" y="155" width="198" height="4"/><rect class="s-bar-warn s-cyc-b" x="61" y="155" width="198" height="4"/></g>
<g class="s-rm-only"><rect class="s-bar-bad" x="61" y="155" width="99" height="4"/><rect class="s-bar-warn" x="160" y="155" width="99" height="4"/></g>
<g class="s-cyc-a"><g class="s-sh-a">${bad(178, 187)}<text class="s-sl s-bad" x="192" y="191.5">1 flaky test</text></g></g>
<g class="s-cyc-b"><g class="s-sh-b">${slow(178, 187)}<text class="s-sl s-warn" x="192" y="191.5">1 slow check</text></g></g>
<rect class="s-bar-ok s-grow" ${f("3.1")} x="61" y="261" width="198" height="4"/>
<g class="s-f" ${f("3.3")}>${kept(178, 293)}<text class="s-sl s-ok" x="192" y="297.5">182 days kept</text></g>`;

// Reduced motion: the OS setting or the app's own switch; the schematic then shows both states at once.
const sysStill = typeof matchMedia === "function" ? matchMedia("(prefers-reduced-motion: reduce)") : null;
function useStill(): boolean {
  const c = useStore(calm);
  const [sys, setSys] = useState(!!sysStill?.matches);
  useEffect(() => {
    if (!sysStill) return;
    const on = () => setSys(sysStill.matches);
    sysStill.addEventListener("change", on);
    return () => sysStill.removeEventListener("change", on);
  }, []);
  return c || sys;
}

// A section frames itself in (the frame, then its heading's rule) when it scrolls into view.
function Panel({ id, title, tone, wide, lede, children }: { id: string; title: string; tone: "act" | "data" | "app" | "set"; wide?: boolean; lede?: string; children: ComponentChildren }) {
  const ref = useRef<HTMLElement>(null);
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver !== "function") { setSeen(true); return; }
    const io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) { setSeen(true); io.disconnect(); } }, { rootMargin: "0px 0px -12% 0px" });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return <section ref={ref} class={`svw-panel svw-${tone}${wide ? " is-wide" : ""}${seen ? " is-in" : ""}`} aria-labelledby={id}>
    <h2 class="svw-dh" id={id}><span class="svw-t">{title}</span></h2>
    {lede ? <p class="svw-lede">{lede}</p> : null}
    {children}
  </section>;
}

// The path a token takes: this browser to api.github.com, drawn in blue once it checks out.
function Route({ state }: { state: "wait" | "busy" | "ok" }) {
  return <svg class={`svw-link is-${state}`} viewBox="0 0 420 44" aria-hidden="true">
    <rect class="l-end" x="0.5" y="12.5" width="10" height="10" />
    <path class="l-wait" d="M11 17.5H409" />
    <path class="l-fill" pathLength={1} d="M11 17.5H409" />
    <rect class="l-end" x="409.5" y="12.5" width="10" height="10" />
    <text x="0" y="40">this browser</text>
    <text x="420" y="40" text-anchor="end">api.github.com</text>
  </svg>;
}

const OkMark = () => <svg class="svw-okmark" viewBox="0 0 28 28" aria-hidden="true"><path pathLength={1} d="M7.5 14.5 12 19l8.5-9" /></svg>;

function TokenSteps() {
  const cfg = authConfig();
  const [remember, setRemember] = useState(false);
  // Same check as the shared Connect panel; this form submits on Enter, so an empty one asks for the token.
  const { text, busy, err, setErr, check: run, onInput } = useTokenCheck(remember);
  const check = (raw: string) => (raw.trim() ? run(raw) : setErr("Paste the token first."));
  const signIn = async () => { if (cfg) location.assign(await authorizeUrl(cfg, remember && canRemember(), location.hash || "#/")); };

  return <>
    {cfg ? <div class="svw-signin"><Button variant="filled" icon="link" onClick={signIn}>Sign in with GitHub</Button><p class="svw-or">or use a token</p></div> : null}
    <ol class="svw-steps">
      <li><div>
        <h3>Make a token on GitHub</h3>
        <p class="svw-sub">The page opens with the name, a 90-day expiry and the permissions filled in.</p>
        <div class="svw-act"><Button variant={cfg ? "tinted" : "filled"} href={tokenPageUrl()} external iconEnd="external">Open GitHub's token page</Button></div>
        <figure class="svw-mock" aria-label="On GitHub's page: Repository access, Only select repositories, then pick yours">
          <p class="svw-mock-title">What GitHub's page looks like</p>
          <div aria-hidden="true">
            <div class="svw-mock-k">Repository access</div>
            <div class="svw-radio"><i class="sv-round" />All repositories</div>
            <div class="svw-radio is-on"><i class="sv-round" />Only select repositories</div>
            <span class="svw-repo">owner/repo</span>
          </div>
          <figcaption>On GitHub's page, under <b>Repository access</b>, pick the repos; GitHub can't fill that in. Then <b>Generate token</b> and copy it.</figcaption>
        </figure>
      </div></li>
      <li><div>
        <h3>Paste it here</h3>
        <form noValidate onSubmit={(e) => { e.preventDefault(); void check(text); }}>
          <label class="svw-field" for="svw-tok">GitHub token</label>
          <div class="svw-row">
            <input id="svw-tok" class="svw-input" type="password" placeholder="github_pat_…" autoComplete="off" spellcheck={false} value={text}
              aria-invalid={err ? "true" : undefined} aria-describedby="svw-tok-help svw-tok-status" onInput={(e) => onInput(e.currentTarget.value)} />
            <Button type="submit" variant="filled" loading={busy}>Check token</Button>
          </div>
          <p class="svw-help" id="svw-tok-help">Checked as soon as you paste. It goes only to api.github.com and stays in this browser.</p>
          {canRemember() ? <label class="svw-check"><input type="checkbox" checked={remember} onChange={(e) => setRemember(e.currentTarget.checked)} /> Remember on this device</label>
            : <p class="svw-help">Kept for this tab only: other sites under {location.hostname} could read a remembered token. Use a custom domain or <code>stackvitals ui</code> to remember it.</p>}
          <Route state={busy ? "busy" : "wait"} />
          <p class={"svw-status" + (err ? " is-bad" : "")} id="svw-tok-status" role="status" aria-live="polite">
            {err ? <><span class="sv-mark sv-mark-bad" aria-hidden="true" />{err}</> : busy ? "Checking with api.github.com…" : ""}</p>
        </form>
      </div></li>
    </ol>
  </>;
}

// Connected: the route drawn, the success mark, who it is, what the token can do, then the repos to pick.
function Connected({ a }: { a: Account }) {
  const got = useStore(lastCheck);
  const info = got && got.login === a.login ? got : null;
  return <ol class="svw-steps is-done">
    <li><div>
      <Route state="ok" />
      <div class="svw-verdict"><OkMark />
        <p class="svw-status" role="status">Connected as <b>{a.login || "you"}</b>.{info ? <span class="svw-sub"> {info.repos === null ? "Classic token: every repo you can reach."
          : `${info.repos}${info.repos === 100 ? "+" : ""} repo${info.repos === 1 ? "" : "s"} picked.`}</span> : null}</p></div>
      <div class="svw-acct"><AccountBar /></div>
      {info ? <div class="svw-abil"><div class="svw-ready">{info.missing.length || info.repos === 0 ? <Pill tone="watch">Needs more</Pill> : <Pill tone="good">Ready</Pill>}</div>
        <Abilities info={info} /></div> : null}
    </div></li>
    <li><div>
      <h3>Pick a repo</h3>
      <p class="svw-sub">Set up ones open their dashboard; the others go to one-click setup.</p>
      <div class="svw-picker"><RepoPicker onPick={pickRepo} /></div>
    </div></li>
  </ol>;
}

function OpenByName() {
  const { text, edit, busy, err, found, go } = useByName();
  return <form noValidate onSubmit={go}>
    <label class="svw-field" for="svw-repo">Repository</label>
    <div class="svw-row">
      <input id="svw-repo" class="svw-input" type="text" placeholder="owner/repo" value={text} autoComplete="off" spellcheck={false}
        aria-invalid={err ? "true" : undefined} aria-describedby="svw-repo-err" onInput={(e) => edit(e.currentTarget.value)} />
      <Button type="submit" variant="tinted" class="svw-mint" loading={busy}>Open</Button>
    </div>
    <p class="svw-status is-bad" id="svw-repo-err" role="status" aria-live="polite">{err ? <><span class="sv-mark sv-mark-bad" aria-hidden="true" />{err}</> : null}</p>
    {found?.res.kind === "none" ? <div class="svw-note" role="status"><span class="sv-mark sv-mark-accent" aria-hidden="true" /><span><b>{found.repo}</b> doesn't run StackVitals yet.
      <span class="svw-note-act"><Button size="sm" variant="filled" onClick={() => openSetup(found.repo, (found.res as { private: boolean }).private)}>Set it up</Button></span></span></div> : null}
    {found?.res.kind === "missing" ? <div class="svw-note" role="status"><span class="sv-mark sv-mark-watch" aria-hidden="true" /><span>GitHub doesn't show <b>{found.repo}</b> to visitors: the name is off, or it's private.
      Connect GitHub above to open private repos.</span></div> : null}
  </form>;
}

export default function SheetWelcome({ a, signing, known }: WelcomeState) {
  const still = useStill();
  // After the intro the drawing stays put, so a resize across the phone layout doesn't replay it.
  const [drawn, setDrawn] = useState(false);
  useEffect(() => { const id = setTimeout(() => setDrawn(true), 4300); return () => clearTimeout(id); }, []);
  return <div class={"svw" + (still ? " is-still" : "") + (drawn ? " is-drawn" : "") + (a ? " is-ok" : "")}>
    <div class="svw-frame">
      <span class="svw-edge e-t" /><span class="svw-edge e-r" /><span class="svw-edge e-b" /><span class="svw-edge e-l" />
      <span class="svw-tick k-t" /><span class="svw-tick k-r" /><span class="svw-tick k-b" /><span class="svw-tick k-l" />
      <main id="main" tabIndex={-1}>
        <section aria-labelledby="svw-hero">
          <h1 id="svw-hero" class="svw-h1">Know how your repo is really doing.</h1>
          <figure class="svw-flow" aria-label={"How it works: your repo runs a GitHub Actions job, which writes to the stackvitals-data branch, which this app reads"
            + (a ? " (healthy: your GitHub token checked out)." : " (it turns healthy once a token checks out).")
            + " Example states: the Actions run found 1 flaky test and 1 slow check; the data branch has 182 days of history kept."}>
            <svg class="svw-schem is-wide" viewBox="0 0 1000 214" aria-hidden="true" dangerouslySetInnerHTML={{ __html: WIDE }} />
            <svg class="svw-schem is-tall" viewBox="0 0 340 404" aria-hidden="true" dangerouslySetInnerHTML={{ __html: TALL }} />
          </figure>
          <div class="svw-notes-row">
            <ol class="svw-notes" aria-label="What it does">
              <li style="--t:3.3s"><span>Finds flaky tests, slow checks and pull requests stuck waiting, with the evidence.</span></li>
              <li style="--t:3.45s"><span>Keeps the history in your own repo, so trends and fixes are measured over months.</span></li>
              <li style="--t:3.6s"><span>Runs in your GitHub Actions. Free, open source, no server, no account.</span></li>
            </ol>
            <div class="svw-tb">
              <div class="svw-brand"><LogoMark size={34} />StackVitals</div>
              <div class="svw-key">
                <p><span class="sv-mark sv-mark-good" aria-hidden="true" /><span><b>Healthy</b>, kept and passing</span></p>
                <p><span class="sv-mark sv-mark-watch" aria-hidden="true" /><span><b>Slow</b> or waiting</span></p>
                <p><span class="sv-mark sv-mark-bad" aria-hidden="true" /><span><b>Failing</b> or flaky</span></p>
              </div>
            </div>
          </div>
          {signing ? <p class="svw-signing" role="status"><span class="sv-mark sv-mark-watch" aria-hidden="true" />{signing}</p> : null}
        </section>

        <div class="svw-panels">
          {a ? <Panel id="svw-connect" title="Your GitHub" tone="act" wide lede="Connected. Open a dashboard, or set StackVitals up in one click."><Connected a={a} /></Panel>
            : <Panel id="svw-connect" title="Connect GitHub" tone="act" wide lede="See your repos, open private ones, and set StackVitals up in one click."><TokenSteps /></Panel>}
          <Panel id="svw-demo" title="Try the demo" tone="app" lede="Three example repos with full data. Nothing to connect.">
            <div class="svw-act"><Button variant="filled" class="svw-yel" href={location.pathname + "?demo=1"}>Open the demo</Button></div>
          </Panel>
          <Panel id="svw-open" title={a ? "Or open a public repo" : "Open a public repo"} tone="data" lede="Reads its published data from its Pages site or data branch.">
            <OpenByName />
          </Panel>
          {known.length ? <Panel id="svw-recent" title="Recently opened" tone="set" wide>
            <div class="svw-recent">{known.map((e) => <button type="button" class="svw-recent-btn press" onClick={() => openEntry(e)}>{e.label}<span aria-hidden="true">→</span></button>)}</div>
          </Panel> : null}
          <Panel id="svw-set" title="Settings" tone="set" wide>
            <div class="svw-settings"><Appearance /></div>
          </Panel>
        </div>
      </main>
    </div>
  </div>;
}
