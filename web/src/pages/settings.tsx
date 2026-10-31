// Settings: every setting in iOS grouped forms with its default, the value in force and what a change would do; edits
// collect in a save bar and go to the repo from the Review sheet (commit, pull request, workflow run, issue or TOML).
import "./settings.css";
import type { ComponentChildren } from "preact";
import { useEffect, useMemo, useState } from "preact/hooks";
import { Appearance } from "../app/Profile";
import type { PageProps } from "../app/routes";
import { href } from "../app/router";
import { refresh, useFiles } from "../data/files";
import { current, demoMode } from "../data/repos";
import { store, useStore } from "../data/store";
import type { AppJson } from "../data/types";
import { helpHref } from "../features/helpLink";
import { GROUPS, GROUP_DOC, brief, check, fmt, groupOf, label, same, sub, valueAt, type Changes, type SettingDef, type SettingsFile, type WorkflowInput } from "../features/settingsModel";
import { applied, loadPending, savePending, type Pending } from "../features/settingsPending";
import { replay, type Point } from "../features/settingsReplay";
import { account } from "../github/token";
import { Button } from "../ui/Button";
import { EmptyState, Pill, Skeleton } from "../ui/bits";
import { Chips, DateInput, SegmentedControl, Select, Stepper, TextInput, Toggle } from "../ui/controls";
import { Icon, type IconName } from "../ui/icons";
import { Page } from "../ui/Page";
import { Sheet } from "../ui/Sheet";

type Alerts = { series?: Record<string, Point[]>; heads_up?: number; min_n?: number };
type Review = typeof import("../features/settingsReview");

// Unsaved edits per repo live outside the page, so moving between groups keeps them.
const edits = store<Record<string, Changes>>({});
const inputs = store<WorkflowInput[] | null>(null);
const wfNow = store<Record<string, Record<string, string> | null>>({});
const base = document.querySelector<HTMLScriptElement>('script[type="module"][src]')?.src || location.href;
let asked = false;

function loadInputs(): void {
  if (asked) return;
  asked = true;
  fetch(new URL("settings-workflow.json", base).href).then((r) => (r.ok ? r.json() : []), () => []).then((x: WorkflowInput[]) => inputs.set(x), () => inputs.set([]));
}

// Workflow inputs as settings ("wf:" keys); secrets are listed but never set here.
const asDef = (w: WorkflowInput): SettingDef => ({ key: "wf:" + w.name, kind: w.secret ? "secret" : w.kind, default: w.default, help: w.help, module: "workflow", ...(w.choices ? { choices: w.choices } : {}) });
const LISTS = new Set(["list", "choices"]);
const norm = (d: SettingDef, v: unknown): unknown => (v === null || v === undefined ? (/text|regex|date/.test(d.kind) ? "" : /int|number|hours|share/.test(d.kind) ? 0 : LISTS.has(d.kind) ? [] : v) : v);
const STACK = new Set(["list", "choices", "dates", "map", "teams", "regex", "services", "rules"]);
const METRICS = ["pickup_p75_hours", "review_p75_hours", "cycle_p75_hours", "change_failure_rate"];
const cap = (s: string) => (s === "ci" ? "CI" : s.charAt(0).toUpperCase() + s.slice(1));

function Control({ d, v, set, wf }: { d: SettingDef; v: unknown; set: (v: unknown) => void; wf: Record<string, string> | null }) {
  const lid = `l-${d.key}`, name = label(d.key), isWf = d.key.startsWith("wf:");
  switch (d.kind) {
    case "bool": return <Toggle checked={isWf ? v === "true" : !!v} onChange={(x) => set(isWf ? String(x) : x)} labelledBy={lid} />;
    case "switch": {
      const input = d.key.split(".").pop()!.replace(/_/g, "-");
      return <Toggle checked={v === null || v === undefined ? (wf?.[input] ?? "") === "true" : !!v} onChange={set} labelledBy={lid} />;
    }
    case "int": case "number": case "hours": case "share": {
      const share = d.kind === "share", raw = isWf ? Number(v) || 0 : Number(v ?? 0);
      return <Stepper label={name} value={share ? Math.round(raw * 1000) / 10 : raw} min={0} max={share ? 100 : d.key === "digest.hour" ? 23 : d.key.endsWith("min_scorecard") ? 10 : Infinity}
        step={d.kind === "number" ? 0.5 : 1} unit={share ? "%" : d.unit === "UTC" ? "UTC" : d.unit || (d.kind === "hours" ? "h" : "")}
        onChange={(n) => set(isWf ? String(n) : share ? Number((n / 100).toFixed(6)) : n)} />;
    }
    case "choice": {
      const opts = (d.choices || []).map((c) => ({ value: c, label: cap(c) }));
      return opts.length <= 4 && opts.every((o) => o.label.length <= 10)
        ? <SegmentedControl size="sm" label={name} value={String(v ?? "")} onChange={set} options={opts} />
        : <Select label={name} value={String(v ?? "")} onChange={set} options={opts} />;
    }
    case "choices": {
      const list: string[] = isWf ? String(v ?? "").split(",").map((x) => x.trim()).filter(Boolean) : (v as string[]) || [];
      return <div class="chipset" role="group" aria-labelledby={lid}>{(d.choices || []).map((c) => {
        const on = list.includes(c);
        const next = (d.choices || []).filter((x) => (x === c ? !on : list.includes(x)));
        return <button type="button" class="chip-t press" aria-pressed={on} onClick={() => set(isWf ? next.join(",") : next)}>{on ? <Icon name="check" /> : null}{cap(c)}</button>;
      })}</div>;
    }
    case "list": return <Chips label={name} values={(v as string[]) || []} onChange={set} placeholder="Add, then Enter" />;
    case "date": return <span class="date-ctl"><DateInput value={String(v || "")} onInput={set} />{v ? <button type="button" class="link-btn" onClick={() => set("")}>Clear</button> : null}</span>;
    case "dates": case "map": case "teams": return <Pairs d={d} v={(v || {}) as Record<string, unknown>} set={set} />;
    // Each service is a small table (paths and a deploy pattern): shown here, written in the settings file.
    case "rules": {
      const list = (v || []) as { name: string; dry_run?: boolean }[];
      return <div class="pairs">{list.length ? list.map((r) => <div class="pair"><span class="pair-k">{r.name}</span>
        <span class="pair-v mono-soft">{r.dry_run ? "dry run: reports only" : "acts on matching pull requests"}</span></div>)
        : <span class="muted small">None yet: add [[rules]] with a name, when and then in the settings file.</span>}</div>;
    }
    case "services": {
      const list = Object.entries((v || {}) as Record<string, { paths?: string[]; deploy?: string }>);
      return <div class="pairs">{list.length ? list.map(([n, s]) => <div class="pair"><span class="pair-k">{n}</span>
        <span class="pair-v mono-soft">{(s.paths || []).join(", ")}{s.deploy ? ` · deploys ${s.deploy}` : ""}</span></div>)
        : <span class="muted small">None yet: add [services.&lt;name&gt;] with paths (and deploy) in the settings file.</span>}</div>;
    }
    case "secret": return <code class="code-inline">{`${d.key.slice(3)}: \${{ secrets.… }}`}</code>;
    default:
      if (d.key === "deps.policy.max_severity") return <Select label={name} value={String(v ?? "")} onChange={(x) => set(x || null)} options={["", "low", "moderate", "high", "critical"].map((x) => ({ value: x, label: x ? cap(x) : "Off" }))} />;
      return <TextInput label={name} value={String(v ?? "")} onInput={set} mono={d.kind === "regex" || isWf} placeholder={d.kind === "regex" ? "(?i)(deploy|release)" : "Not set"} />;
  }
}

// Muted tests (id until a date), renamed logins (old to new) and teams or labels (name to a list), edited as rows.
function Pairs({ d, v, set }: { d: SettingDef; v: Record<string, unknown>; set: (v: unknown) => void }) {
  const [k, setK] = useState(d.key === "investment.labels" ? "feature" : "");
  const [x, setX] = useState("");
  const teams = d.kind === "teams";
  const add = () => {
    if (!k.trim() || !x.trim()) return;
    set({ ...v, [k.trim()]: teams ? x.split(",").map((s) => s.trim()).filter(Boolean) : x.trim() });
    setK(d.key === "investment.labels" ? "feature" : ""); setX("");
  };
  const words = d.kind === "dates" ? ["Test id or pattern", "Muted until"] : d.kind === "map" ? ["Old login", "Current login"] : d.key === "investment.labels" ? ["Kind of work", "Labels, comma separated"] : ["Team name", "Logins, comma separated"];
  return <div class="pairs">
    {Object.entries(v).map(([name, val]) => <div class="pair">
      <span class="pair-k">{name}</span>
      {teams ? <Chips label={`${name} members`} values={(val as string[]) || []} onChange={(l) => set({ ...v, [name]: l })} /> : <span class="pair-v">{d.kind === "dates" ? `until ${val}` : `now ${val}`}</span>}
      <button type="button" class="pair-x press" aria-label={`Remove ${name}`} onClick={() => { const n = { ...v }; delete n[name]; set(n); }}><Icon name="x" /></button>
    </div>)}
    <div class="pair-add">
      {d.key === "investment.labels" ? <Select label={words[0]!} value={k} onChange={setK} options={["feature", "fix", "maintenance", "security", "docs"].map((o) => ({ value: o, label: cap(o) }))} />
        : <TextInput label={words[0]!} value={k} onInput={setK} placeholder={words[0]} mono={d.kind === "dates"} />}
      {d.kind === "dates" ? <DateInput value={x} onInput={setX} /> : <TextInput label={words[1]!} value={x} onInput={setX} placeholder={words[1]} />}
      <Button size="sm" icon="plus" disabled={!k.trim() || !x.trim()} onClick={add}>Add</Button>
    </div>
  </div>;
}

interface RowCtx { values: unknown; pend: Changes; set: (key: string, v: unknown) => void; info: (d: SettingDef) => void; wf: Record<string, string> | null; replays: Record<string, [number, number, boolean]> }

const inForce = (d: SettingDef, c: RowCtx): unknown => (d.key.startsWith("wf:") ? c.wf?.[d.key.slice(3)] ?? d.default : valueAt(c.values, d.key));

function Row({ d, c }: { d: SettingDef; c: RowCtx }) {
  const cur = inForce(d, c), draft = c.pend[d.key];
  const shown = draft === undefined ? cur : draft === null ? d.default : draft;
  const changed = draft !== undefined && !same(norm(d, shown), norm(d, cur));
  const inFile = !same(norm(d, cur), norm(d, d.default)) && !(d.kind === "switch" && cur == null);
  const err = changed ? check(d.key, d.kind, shown) : "";
  const r = c.replays[d.key];
  return <div class={"srow" + (STACK.has(d.kind) || (d.kind === "text" && d.key !== "deps.policy.max_severity") ? " is-stack" : "") + (changed ? " is-changed" : "")} id={`set-${d.key}`}>
    <div class="srow-text">
      <span class="srow-label" id={`l-${d.key}`}>{changed ? <span class="cdot" aria-label="Changed" /> : null}{label(d.key)}</span>
      <span class="srow-help">{brief(d.help)}{d.kind === "switch" && shown == null ? " Follows the workflow input now." : ""}</span>
      <span class="srow-meta">
        {d.kind !== "secret" && d.kind !== "switch" && fmt(d.default, d.kind, d.unit) !== "Not set" ? <span>Default {fmt(d.default, d.kind, d.unit)}</span> : null}
        {inFile && !changed ? <Pill tone="accent" icon={null}>{d.key.startsWith("wf:") ? "Set in the workflow" : "Changed in the file"}</Pill> : null}
        {changed ? <button type="button" class="link-btn" onClick={() => c.set(d.key, undefined)}>Undo</button>
          : inFile && d.kind !== "secret" ? <button type="button" class="link-btn" onClick={() => c.set(d.key, null)}>Use default</button> : null}
      </span>
      {err ? <span class="field-error" role="alert"><Icon name="warn" />{err}</span> : null}
      {r && changed ? <span class="replay"><Icon name="refresh" />{!r[2] ? "Not enough data to replay the last 90 days." : shown === 0 ? "Turns this alert off." : `Over the last 90 days it would have alerted ${r[1]} time${r[1] === 1 ? "" : "s"} (now ${r[0]}).`}</span> : null}
    </div>
    <div class="srow-ctl"><Control d={d} v={shown} set={(v) => c.set(d.key, v)} wf={c.wf} /></div>
    <button type="button" class="info-btn press" aria-label={`About ${label(d.key)}`} onClick={() => c.info(d)}><Icon name="info" /></button>
  </div>;
}

function Rows({ defs, c }: { defs: SettingDef[]; c: RowCtx }) {
  const out: ComponentChildren[] = [];
  let head: string | null = null, rows: ComponentChildren[] = [];
  const flush = () => { if (rows.length) out.push(<div class="sgroup">{head ? <h3 class="sgroup-h">{head}</h3> : null}<div class="sform card">{rows}</div></div>); rows = []; };
  for (const d of defs) {
    const h = d.kind === "secret" ? "Secrets (set in the repo's secrets, named here)" : d.key.startsWith("wf:") ? "Inputs" : sub(d.key);
    if (h !== head) { flush(); head = h; }
    rows.push(<Row d={d} c={c} />);
  }
  flush();
  return <>{out}</>;
}

function Status({ p, app, done }: { p: Pending; app: AppJson; done: boolean }) {
  const n = Object.keys(p.settings).length, what = `${n} change${n === 1 ? "" : "s"}`;
  const forget = () => { savePending(app.repo, null); refresh(); };
  if (done) return <div class="note note-good set-status" role="status"><Icon name="check" /><span><b>Applied.</b> The last run shows your {what}.</span><button type="button" class="link-btn" onClick={forget}>Dismiss</button></div>;
  const how = { issue: "sent as a GitHub issue; the workflow applies it once the issue is submitted", copy: "copied as TOML; paste it into the file and commit", committed: "committed; the next run publishes it",
    pr: "waiting in a pull request; it applies once merged", compare: "on a branch; open the pull request to apply it", dispatch: p.run ? `applying in run #${p.run.run_number}` : "sent to the workflow" }[p.via];
  return <div class="note note-accent set-status" role="status"><span class="spin" aria-hidden="true" /><span><b>Pending:</b> {what} {how}.{p.url ? <> <a href={p.url} target="_blank" rel="noopener noreferrer">Open</a></> : null}</span>
    <button type="button" class="link-btn" onClick={refresh}>Check again</button><button type="button" class="link-btn" onClick={forget}>Forget</button></div>;
}

function Account({ app }: { app: AppJson }) {
  const a = useStore(account);
  const [mod, setMod] = useState<typeof import("../features/connect") | null>(null);
  useEffect(() => { import("../features/connect").then(setMod, () => {}); }, []);
  if (!mod) return <Skeleton lines={2} />;
  return <div class="sgroup"><p class="sgroup-note">{a ? "Saving commits straight to the repo with this account (a pull request when the branch is protected)." : "Optional. Without GitHub, changes go as a prefilled issue the workflow applies. Connected, Save commits in one click."}</p>
    <div class="card card-pad">{a ? <mod.AccountBar /> : <mod.ConnectPanel app={app} />}</div></div>;
}

export default function Settings({ app, route }: PageProps) {
  const f = useFiles<{ s: SettingsFile; alerts: Alerts }>({ s: "settings.json", alerts: "alerts.json" });
  const repo = useStore(current), all = useStore(edits), wfIn = useStore(inputs), wfAll = useStore(wfNow);
  useStore(account);
  const [q, setQ] = useState(route.query.get("q") || "");
  const [info, setInfo] = useState<SettingDef | null>(null);
  const [review, setReview] = useState<Review | null>(null);
  const [open, setOpen] = useState(false);
  const group = route.rest[0] || route.query.get("module") || "";
  const shownGroup = group || "alerts";
  const pend = all[repo.id] || {};
  const wf = wfAll[repo.id] ?? null;
  useEffect(loadInputs, []);
  // The workflow's inputs as set now, read once per repo (never for the demo, whose repos don't exist).
  useEffect(() => {
    if (!app || demoMode || repo.id in wfNow.get()) return;
    wfNow.set((m) => ({ ...m, [repo.id]: null }));
    import("../features/settingsApply").then((m) => m.workflowNow(app)).then((v) => wfNow.set((m) => ({ ...m, [repo.id]: v })), () => {});
  }, [repo.id, !!app]);
  const key = route.query.get("key");
  useEffect(() => {
    const el = key && document.getElementById(`set-${key}`);
    if (el) { el.scrollIntoView({ block: "center", behavior: "smooth" }); el.classList.add("is-flash"); }
  }, [key, f.ready]);

  const defs = useMemo(() => [...(f.s?.settings || []), ...(wfIn || []).map(asDef)], [f.s, wfIn]);
  const values = f.s?.values;
  const ctxBase = { values, pend, wf };
  const changes: Changes = {};
  let errors = 0;
  for (const d of defs) {
    const draft = pend[d.key];
    if (draft === undefined) continue;
    const cur = inForce(d, ctxBase as RowCtx), shown = draft === null ? d.default : draft;
    if (same(norm(d, shown), norm(d, cur))) continue;
    changes[d.key] = draft;
    if (check(d.key, d.kind, shown)) errors++;
  }
  const count = Object.keys(changes).length;

  // Alert thresholds replayed over the published 90 days: [now, with the change, enough data].
  const replays = useMemo(() => {
    const out: Record<string, [number, number, boolean]> = {};
    const a = f.alerts;
    if (!a?.series) return out;
    const opts = { headsUp: a.heads_up ?? 0.8, minN: a.min_n ?? 10 };
    const limits = (pick: (k: string) => unknown) => Object.fromEntries(METRICS.map((m) => [m, Number(pick(`alerts.${m}`)) || 0]).filter(([, v]) => v));
    const before = replay(a.series, limits((k) => valueAt(values, k)), opts);
    const after = replay(a.series, limits((k) => (k in changes ? (changes[k] ?? valueAt(f.s?.settings?.find((d) => d.key === k), "default")) : valueAt(values, k))), opts);
    for (const m of METRICS) {
      if (!a.series[m]) continue;
      out[`alerts.${m}`] = [before[m] ?? 0, after[m] ?? 0, a.series[m]!.some((p) => p[1] != null && (p[2] ?? 0) >= opts.minN)];
    }
    return out;
  }, [f.alerts, values, JSON.stringify(changes)]);

  if (!f.ready) return <Page title="Settings"><Skeleton lines={6} /></Page>;
  if (!app || !f.s?.settings) return <Page title="Settings"><EmptyState icon="settings" title="Settings appear after the next run.">The workflow publishes every setting with its default and the value in force.</EmptyState></Page>;

  const set = (k: string, v: unknown) => edits.set((m) => {
    const mine = { ...(m[repo.id] || {}) };
    if (v === undefined) delete mine[k]; else mine[k] = v;
    return { ...m, [repo.id]: mine };
  });
  const c: RowCtx = { values, pend, set, info: setInfo, wf, replays };
  const pending = loadPending(app.repo);
  const done = !!pending && applied(pending, f.s.settings, values);
  const needle = q.trim().toLowerCase();
  const found = needle ? defs.filter((d) => `${label(d.key)} ${d.key} ${d.help}`.toLowerCase().includes(needle)) : [];
  // Workflow secrets sit last, after the inputs that can be set here.
  const inGroup = (g: string) => defs.filter((d) => (d.key.startsWith("wf:") ? "workflow" : groupOf(d)) === g).sort((a, b) => +(a.kind === "secret") - +(b.kind === "secret"));
  const changedIn = (g: string) => inGroup(g).filter((d) => d.key in changes).length;
  const title = GROUPS.find((g) => g[0] === shownGroup)?.[1] || "Settings";
  const openReview = () => { import("../features/settingsReview").then((m) => { setReview(m); setOpen(true); }); };

  const body = (g: string) => g === "appearance" ? <div class="sgroup"><div class="sform card card-pad"><Appearance /></div></div>
    : g === "account" ? <Account app={app} />
      : <>{g === "workflow" ? <p class="sgroup-note">Inputs of the StackVitals step in <code>.github/workflows/{app.links?.workflow || "stackvitals.yml"}</code>{wf ? "" : demoMode ? "; the demo shows the defaults" : "; showing defaults until the file can be read"}. A setting in the file wins over its input.
        Modules running now: {Object.keys(app.modules || {}).join(", ") || "none yet"}.</p> : null}
        {inGroup(g).length ? <Rows defs={inGroup(g)} c={c} /> : <Skeleton lines={3} />}</>;

  return <Page title="Settings" subtitle={<>Kept in <a href={app.links?.settings_file} target="_blank" rel="noopener noreferrer"><code>{f.s.file || ".github/stackvitals.toml"}</code></a> on {app.default_branch || "main"}. Change them here, review, save once.</>}
    toolbar={app.links?.edit_settings ? <Button variant="plain" icon="external" href={app.links.edit_settings} external>Edit on GitHub</Button> : null}>
    {pending ? <Status p={pending} app={app} done={done} /> : null}
    {f.s.notes?.length ? <div class="note note-watch"><Icon name="warn" /><span><b>The last run couldn't use part of the file:</b> {f.s.notes.join(" ")}</span></div> : null}
    <div class={"set-layout" + (group || needle ? " has-group" : "")}>
      <nav class="set-nav" aria-label="Settings groups">
        <label class="search-field set-search"><Icon name="search" /><input class="input" type="search" placeholder="Search settings" aria-label="Search settings" value={q} onInput={(e) => setQ(e.currentTarget.value)} /></label>
        <ul class="set-nav-list card">{GROUPS.map(([id, name, icon]) => { const n = changedIn(id); return <li><a class="set-nav-item press" href={href("settings", id)} aria-current={!needle && id === shownGroup ? "page" : undefined}>
          <span class="set-ic" data-g={id}><Icon name={icon as IconName} /></span><span class="set-nav-t">{name}</span>
          {n ? <span class="badge badge-accent num" aria-label={`${n} changed`}>{n}</span> : null}<Icon name="right" class="set-chev" /></a></li>; })}</ul>
      </nav>
      <section class="set-main" aria-labelledby="set-h">
        <a class="set-back press" href={href("settings")} onClick={() => setQ("")}><Icon name="left" />Settings</a>
        <div class="set-head"><h2 id="set-h" class="set-title">{needle ? `Results for "${q.trim()}"` : title}</h2>
          {!needle ? <a class="link-btn" href={helpHref(GROUP_DOC[shownGroup] || "settings", GROUP_DOC[shownGroup] ? "" : `[${shownGroup === "people" ? "identity" : shownGroup}]`)}>Learn more</a> : null}</div>
        {needle ? (found.length ? GROUPS.filter(([id]) => found.some((d) => (d.key.startsWith("wf:") ? "workflow" : groupOf(d)) === id)).map(([id, name]) =>
          <div class="sgroup"><h3 class="sgroup-h">{name}</h3><div class="sform card">{found.filter((d) => (d.key.startsWith("wf:") ? "workflow" : groupOf(d)) === id).map((d) => <Row d={d} c={c} />)}</div></div>)
          : <EmptyState icon="search" title={`No setting matches "${q.trim()}"`}>Try a word like review, flaky, digest or Jira.</EmptyState>)
          : body(shownGroup)}
      </section>
    </div>
    <div class={"savebar" + (count ? " is-on" : "")} role="region" aria-label="Unsaved changes" aria-hidden={!count}>
      <span class="cdot" aria-hidden="true" /><b>{count} change{count === 1 ? "" : "s"}</b>
      <Button size="sm" variant="plain" onClick={() => edits.set((m) => ({ ...m, [repo.id]: {} }))}>Discard</Button>
      <Button size="sm" variant="filled" disabled={!!errors} onClick={openReview}>{errors ? `Fix ${errors} field${errors === 1 ? "" : "s"}` : "Review"}</Button>
    </div>
    <Sheet open={!!info} onClose={() => setInfo(null)} title={info ? label(info.key) : ""} size="sm"
      footer={info ? <><Button variant="plain" href={info.key.startsWith("wf:") ? helpHref("install") : helpHref("settings", `[${info.kind === "dates" ? info.key : info.key.slice(0, info.key.lastIndexOf("."))}]`)} onClick={() => setInfo(null)}>Learn more</Button>
        <Button variant="filled" onClick={() => setInfo(null)}>Done</Button></> : null}>
      {info ? <><p class="info-body">{info.help}</p><dl class="facts">
        <div class="fact"><dt>Default</dt><dd>{fmt(info.default, info.kind, info.unit)}</dd></div>
        <div class="fact"><dt>Now</dt><dd>{fmt(inForce(info, c), info.kind, info.unit)}</dd></div>
        <div class="fact fact-wide"><dt>{info.key.startsWith("wf:") ? "Workflow input" : "In the settings file"}</dt><dd class="mono">{info.key.replace(/^wf:/, "")}</dd></div>
      </dl></> : null}
    </Sheet>
    {review ? <review.ReviewSheet open={open} onClose={() => setOpen(false)} app={app} defs={defs} changes={changes} values={values} wf={wf} replays={replays}
      onSent={(keys, saved) => {
        edits.set((m) => { const mine = { ...(m[repo.id] || {}) }; for (const k of keys) delete mine[k]; return { ...m, [repo.id]: mine }; });
        // Workflow inputs saved with the token show at once; the file itself is the record.
        if (saved) wfNow.set((m) => { const v = { ...(m[repo.id] || {}) }; for (const [k, x] of Object.entries(saved)) { if (x === null) delete v[k]; else v[k] = x; } return { ...m, [repo.id]: v }; });
      }} /> : null}
  </Page>;
}
