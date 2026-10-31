// The Review sheet: what changes (old to new, with the alert replay), then how it reaches the repo. With GitHub connected,
// one click commits the file (a pull request when the branch is protected) or runs the workflow; without, an issue or TOML.
import { useState } from "preact/hooks";
import { refresh } from "../data/files";
import { demoMode } from "../data/repos";
import type { AppJson } from "../data/types";
import { issueUrl } from "../data/requestIssue";
import { request } from "../data/write";
import { Button, safeHref } from "../ui/Button";
import { CodeBlock, CopyButton, copyText, toast } from "../ui/bits";
import { PasteNote, onPrefill } from "../ui/prefill";
import { Icon } from "../ui/icons";
import { Sheet } from "../ui/Sheet";
import { isRepo, isWorkflowFile } from "../github/names";
import { SETTINGS_FILE, commitFile, dispatchRequest, runStatus, tokenNow, type Outcome } from "./settingsApply";
import { fmt, label, tomlSnippet, valueAt, type Changes, type SettingDef } from "./settingsModel";
import { savePending, type Pending } from "./settingsPending";
import { tomlEdit, workflowEdit, yamlScalar } from "./settingsToml";

interface Props {
  open: boolean; onClose: () => void; app: AppJson; defs: SettingDef[]; changes: Changes; values: unknown; wf: Record<string, string> | null;
  replays: Record<string, [number, number, boolean]>; onSent: (keys: string[], wf?: Record<string, string | null>) => void;
}

const SAID: Record<Outcome["kind"], string> = { committed: "Committed. The workflow runs on the push and publishes it in a few minutes.", pr: "The branch is protected, so the change waits in a pull request.",
  compare: "The branch is protected and Actions can't open pull requests here; open it from the branch.", same: "The file already says that; nothing to change." };

export function ReviewSheet({ open, onClose, app, defs, changes, values, wf, replays, onSent }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const [result, setResult] = useState<{ tone: "good" | "bad"; text: string; url?: string } | null>(null);
  const byKey = Object.fromEntries(defs.map((d) => [d.key, d]));
  const keys = Object.keys(changes), sk = keys.filter((k) => !k.startsWith("wf:")), wk = keys.filter((k) => k.startsWith("wf:"));
  const settings: Changes = Object.fromEntries(sk.map((k) => [k, changes[k]]));
  const inputs = Object.fromEntries(wk.map((k) => [k.slice(3), changes[k] as string | null]));
  const kinds = Object.fromEntries(defs.filter((d) => !d.key.startsWith("wf:")).map((d) => [d.key, d.kind]));
  const toml = tomlSnippet(settings, kinds);
  const yaml = wk.map((k) => (changes[k] === null ? `# ${k.slice(3)}: remove the line (back to "${byKey[k]?.default}")` : `${k.slice(3)}: ${yamlScalar(String(changes[k]))}`)).join("\n") + "\n";
  const req = request([], settings);
  const url = issueUrl(app, `StackVitals: change ${sk.length} setting${sk.length === 1 ? "" : "s"}`, req);
  const branch = app.default_branch || "main", wfFile = `.github/workflows/${isWorkflowFile(app.links?.workflow) ? app.links!.workflow : "stackvitals.yml"}`;
  // Writes with a token only to a plainly named repo, and the sheet says which one.
  const token = !!tokenNow() && !demoMode && isRepo(app.repo);
  const now = (k: string) => (k.startsWith("wf:") ? wf?.[k.slice(3)] ?? byKey[k]?.default : valueAt(values, k));

  const pend = (p: Omit<Pending, "settings" | "at">) => { savePending(app.repo, { settings, at: new Date().toISOString(), ...p }); onSent(sk); };
  const run = async (id: string, job: () => Promise<void>) => {
    setBusy(id); setResult(null);
    try { await job(); } catch (e) { setResult({ tone: "bad", text: `Not saved: ${e instanceof Error ? e.message : String(e)}` }); }
    setBusy(null);
  };
  const commit = () => run("commit", async () => {
    const out = await commitFile(app, SETTINGS_FILE, (t) => tomlEdit(t, settings, kinds), "settings");
    if (out.kind !== "same") pend({ via: out.kind, ...(out.url ? { url: out.url } : {}) }); else onSent(sk);
    setResult({ tone: "good", text: SAID[out.kind], ...(out.url ? { url: out.url } : {}) });
    toast(out.kind === "committed" ? "Saved to " + branch : out.kind === "same" ? "Nothing to change" : "Pull request opened");
  });
  const dispatch = () => run("dispatch", async () => {
    let r = await dispatchRequest(app, req);
    pend({ via: "dispatch", ...(r ? { run: r, url: r.html_url } : {}) });
    setResult({ tone: "good", text: r ? `Run #${r.run_number} is applying it; it shows in Activity with your name.` : "The workflow started; it shows in the Actions tab in a moment.", ...(r ? { url: r.html_url } : {}) });
    for (let i = 0; r && r.status !== "completed" && i < 60; i++) {
      await new Promise((ok) => setTimeout(ok, 5000));
      r = await runStatus(app, r.id).catch(() => r);
    }
    if (r?.status === "completed") { savePending(app.repo, { settings, at: new Date().toISOString(), via: "dispatch", run: r, url: r.html_url }); refresh(); }
  });
  const saveWorkflow = () => run("wf", async () => {
    const out = await commitFile(app, wfFile, (t) => workflowEdit(t, inputs), "workflow inputs");
    onSent(wk, inputs);
    setResult({ tone: "good", text: SAID[out.kind], ...(out.url ? { url: out.url } : {}) });
  });

  return <Sheet open={open} onClose={onClose} title={`Review ${keys.length} change${keys.length === 1 ? "" : "s"}`} description={`Writes to ${app.repo}`} size="lg"
    footer={<Button variant={result?.tone === "good" ? "filled" : "plain"} onClick={onClose}>{result?.tone === "good" ? "Done" : "Keep editing"}</Button>}>
    {keys.length ? <ul class="diff" aria-label="Changes">{keys.map((k) => {
      const d = byKey[k], r = replays[k], v = changes[k] === null ? d?.default : changes[k];
      return <li><span class="diff-t">{label(k)}<small class="mono">{k.replace(/^wf:/, "")}</small></span>
        <span class="diff-v"><s>{fmt(now(k), d?.kind || "", d?.unit)}</s><Icon name="right" /><b>{fmt(v, d?.kind || "", d?.unit)}</b></span>
        {r ? <span class="replay"><Icon name="refresh" />{!r[2] ? "Not enough data to replay." : v === 0 ? "Turns this alert off." : `Last 90 days: ${r[1]} alert${r[1] === 1 ? "" : "s"} instead of ${r[0]}.`}</span> : null}</li>;
    })}</ul> : <p class="muted">Nothing left to send.</p>}
    {result ? <div class={`note note-${result.tone}`} role={result.tone === "bad" ? "alert" : "status"}><Icon name={result.tone === "bad" ? "warn" : "check"} />
      <span>{result.text}{result.url ? <> <a href={safeHref(result.url)} target="_blank" rel="noopener noreferrer">Open on GitHub</a></> : null}</span></div> : null}
    {sk.length ? <section class="how" aria-labelledby="how-s">
      <h3 id="how-s" class="sheet-h3">Settings file</h3>
      <dl class="kv"><dt>Where</dt><dd><code>{SETTINGS_FILE}</code> on {branch}, edited in place (comments stay)</dd>
        <dt>Who can</dt><dd>anyone with write access to {app.repo}</dd><dt>When</dt><dd>the next run, a few minutes after saving</dd></dl>
      <div class="how-actions">
        {token ? <>
          <Button variant="filled" icon="check" loading={busy === "commit"} disabled={!!busy} onClick={commit}>Save to {branch} in {app.repo}</Button>
          <Button variant="tinted" icon="bolt" loading={busy === "dispatch"} disabled={!!busy} onClick={dispatch}>Run {app.repo}'s workflow with it</Button>
        </> : <>
          {url ? <Button variant="filled" icon="external" href={url.url} external onClick={() => { pend({ via: "issue" }); onPrefill(url, "Opened on GitHub: press Submit there")(); }}>Open as a GitHub issue</Button> : null}
          <Button variant="tinted" icon="link" href="#/settings/account" onClick={onClose}>Connect GitHub to save in one click</Button>
        </>}
        <Button variant="plain" icon="copy" onClick={async () => { const ok = await copyText(toml); toast(ok ? "TOML copied" : "Copy failed: select the text below", ok ? "good" : "bad"); if (ok && !token) pend({ via: "copy" }); }}>Copy TOML</Button>
      </div>
      {!token ? <PasteNote link={url} /> : null}
      <CodeBlock code={toml} title={SETTINGS_FILE} />
    </section> : null}
    {wk.length ? <section class="how" aria-labelledby="how-w">
      <h3 id="how-w" class="sheet-h3">Workflow file</h3>
      <p class="field-hint">These are inputs of the StackVitals step in <code>{wfFile}</code>, under <code>with:</code>.{token ? " Saving needs the Workflows permission on your token." : ""}</p>
      <div class="how-actions">
        {token ? <Button variant="filled" icon="check" loading={busy === "wf"} disabled={!!busy} onClick={saveWorkflow}>Save to the workflow in {app.repo}</Button>
          : <Button variant="filled" icon="external" href={`https://github.com/${app.repo}/edit/${encodeURIComponent(branch)}/${wfFile}`} external>Edit the workflow on GitHub</Button>}
        <CopyButton text={yaml} label="Copy the lines" />
      </div>
      <CodeBlock code={yaml} title={`${wfFile}, under with:`} />
    </section> : null}
  </Sheet>;
}
