// Setup: pick a repo, see the plan (detected and pre-ticked), then "Set it up" commits the workflow, starts the first run,
// shows it live and turns on Pages. Without a token: the file ready on GitHub, the YAML or the CLI, and a paced watch.
import "./setup.css";
import { useEffect, useMemo, useState } from "preact/hooks";
import type { PageProps } from "../app/routes";
import { navigate } from "../app/router";
import { freshest } from "../data/files";
import { current } from "../data/repos";
import { useStore } from "../data/store";
import { AccountBar, ConnectPanel, TokenWarnings } from "../features/connect";
import { RepoPicker } from "../features/connectRepos";
import { tokenPageUrl } from "../github/caps";
import { makeApi, type Api } from "../github/client";
import { detect, suggest, type Detected, type PagesMode, type Plan } from "../github/detect";
import { remember } from "../github/mine";
import { openByName, openSetup, parseRepo } from "../github/open";
import { diffText, lineDiff } from "../github/diff";
import { isRepo } from "../github/names";
import { freshAccount } from "../github/session";
import { TITLES, loadRun, newRun, releaseLock, retry, runSetup, saveRun, siteUrl, takeLock, type SetupRun, type Status } from "../github/setup";
import { account } from "../github/token";
import { POLL_FOR_MS, POLL_MS, check, watchSteps, type Watched } from "../github/watch";
import { FILE, MODULES, cliCommand, withInputs, workflowTemplate, type Module } from "../github/workflow";
import { Button } from "../ui/Button";
import { SegmentedControl, Stepper, Toggle } from "../ui/controls";
import { Icon, type IconName } from "../ui/icons";
import { Card, Page, Section } from "../ui/Page";
import { CodeBlock, CopyButton, EmptyState, Skeleton, toast } from "../ui/bits";
import { PasteNote, onPrefill } from "../ui/prefill";
import { newFile } from "../github/links";
import { Sheet } from "../ui/Sheet";

const NAMES: Record<Module, string> = { ci: "CI health", flow: "Pull requests and delivery", deps: "Dependencies", community: "Community" };
const detected = new Map<string, Promise<Detected | null>>();
const active = new Set<string>();
// This tab's id for the one-tab-at-a-time setup lock.
const TAB = Math.random().toString(36).slice(2);

function currentRepo(app: PageProps["app"]): string | null {
  const s = current.get().source;
  const r = s.kind === "branch" ? `${s.owner}/${s.repo}` : app?.repo || null;
  return r && isRepo(r) ? r : null;
}

export default function Setup({ app, route }: PageProps) {
  const pick = route.query.has("pick");
  const asked = route.query.get("repo");
  // Only a plain owner/name is set up; anything else goes back to picking a repo.
  const repo = asked ? (isRepo(asked) ? asked : null) : pick ? null : currentRepo(app);
  // A repo whose data is already here is running: show its health instead of asking GitHub again.
  if (repo && app?.repo?.toLowerCase() === repo.toLowerCase() && freshest(app) && !route.query.has("check")) return <Running app={app} />;
  return repo ? <SetupFor key={repo.toLowerCase()} repo={repo} app={app} /> : <Choose app={app} bad={asked && !isRepo(asked) ? asked : null} />;
}

function Choose({ app, bad }: { app: PageProps["app"]; bad?: string | null }) {
  const a = useStore(account);
  const [text, setText] = useState("");
  const go = (e: Event) => { e.preventDefault(); const r = parseRepo(text); if (r) navigate(`#/setup?repo=${encodeURIComponent(r)}`); else toast("Type it as owner/repo", "bad"); };
  return <Page title="Set up StackVitals" subtitle="Pick a repo: StackVitals checks what it has and suggests a plan you can change.">
    {bad ? <div class="note note-bad" role="alert"><Icon name="warn" /><span>“{bad.slice(0, 80)}” isn't a repo name (owner/name), so nothing was opened.</span></div> : null}
    {a ? <Section title="Your repos" action={<AccountBar compact />}>
      <TokenWarnings />
      <RepoPicker onPick={(r, s) => (s === "data" ? openByName(r.full_name, r.private) : openSetup(r.full_name, r.private))} />
    </Section> : <Section title="Connect GitHub" description="To list your repos and set one up in one click.">
      <Card><ConnectPanel app={app} /></Card>
    </Section>}
    <Section title="Or type a repo">
      <form class="byname-row" onSubmit={go}>
        <input class="input mono" aria-label="Repository, as owner/repo" placeholder="owner/repo" value={text} onInput={(e) => setText(e.currentTarget.value)} />
        <Button type="submit" variant="tinted">Continue</Button>
      </form>
    </Section>
  </Page>;
}

// The running state loads on its own, so the setup page stays small.
function Running({ app }: { app: NonNullable<PageProps["app"]> }) {
  const [M, setM] = useState<typeof import("../features/SetupRunning") | null>(null);
  useEffect(() => { import("../features/SetupRunning").then(setM); }, []);
  return M ? <M.Running app={app} /> : <Skeleton lines={6} />;
}

const ICON: Record<Status, IconName> = { pending: "dot", running: "dot", done: "check", failed: "warn", skipped: "off", waiting: "clock" };

function Steps({ run }: { run: SetupRun }) {
  return <ol class="setup-steps" aria-label="Setup steps">
    {run.steps.map((s) => <li class={`setup-step is-${s.status}`} aria-current={s.status === "running" ? "step" : undefined}>
      <span class="setup-mark">{s.status === "running" ? <span class="spin" aria-label="Running" /> : <Icon name={ICON[s.status]} />}</span>
      <div class="setup-body">
        <b>{TITLES[s.id]}</b><span class="sr"> ({s.status})</span>
        {s.note ? <p>{s.note}{s.link ? <> <a href={s.link} target="_blank" rel="noopener noreferrer">Open on GitHub</a></> : null}</p> : null}
        {s.fix ? <p class="setup-fix"><Icon name="about" /><span>{s.fix}</span></p> : null}
        {s.fixLink ? <Button size="sm" variant="tinted" href={s.fixLink} external iconEnd="external">{s.fixLink.includes("personal-access-tokens") ? "Make a new token" : "Open on GitHub"}</Button> : null}
        {s.id === "run" && run.jobs?.length ? <ul class="jobs">{run.jobs.map((j) => <li>
          <span class={`job-dot is-${j.conclusion || j.status}`} aria-hidden="true" /><b>{j.name}</b><span class="job-state">{j.conclusion || j.status.replace("_", " ")}</span>
          {j.status !== "completed" ? <ul class="job-steps">{j.steps.filter((x) => x.status !== "queued" || j.steps.indexOf(x) < 3).map((x) =>
            <li class={`is-${x.conclusion || x.status}`}>{x.status === "in_progress" ? <span class="spin" aria-hidden="true" /> : <Icon name={x.conclusion === "success" ? "check" : x.conclusion === "failure" ? "warn" : "dot"} />}{x.name}</li>)}</ul> : null}
        </li>)}</ul> : null}
      </div>
    </li>)}
  </ol>;
}

function useDetected(api: Api, repo: string, authed: boolean) {
  const [det, setDet] = useState<Detected | null | undefined>(undefined);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    const k = `${repo}|${authed}`;
    if (!detected.has(k)) detected.set(k, detect(api, repo));
    detected.get(k)!.then((d) => live && setDet(d), (e) => { detected.delete(k); if (live) setErr(e instanceof Error ? e.message : "The check failed."); });
    return () => { live = false; };
  }, [repo, authed]);
  return { det, err };
}

function SetupFor({ repo, app }: { repo: string; app: PageProps["app"] }) {
  const a = useStore(account);
  const api = useMemo(() => makeApi(a?.token), [a?.token]);
  const { det, err } = useDetected(api, repo, !!a);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [adv, setAdv] = useState(false);
  const [run, setRun] = useState<SetupRun | null>(() => loadRun(repo));
  const [busy, setBusy] = useState(false);
  const [connect, setConnect] = useState(false);
  useEffect(() => { if (det) setPlan(suggest(det)); }, [det]);

  const yaml = (compact: boolean) => plan ? withInputs(workflowTemplate(plan.names, { compact, modules: plan.modules }),
    { days: plan.days, budget: plan.budget, ...(plan.pages === "artifact" ? { pages: "artifact" as const } : {}) }) : "";

  const go = async (base: SetupRun) => {
    if (!a || active.has(repo)) return;
    // Another tab of this browser is setting the same repo up: leave it to that tab.
    if (!takeLock(repo, TAB)) { toast("Setup for this repo is running in another tab.", "neutral"); return; }
    active.add(repo); setBusy(true);
    let done: SetupRun = base;
    try {
      // A signed-in token near its end is renewed first; if that fails the account is signed out with a message.
      const fresh = await freshAccount({ app });
      if (fresh) done = await runSetup(base, setRun, { api: makeApi(fresh.token), save: (r) => { saveRun(r); takeLock(repo, TAB); }, tokenPage: tokenPageUrl() });
    } finally { active.delete(repo); releaseLock(repo, TAB); setBusy(false); }
    if (done.finished && done.steps.find((s) => s.id === "data")?.status === "done") {
      remember(repo, "data");
      toast(`StackVitals is set up in ${repo}`);
      openByName(repo, done.target.private);
    }
  };
  // A different StackVitals file already there: what would change, and how (a pull request unless a direct commit is confirmed).
  const differs = det && plan && det.existing !== null && det.existing !== yaml(false);
  const diff = useMemo(() => (differs ? diffText(lineDiff(det!.existing!, yaml(false))) : ""), [differs, det?.existing, plan]);
  const [direct, setDirect] = useState(false);
  const [sure, setSure] = useState(false);
  const replace = !!differs && direct && sure;
  const otherPages = !!det?.pages && !det.pages.ours && !det.private && plan?.pages === "public";
  const start = () => det && plan && go(newRun({ repo: det.repo, branch: det.branch, private: det.private, yaml: yaml(false),
    everyCiRun: det.private && plan.everyCiRun, pages: plan.pages, replace, pagesSwitch: otherPages && plan.pagesSwitch }));
  // A reload in the middle carries on by itself.
  useEffect(() => { if (a && run && !run.finished && run.steps.some((s) => s.status === "running")) void go(run); }, [!!a]);

  const set = (p: Partial<Plan>) => setPlan((x) => (x ? { ...x, ...p } : x));
  const toggleMod = (m: Module, on: boolean) => set({ modules: MODULES.filter((x) => (x === m ? on : plan!.modules.includes(x))) });
  const stopped = run && !run.finished && !busy && run.steps.some((s) => s.status === "failed" || s.status === "waiting");

  return <Page title={`Set up ${repo}`} subtitle="StackVitals checked the repo and ticked what fits. Change anything, then set it up."
    toolbar={<Button variant="plain" href="#/setup?pick=1" icon="left">Another repo</Button>}>
    {err ? <EmptyState icon="warn" title="Couldn't check this repo.">{err}</EmptyState> : null}
    {det === undefined && !err ? <Skeleton lines={6} /> : null}
    {det === null ? <div class="note note-watch" role="status"><Icon name="lock" /><span>GitHub doesn't show <b>{repo}</b>{a ? " to this token" : " to visitors"}: the name is off, or it's private.
      {a ? " Make sure the token can reach it." : " Connect GitHub to set up a private repo in one click."}</span></div> : null}

    {run ? <Section title="Progress" description={run.finished ? "Done." : busy ? "Working; keep this tab open." : "Stopped. Fix what's marked, then continue."}
      action={stopped ? <Button variant="filled" onClick={() => go(retry(run))}>Continue</Button> : run.finished ? <Button variant="filled" onClick={() => openByName(repo, run.target.private)}>Open the dashboard</Button> : null}>
      <Card><Steps run={run} /></Card>
      {run.siteUrl ? <p class="setup-site">Web page: <a href={run.siteUrl} target="_blank" rel="noopener noreferrer">{run.siteUrl.replace("https://", "")}</a></p> : null}
    </Section> : null}

    {det && plan && !busy ? <>
      {det.dataBranch && !run ? <div class="note note-good"><Icon name="check" /><span>{repo} already runs StackVitals.
        <span class="note-act"><Button size="sm" variant="filled" onClick={() => openByName(repo, det.private)}>Open the dashboard</Button></span></span></div> : null}
      {det.off.length ? <div class="note" role="status"><Icon name="warn" /><span>Turned off on GitHub: {det.off.join(", ")}. StackVitals reads a workflow's runs only while it's on (Actions tab, the workflow, Enable).</span></div> : null}
      {det.canPush === false ? <div class="note note-bad" role="alert"><Icon name="warn" /><span>Your account can't push to {repo}. Ask someone with write access, or send them this page.</span></div> : null}
      <Section title="The plan" description={<>{det.private ? "Private" : "Public"} repo, default branch <code>{det.branch}</code>
        {det.workflows.length ? `, ${det.workflows.length} workflow${det.workflows.length === 1 ? "" : "s"} found` : ", no workflows yet"}.</>}>
        <Card pad={false}><ul class="plan">
          {MODULES.map((m) => <li class="plan-row">
            <div class="plan-text"><b id={`m-${m}`}>{NAMES[m]}</b><small>{why(m, det)}</small>
              {m === "ci" && plan.modules.includes("ci") && det.workflows.length ? <div class="wf-chips" role="group" aria-label="CI workflows to read">
                {det.workflows.map((n) => <button type="button" class="wf-chip press" aria-pressed={plan.names.includes(n)}
                  onClick={() => set({ names: plan.names.includes(n) ? plan.names.filter((x) => x !== n) : [...plan.names, n] })}>{plan.names.includes(n) ? <Icon name="check" /> : null}{n}</button>)}
              </div> : null}</div>
            <Toggle checked={plan.modules.includes(m)} labelledBy={`m-${m}`} disabled={plan.modules.length === 1 && plan.modules.includes(m)} onChange={(v) => toggleMod(m, v)} />
          </li>)}
          <li class="plan-row"><div class="plan-text"><b>Where you see it</b><small>{otherPages ? (plan.pagesSwitch
            ? `GitHub Pages switches from ${det.pages!.says} to the dashboard at ${siteUrl(repo).replace("https://", "")}.`
            : `Here in this app; the Pages site keeps serving ${det.pages!.says}.`)
            : plan.pages === "public" ? `A GitHub Pages site at ${siteUrl(repo).replace("https://", "")}, turned on after the first run.`
            : plan.pages === "artifact" ? "Each run uploads the app as a download (kept 7 days)." : det.private ? "Here in this app, read with your token. A Pages site would be public." : "Here in this app; no Pages site."}</small></div>
            <Button size="sm" variant="plain" onClick={() => setAdv(!adv)} expanded={adv}>{adv ? "Hide advanced" : "Advanced"}</Button></li>
        </ul></Card>
        {otherPages ? <Card class="advanced">
          <div class="note note-watch" role="status"><Icon name="warn" /><span>Pages already serves <b>{det.pages!.says}</b> for {repo}. Switching replaces that site with the dashboard.</span></div>
          <div class="adv-row"><span>Pages site</span><SegmentedControl<"keep" | "switch"> size="sm" label="Pages site" value={plan.pagesSwitch ? "switch" : "keep"}
            onChange={(v) => set({ pagesSwitch: v === "switch" })}
            options={[{ value: "keep", label: "Keep it (dashboard in the app)" }, { value: "switch", label: "Switch Pages to the dashboard" }]} /></div>
        </Card> : null}
        {adv ? <Card class="advanced">
          <div class="adv-row"><span id="adv-days">History to read on the first runs</span><Stepper label="days" value={plan.days} min={7} max={90} step={1} unit="days" onChange={(v) => set({ days: v })} /></div>
          <div class="adv-row"><span>Most API requests per run</span><Stepper label="requests" value={plan.budget} min={100} max={5000} step={100} onChange={(v) => set({ budget: v })} /></div>
          <div class="adv-row"><span>Web page</span><SegmentedControl<PagesMode> size="sm" label="Web page" value={plan.pages} onChange={(v) => set({ pages: v })}
            options={[{ value: "public", label: "Pages site" }, { value: "artifact", label: "Artifact" }, { value: "local", label: "In this app" }]} /></div>
          {det.private && plan.pages === "public" ? <div class="note note-watch"><Icon name="warn" /><span>A Pages site is public on most plans, even for a private repo.</span></div> : null}
          {det.private ? <div class="adv-row"><span id="adv-every">Read every CI run (uses more Actions minutes; the pull request verdict needs it)</span>
            <Toggle checked={plan.everyCiRun} labelledBy="adv-every" onChange={(v) => set({ everyCiRun: v })} /></div> : null}
        </Card> : null}
        <details class="yaml-peek"><summary>See the file ({FILE})</summary><CodeBlock code={yaml(false)} title={FILE} /></details>
      </Section>

      {differs ? <Section title="The workflow file is already there" description={<>{repo} has a different <code>{FILE}</code>. Lines with − go, lines with + come in.</>}>
        <Card>
          <pre class="diff" aria-label="What would change" tabIndex={0} style={{ overflow: "auto", maxHeight: "20rem", fontSize: "0.8125rem", margin: 0 }}><code>{diff}</code></pre>
          <div class="adv-row"><span>How to change it</span><SegmentedControl<"pr" | "commit"> size="sm" label="How to change it" value={direct ? "commit" : "pr"}
            onChange={(v) => { setDirect(v === "commit"); setSure(false); }}
            options={[{ value: "pr", label: "Open a pull request" }, { value: "commit", label: `Commit to ${det.branch}` }]} /></div>
          {direct ? <div class="adv-row"><span id="sure-l">I've read the changes: replace the file on <code>{det.branch}</code> in {repo}</span>
            <Toggle checked={sure} labelledBy="sure-l" onChange={setSure} /></div> : null}
        </Card>
      </Section> : null}

      {a ? <Section title="Set it up" action={<AccountBar compact />}>
        <Card class="go-card">
          <p class="go-or">Writes to <b>{det.repo}</b> with {a.login ? `${a.login}'s` : "your"} GitHub access:</p>
          <ul class="go-list">
            <li><Icon name="check" />{differs && !replace ? <>Opens a pull request with the new file against <code>{det.branch}</code></>
              : <>Commits the file to <code>{det.branch}</code> (a pull request if the branch is protected)</>}</li>
            {det.private && plan.everyCiRun ? <li><Icon name="check" />Sets <code>STACKVITALS_EVERY_CI_RUN</code></li> : null}
            <li><Icon name="check" />Starts the first run and shows it here (2 to 5 minutes)</li>
            {!det.private && plan.pages === "public" && (!otherPages || plan.pagesSwitch) ? <li><Icon name="check" />{otherPages ? "Switches the Pages site to the dashboard" : "Turns on the Pages site"}</li> : null}
            <li><Icon name="check" />Opens the dashboard</li>
          </ul>
          <Button variant="filled" size="lg" wide onClick={start} disabled={det.canPush === false || (!!differs && direct && !sure)}>
            {differs ? (replace ? `Replace the file on ${det.branch}` : "Open a pull request") : run ? "Set it up again" : "Set it up"}</Button>
        </Card>
      </Section> : <NoToken repo={repo} branch={det.branch} yamlFull={yaml(false)} yamlCompact={yaml(true)} modules={plan.modules} onConnect={() => setConnect(true)} />}
    </> : null}
    {det === null && !a ? <NoToken repo={repo} branch="main" yamlFull={workflowTemplate(null)} yamlCompact={workflowTemplate(null, { compact: true })} modules={[...MODULES]} onConnect={() => setConnect(true)} /> : null}
    <Sheet open={connect} onClose={() => setConnect(false)} title="Connect GitHub" description="Then setup runs in one click.">
      <ConnectPanel app={app} onConnected={() => setConnect(false)} />
    </Sheet>
  </Page>;
}

function why(m: Module, d: Detected): string {
  if (m === "ci") return d.workflows.length ? `Flaky and slowing checks. Reads these when they finish (ticked: the ones that look like CI).` : "No CI workflows yet: it starts reading once you add one.";
  if (m === "flow") return d.deployments || d.releases ? `Review flow and cycle time; ${d.deployments ? "deployments" : "releases"} found, so delivery and DORA too.` : "Review flow and cycle time; delivery shows once you deploy or release.";
  if (m === "deps") return d.lockfiles.length ? `Lockfiles found (${d.lockfiles.slice(0, 3).join(", ")}): known vulnerabilities and a pull request check.` : "No lockfiles at the top of the repo.";
  return d.private ? "Newcomers and first answers; mostly useful for public repos." : "Newcomers, first answers, stars and traffic.";
}

// Without a token: GitHub's editor with the file ready, the YAML, or the CLI; then a slow watch on the open API.
function NoToken({ repo, branch, yamlFull, yamlCompact, modules, onConnect }: { repo: string; branch: string; yamlFull: string; yamlCompact: string; modules: Module[]; onConnect: () => void }) {
  const KEY = `sv:watch:${repo}`;
  const [since, setSince] = useState<number | null>(() => { try { return Number(sessionStorage.getItem(KEY)) || null; } catch { return null; } });
  const [w, setW] = useState<Watched | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const begin = () => { const t = Date.now(); setSince(t); try { sessionStorage.setItem(KEY, String(t)); } catch { /* memory only */ } };
  const once = async (prev: Watched | null) => {
    setBusy(true);
    try { const next = await check(makeApi(), repo, prev); setW(next); setMsg(null); return next; } catch (e) { setMsg(e instanceof Error ? e.message : "The check failed."); return null; } finally { setBusy(false); }
  };
  useEffect(() => {
    if (!since || Date.now() - since > POLL_FOR_MS) return;
    let live = true, last: Watched | null = w;
    void once(last).then((x) => { last = x || last; });
    const id = setInterval(() => {
      if (!live || document.hidden || Date.now() - since > POLL_FOR_MS || last?.site) return;
      void once(last).then((x) => { last = x || last; });
    }, POLL_MS);
    return () => { live = false; clearInterval(id); };
  }, [since]);
  const list = watchSteps(w);
  // The short file fills GitHub's editor when it fits; otherwise the full file (with its comments) is copied to paste.
  const link = newFile(repo, branch, FILE, yamlCompact, yamlFull);
  return <>
    <Section title="Do it on GitHub" description="No token needed: GitHub opens with the file ready; press Commit changes. That also starts the first run.">
      <Card class="go-card">
        <div class="go-buttons">
          <Button variant="filled" href={link.url} external iconEnd="external" onClick={() => { onPrefill(link, "GitHub opened with the file: press Commit changes there")(); begin(); }}>Open GitHub with the file ready</Button>
          <CopyButton text={yamlFull} label="Copy the file" />
          <Button variant="tinted" icon="link" onClick={onConnect}>Connect GitHub for one click</Button>
        </div>
        <PasteNote link={link} />
        <p class="go-or">Or from a terminal:</p>
        <CodeBlock inline code={cliCommand(repo, modules)} note={<>Then commit and push the file. <code>pip install stackvitals</code> first.</>} />
        {branch === "main" ? <p class="go-or">Default branch isn't <code>main</code>? Change it in GitHub's editor before committing.</p> : null}
      </Card>
    </Section>
    <Section title="Progress" description={since ? "Checked about once a minute for 15 minutes (GitHub allows visitors 60 requests an hour)." : "Starts when you open GitHub, or now:"}
      action={<Button size="sm" variant="tinted" loading={busy} onClick={() => (since ? once(w) : begin())}>{since ? "Check now" : "Watch progress"}</Button>}>
      <Card><ol class="setup-steps">{list.map((s) => <li class={`setup-step is-${s.state === "done" ? "done" : s.state === "now" && since ? "running" : "pending"}`}>
        <span class="setup-mark">{s.state === "done" ? <Icon name="check" /> : s.state === "now" && since ? <span class="spin" aria-label="Waiting" /> : <Icon name="dot" />}</span>
        <div class="setup-body"><b>{s.title}</b>
          {s.title === "First run started" && w?.run ? <p>Run <a href={w.run.html_url} target="_blank" rel="noopener noreferrer">#{w.run.run_number}</a>: {w.run.status === "completed" ? w.run.conclusion : w.run.status}.</p> : null}
          {s.title === "Web page on" && s.state === "now" && w?.public ? <p>In Settings, Pages: Deploy from a branch, <code>stackvitals-data</code>, <code>/docs</code>. <a href={`https://github.com/${repo}/settings/pages`} target="_blank" rel="noopener noreferrer">Open Pages settings</a></p> : null}
        </div></li>)}</ol>
        {msg ? <div class="note note-watch" role="alert"><Icon name="warn" /><span>{msg}</span></div> : null}
        {w?.dataBranch ? <Button variant="filled" onClick={() => openByName(repo, false)}>Open the dashboard</Button> : null}
      </Card>
    </Section>
  </>;
}

