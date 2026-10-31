// Connections: every service StackVitals reads or feeds, grouped by status (connected, needs attention, available).
// Each opens a sheet with what it unlocks, the steps, its secrets (saved sealed, straight to GitHub), its settings,
// and Test connection, which runs the workflow's check and reads the result back from connectors.json.
import "./connections.css";
import { useEffect, useState } from "preact/hooks";
import type { PageProps } from "../app/routes";
import { useFiles } from "../data/files";
import { ago } from "../data/format";
import { demoMode } from "../data/repos";
import { request, setToken } from "../data/write";
import type { Conn, SecretDef, View } from "../features/connections-data";
import { BUCKET, WORDS, type Entry, type Status } from "../features/connstatus";
import { Send } from "../features/Decide";
import { checkIssueUrl, ghToken, listSecrets, newSecretUrl, saveSecret, startCheck, testLinear, tokenUrl, waitForCheck } from "../features/secrets";
import { brief, check, label, same, tomlSnippet, valueAt, type SettingDef, type SettingsFile } from "../features/settingsModel";
// Status and its sentence come with the lazily loaded catalog, to keep this page's own code small.
import { Button } from "../ui/Button";
import { CodeBlock, CopyButton, DOCS, EmptyState, PageSkeleton, Pill, copyText, toast, type PillTone } from "../ui/bits";
import { onPrefill } from "../ui/prefill";
import { Chips, DateInput, Field, Select, TextInput, Toggle } from "../ui/controls";
import { Icon, type IconName } from "../ui/icons";
import { Page, Section } from "../ui/Page";
import { Sheet } from "../ui/Sheet";

type Data = typeof import("../features/connections-data");
const PILL: Record<Status, [PillTone, IconName]> = {
  connected: ["good", "check"], builtin: ["accent", "link"], key: ["watch", "lock"], failed: ["bad", "warn"], recorded: ["watch", "clock"], off: ["neutral", "dot"],
};
const StatusPill = ({ s }: { s: Status }) => <Pill tone={PILL[s][0]} icon={PILL[s][1]}>{WORDS[s]}</Pill>;
// A chat bubble for chat alerts; kept here, not in the shared icon set, so the first screen stays small.
const CHAT = '<path d="M20 12a7.5 7.5 0 0 1-11 6.6L4 20l1.4-4.6A7.5 7.5 0 1 1 20 12z"/><path d="M8.5 12h.01M12 12h.01M15.5 12h.01"/>';
// The product's brand mark(s) in its colour (simple-icons); the letter glyph when there is none.
function Glyph({ c, big, data }: { c: Conn; big?: boolean; data: Data }) {
  const l = data.LOGOS[c.id], cls = "glyph" + (big ? " glyph-lg" : "") + (l ? " glyph-logo" : "") + (Array.isArray(l) && l.length > 1 ? ` glyph-n${l.length}` : "");
  return <span class={cls} data-cat={c.cat} aria-hidden="true">{!l ? c.glyph : l === "chat" ? <svg class="ic" viewBox="0 0 24 24" aria-hidden="true" focusable="false" dangerouslySetInnerHTML={{ __html: CHAT }} />
    : l.map((id) => { const [, on, dark, d] = data.BRANDS[id]; return <svg class="blogo" viewBox="0 0 24 24" style={`--b:${on};--bd:${dark || "var(--ink)"}`}><path d={d} /></svg>; })}</span>;
}

interface Ctx extends View { onToken: () => void; onChecked: (n: string, e: Entry) => void }

function TokenBox({ repo, onDone }: { repo: string; onDone: () => void }) {
  const [draft, setDraft] = useState("");
  return <div class="card card-pad token-box">
    <p>Paste a fine-grained token for <b>{repo}</b> with <b>Secrets</b> and <b>Actions: read and write</b>. <a href={tokenUrl(repo)} target="_blank" rel="noopener noreferrer">Create one</a> (30 days).
      It stays in this tab and goes only to api.github.com.</p>
    <div class="inline-form">
      <TextInput type="password" mono value={draft} onInput={(v) => setDraft(v.trim())} placeholder="github_pat_…" label="Fine-grained GitHub token" />
      <Button variant="filled" disabled={!draft} onClick={() => { setToken(draft, true); setDraft(""); onDone(); }}>Use it</Button>
    </div>
  </div>;
}

function SecretRow({ d, x }: { d: SecretDef; x: Ctx }) {
  const repo = x.app.repo;
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [ask, setAsk] = useState(false);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  const known = x.secrets && (!d.kind || d.kind === "secret") ? x.secrets.includes(d.name) : null;
  const kindWord = d.kind === "variable" ? "Repository variable" : d.kind === "gitlab" ? "GitLab CI/CD variable, masked" : "Repository secret";
  const onGitHub = () => { copyText(d.name).then((ok) => toast(ok ? `${d.name} copied: paste it as the name` : "Opened GitHub")); };
  const save = async () => {
    if (!ghToken()) { setAsk(true); return; }
    setBusy(true); setNote(null);
    try { await saveSecret(repo, d.name, value); setValue(""); setNote({ ok: true, text: `Saved ${d.name}. GitHub keeps it encrypted; nobody can read it back.` }); toast(`${d.name} saved`); x.onToken(); }
    catch (e) { setNote({ ok: false, text: (e as Error).message }); }
    setBusy(false);
  };
  const editable = !d.kind && !demoMode;
  return <li class="secret">
    <div class="secret-head">
      <span class="secret-name"><code>{d.name}</code><small>{kindWord}{d.optional ? ", optional" : ""}</small></span>
      {known === true ? <Pill tone="good">Saved</Pill> : known === false ? <Pill tone={d.optional ? "neutral" : "watch"} icon="lock">Not saved</Pill> : null}
      {d.kind === "gitlab" ? null : <Button size="sm" variant={editable && ghToken() ? "plain" : "tinted"} icon="external" external href={newSecretUrl(repo, d.kind === "variable" ? "variable" : "secret")} onClick={onGitHub}>Add on GitHub</Button>}
    </div>
    {editable ? <div class="secret-form">
      {d.multiline ? <textarea class="input mono" rows={3} value={value} spellcheck={false} aria-label={`Value for ${d.name}`} placeholder="Paste the value"
        onInput={(e) => setValue(e.currentTarget.value)} />
        : <TextInput type="password" mono value={value} onInput={setValue} placeholder="Paste the value" label={`Value for ${d.name}`} />}
      <div class="secret-actions">
        {d.browser === "linear" ? <Button size="sm" variant="plain" disabled={!value} onClick={async () => setNote(await testLinear(value.trim()))}>Test key here</Button> : null}
        <Button size="sm" variant="filled" icon="lock" loading={busy} disabled={!value.trim()} onClick={save}>Save secret</Button>
      </div>
    </div> : null}
    {ask && !ghToken() ? <TokenBox repo={repo} onDone={() => { setAsk(false); x.onToken(); save(); }} /> : null}
    {note ? <p class={`note note-${note.ok ? "good" : "bad"}`} role="status"><Icon name={note.ok ? "check" : "warn"} /><span>{note.text}</span></p> : null}
  </li>;
}

function SettingField({ d, value, onChange }: { d: SettingDef; value: unknown; onChange: (v: unknown) => void }) {
  const err = check(d.key, d.kind, value);
  if (d.kind === "bool") return <div class="field field-row"><span class="field-label" id={`l-${d.key}`}>{label(d.key)}<small>{brief(d.help)}</small></span>
    <Toggle checked={!!value} onChange={onChange} labelledBy={`l-${d.key}`} /></div>;
  if (d.kind === "choices") {
    const list = Array.isArray(value) ? value as string[] : [];
    return <div class="field"><span class="field-label">{label(d.key)}</span><div class="choice-row">
      {(d.choices || []).map((o) => <label class="choice"><input type="checkbox" checked={list.includes(o)} onChange={(e) => onChange(e.currentTarget.checked ? [...list, o] : list.filter((y) => y !== o))} />{o}</label>)}
    </div><p class="field-hint">{brief(d.help)}</p></div>;
  }
  return <Field label={label(d.key)} hint={brief(d.help)} error={err || null}>{(id) =>
    d.kind === "list" ? <Chips id={id} values={Array.isArray(value) ? value as string[] : []} onChange={onChange} label={label(d.key)} />
      : d.kind === "date" ? <DateInput id={id} value={String(value || "")} onInput={onChange} />
        : d.kind === "choice" ? <Select id={id} value={String(value ?? "")} onChange={onChange} options={(d.choices || []).map((o) => ({ value: o, label: o }))} />
          : <TextInput id={id} value={String(value ?? "")} onInput={onChange} />}</Field>;
}

function SettingsForm({ c, x }: { c: Conn; x: Ctx }) {
  const defs = (x.settings?.settings || []).filter((d) => d.key.startsWith(c.prefix + "."));
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  if (!defs.length) return null;
  const now = (k: string) => valueAt(x.settings?.values, k);
  const changes: Record<string, unknown> = {};
  for (const d of defs) if (d.key in draft && !same(draft[d.key], now(d.key))) changes[d.key] = draft[d.key];
  const bad = Object.entries(changes).some(([k, v]) => check(k, defs.find((d) => d.key === k)!.kind, v));
  const kinds = Object.fromEntries(defs.map((d) => [d.key, d.kind]));
  return <section class="sheet-sec"><h3>Settings</h3>
    <div class="form">{defs.map((d) => <SettingField d={d} value={d.key in draft ? draft[d.key] : now(d.key)} onChange={(v) => setDraft({ ...draft, [d.key]: v })} />)}</div>
    {Object.keys(changes).length && !bad ? <div class="conn-send">
      <Send app={x.app} title={`StackVitals: ${c.name} settings`} req={request([], changes)} who="anyone with write access to this repo"
        lands=".github/stackvitals.toml on the default branch (a pull request when it is protected)" when="as soon as the workflow has run" />
      <CopyButton text={tomlSnippet(changes, kinds)} label="Copy as TOML" />
    </div> : null}
  </section>;
}

function TestConnection({ c, e, x }: { c: Conn; e: Entry | null; x: Ctx }) {
  const [state, setState] = useState<"idle" | "wait" | "late" | "error">("idle");
  const [err, setErr] = useState("");
  const [live] = useState({ on: true });
  useEffect(() => () => { live.on = false; }, []);
  const last = e?.check;
  const check = checkIssueUrl(x.app, c.check!, c.name);
  const wait = async () => {
    setState("wait");
    let got;
    try { got = await waitForCheck(c.check!, last?.checked_at || "1970-01-01T00:00:00Z", () => live.on); }
    catch (er) { if (live.on) { setErr((er as Error).message); setState("error"); } return; }
    if (!live.on) return;
    if (got) { x.onChecked(c.check!, got); setState("idle"); toast(got.check?.ok ? `${c.name} works` : `${c.name}: check failed`, got.check?.ok ? "good" : "bad"); }
    else setState("late");
  };
  const run = async () => {
    try { await startCheck(x.app, c.check!); wait(); } catch (er) { setErr((er as Error).message); setState("error"); }
  };
  return <section class="sheet-sec"><h3>Test connection</h3>
    {last ? <div class={`note note-${last.ok ? "good" : "bad"}`} role="status"><Icon name={last.ok ? "check" : "warn"} />
      <span><b>{last.ok ? `Working${last.as ? `, as ${last.as}` : ""}.` : "Not working."}</b> {last.detail}{!last.ok && last.fix ? <><br /><b>Fix:</b> {last.fix}</> : null}
        <small class="when">Tested {ago(last.checked_at)}</small></span></div> : <p class="muted">Not tested yet. One cheap call to {c.name} proves the key and settings work.</p>}
    {demoMode ? <p class="muted">Demo data: there is nothing to test.</p> : <div class="test-row">
      {ghToken() ? <Button variant="tinted" icon="play" loading={state === "wait"} onClick={run}>Test connection</Button>
        : <Button variant="tinted" icon="external" external href={check.url} onClick={() => { onPrefill(check, "Press Submit on GitHub; the result shows here")(); wait(); }}>Test on GitHub</Button>}
      {state === "wait" ? <span class="muted" role="status"><span class="spin" aria-hidden="true" /> A short run tests it; this takes a minute or two.</span> : null}
    </div>}
    {state === "late" ? <p class="note note-watch"><Icon name="clock" /><span>No result yet. The run may still be going: <a href={x.app.links?.actions} target="_blank" rel="noopener noreferrer">open Actions</a>, then reopen this page.</span></p> : null}
    {state === "error" ? <p class="note note-bad" role="alert"><Icon name="warn" /><span>{err}</span></p> : null}
  </section>;
}

function ConnSheet({ c, open, x, data, onClose }: { c: Conn | null; open: boolean; x: Ctx; data: Data; onClose: () => void }) {
  if (!c) return null;
  const e = data.entryOf(c, x.entries), s = data.statusFor(c, x);
  return <Sheet open={open} onClose={onClose} title={c.name} size="md"
    footer={<><Button variant="plain" href={DOCS + c.doc} external iconEnd="external">Learn more</Button><Button variant="filled" onClick={onClose}>Done</Button></>}>
    <div class="conn-top"><Glyph c={c} big data={data} /><div><StatusPill s={s} />{c.tested ? <span class="tested"><Icon name={c.tested === "Recorded" ? "about" : "check"} />{c.tested === "Recorded" ? "Tested on recorded answers" : `Tested ${c.tested.toLowerCase()}`}</span> : null}
      <p class="conn-detail">{data.detail(c, s, e, x)}</p></div></div>
    <section class="sheet-sec"><h3>What it unlocks</h3><ul class="ticks">{c.unlocks.map((u) => <li><Icon name="check" /><span>{u}</span></li>)}</ul></section>
    {c.id === "github" ? <section class="sheet-sec"><h3>What the workflow token reads</h3><dl class="kv">{data.PERMS.map(([k, v]) => <><dt>{k}</dt><dd>{v}</dd></>)}</dl></section> : null}
    <section class="sheet-sec"><h3>{c.kind === "builtin" ? "How it works" : "How to connect"}</h3><ol class="steps">{c.steps(x.app.repo).map((st) => <li><div>
      <p>{st.text}</p>{st.code ? <CodeBlock code={st.code} title={st.file} /> : null}
      {st.href ? <Button size="sm" variant="tinted" href={st.href} external icon="external">{st.action || "Open"}</Button> : null}
      {st.to ? <Button size="sm" variant="tinted" href={st.to} icon="right" onClick={onClose}>{st.action || "Open Settings"}</Button> : null}</div></li>)}</ol></section>
    {c.secrets?.length ? <section class="sheet-sec"><h3>{c.secrets.length === 1 ? "Secret" : "Secrets"}</h3><ul class="secrets card">{c.secrets.map((d) => <SecretRow d={d} x={x} />)}</ul>
      <p class="muted">{ghToken() ? "Sealed in this browser with the repo's key and sent straight to GitHub; nobody can read it back, StackVitals included." : "Add them on GitHub, or save them here with a token: sealed in this browser, sent only to GitHub."}
        {c.example ? " The names are examples: any name works if the workflow passes it." : ""}</p></section> : null}
    {c.prefix ? <SettingsForm c={c} x={x} /> : null}
    {c.check ? <TestConnection c={c} e={e} x={x} /> : null}
  </Sheet>;
}

function CardBtn({ c, s, data, onOpen }: { c: Conn; s: Status; data: Data; onOpen: () => void }) {
  return <button type="button" class="conn press" onClick={onOpen} aria-haspopup="dialog" aria-label={`${c.name}: ${WORDS[s]}. ${c.unlocks[0]}`}>
    <Glyph c={c} data={data} /><span class="conn-text"><b>{c.name}</b><span>{c.unlocks[0]}</span></span><StatusPill s={s} />
  </button>;
}

export default function Connections({ app, route }: PageProps) {
  const f = useFiles<{ c: { connectors?: Record<string, Entry> }; s: SettingsFile }>({ c: "connectors.json", s: "settings.json" });
  const [data, setData] = useState<Data | null>(null);
  const [secrets, setSecrets] = useState<string[] | null>(null);
  const [tick, setTick] = useState(0);
  const [fresh, setFresh] = useState<Record<string, Entry>>({});
  const [sel, setSel] = useState<string | null>(route.rest[0] || null);
  const [open, setOpen] = useState(!!route.rest[0]);
  const [askToken, setAskToken] = useState(false);
  useEffect(() => { import("../features/connections-data").then(setData, () => setData(null)); }, []);
  useEffect(() => { if (app?.repo && !demoMode) listSecrets(app.repo).then(setSecrets); }, [app?.repo, tick]);
  if (!app) return <Page title="Connections"><EmptyState icon="connections" title="No repository data yet.">Connections show once the StackVitals workflow has run.</EmptyState></Page>;
  if (!data || !f.ready) return <PageSkeleton />;
  const x: Ctx = { app, entries: { ...(f.c?.connectors || {}), ...fresh }, secrets, settings: f.s, onToken: () => setTick((n) => n + 1),
    onChecked: (n, e) => setFresh((m) => ({ ...m, [n]: e })) };
  const rows = data.CONNS.map((c) => ({ c, s: data.statusFor(c, x) }));
  const groups: [string, string, string][] = [["on", "Connected", "Reading or sending now."], ["attention", "Needs attention", "A key is missing, expiring or refused."],
    ["available", "Available", "What else StackVitals can read or send to."]];
  const n = (b: string) => rows.filter((r) => BUCKET[r.s] === b).length;
  return <Page title="Connections" subtitle="What StackVitals reads and sends, and what each one unlocks."
    toolbar={!demoMode && !ghToken() ? <Button variant="tinted" icon="lock" onClick={() => setAskToken(true)}>Use a token</Button> : null}>
    <div class="conn-sum" aria-label="Summary"><Pill tone="good" icon="check">{n("on")} on</Pill>{n("attention") ? <Pill tone="watch" icon="warn">{n("attention")} need attention</Pill> : null}<Pill tone="neutral" icon="plus">{n("available")} available</Pill></div>
    {askToken && !ghToken() ? <TokenBox repo={app.repo} onDone={() => { setAskToken(false); setTick((t) => t + 1); }} /> : null}
    {groups.map(([b, title, desc]) => { const list = rows.filter((r) => BUCKET[r.s] === b); return list.length ? <Section title={title} description={desc}>
      <div class="conn-grid">{list.map((r) => <CardBtn c={r.c} s={r.s} data={data} onOpen={() => { setSel(r.c.id); setOpen(true); }} />)}</div></Section> : null; })}
    <p class="note conn-privacy"><Icon name="lock" /><span>Keys live in this repo's GitHub secrets and go only to their own service. Nothing passes through a StackVitals server; there isn't one.{" "}
      <a href={DOCS + "privacy.md"} target="_blank" rel="noopener noreferrer">What leaves your repo</a></span></p>
    <ConnSheet key={sel || ""} c={data.CONNS.find((c) => c.id === sel) || null} open={open} x={x} data={data} onClose={() => setOpen(false)} />
  </Page>;
}
