// Installation health from app.json: how fresh the data is, which modules wrote it, notes from the last run, and
// one-click links to run the workflow or change its settings.
import { useEffect, useState } from "preact/hooks";
import { freshest, json } from "../data/files";
import { ago, parseStamp } from "../data/format";
import type { AppJson, SettingsJson } from "../data/types";
import { Button, safeHref } from "../ui/Button";
import { Icon } from "../ui/icons";
import { GroupedList, ListRow } from "../ui/Page";
import { Pill } from "../ui/bits";
import { Sheet } from "../ui/Sheet";

const NAMES: Record<string, string> = { ci: "CI Health", flow: "Pull Requests", delivery: "Delivery", insights: "Insights", community: "Community",
  portal: "Portal", alerts: "Alerts", deps: "Dependencies", supply: "Supply chain", vulns: "Vulnerabilities" };

export type HealthTone = "good" | "watch" | "bad";
export function health(app: AppJson | null | undefined): { tone: HealthTone; when: string | null; title: string } {
  const when = freshest(app);
  if (!app || !when) return { tone: "bad", when: null, title: "No run has written data yet" };
  if (app.run?.conclusion && app.run.conclusion !== "success") return { tone: "bad", when, title: `The last run ${app.run.conclusion === "failure" ? "failed" : app.run.conclusion}` };
  const h = (Date.now() - parseStamp(when)) / 3.6e6;
  return h < 6 ? { tone: "good", when, title: "Running on schedule" } : h < 26 ? { tone: "watch", when, title: "Data is a few hours old" } : { tone: "bad", when, title: "Data is getting old" };
}

export function privateOnPages(app: AppJson | null | undefined): boolean {
  return app?.visibility === "private" && /\.github\.io$/.test(location.hostname);
}

function useNotes(app: AppJson | null | undefined): string[] {
  const [notes, setNotes] = useState<string[]>([]);
  useEffect(() => {
    if (!app) { setNotes([]); return; }
    json<SettingsJson>("settings.json").then((s) => setNotes([...(app.notes || []), ...(s?.notes || [])]));
  }, [app]);
  return notes;
}

export function HealthSheet({ app, open, onClose }: { app: AppJson | null | undefined; open: boolean; onClose: () => void }) {
  const h = health(app);
  const notes = useNotes(open ? app : null);
  return <Sheet open={open} onClose={onClose} title="Installation" description={app?.repo || "No repository data"}
    footer={<>{app?.links?.edit_settings ? <Button variant="plain" href={app.links.edit_settings} external icon="settings">Edit settings</Button> : null}
      {app?.links?.actions ? <Button variant="filled" href={app.links.actions} external icon="play">Run it now</Button> : null}</>}>
    <div class={`health-top tone-${h.tone}`}>
      <span class="light"><Icon name={h.tone === "good" ? "check" : h.tone === "watch" ? "clock" : "warn"} /></span>
      <div><b>{h.title}</b><small>{h.when ? `Data written ${ago(h.when)}` : "The first run of the StackVitals workflow writes it."}
        {app?.run?.number ? `, run #${app.run.number}` : ""}{app?.run?.next ? `. Next ${ago(app.run.next).replace(" ago", "")}` : ""}</small></div>
    </div>
    {privateOnPages(app) ? <div class="note note-bad" role="alert"><Icon name="lock" /><span>This repo is private, but this page is on GitHub Pages, which is public on most plans.
      Turn Pages off and set <code>pages: artifact</code>, or open it with <code>stackvitals ui {app?.repo}</code>.</span></div> : null}
    {notes.map((n) => <div class="note note-watch"><Icon name="warn" /><span>{n}</span></div>)}
    {app ? <>
      <h3 class="sheet-h3">Modules</h3>
      <GroupedList label="Modules and when each wrote its data">
        {Object.entries(app.modules || {}).map(([k, m]) => <ListRow title={NAMES[k] || k} subtitle={m.file}
          trailing={m.updated ? <Pill tone={(Date.now() - parseStamp(m.updated)) / 3.6e6 < 26 ? "good" : "watch"}>{ago(m.updated)}</Pill> : <Pill tone="neutral">not yet</Pill>} />)}
      </GroupedList>
      <dl class="kv">
        <dt>Default branch</dt><dd>{app.default_branch || "–"}</dd>
        <dt>Visibility</dt><dd>{app.visibility || "–"}</dd>
        {app.links?.workflow ? <><dt>Workflow</dt><dd><code>{app.links.workflow}</code></dd></> : null}
        {app.links?.settings_file ? <><dt>Settings</dt><dd><a href={safeHref(app.links.settings_file)} target="_blank" rel="noopener noreferrer">.github/stackvitals.toml</a></dd></> : null}
      </dl>
    </> : null}
  </Sheet>;
}

// The one-line strip on Overview and the sidebar footer both open the sheet.
export function HealthStrip({ app }: { app: AppJson | null | undefined }) {
  const [open, setOpen] = useState(false);
  const h = health(app);
  return <>
    <div class={`hstrip tone-${h.tone}`}>
      <span class={`dot dot-${h.tone}`} aria-hidden="true" />
      <span class="hstrip-text"><b>{h.title}.</b> {h.when ? `Data written ${ago(h.when)}` : "Waiting for the first run"}{app?.default_branch ? `, from ${app.default_branch}` : ""}.</span>
      <Button size="sm" variant="tinted" onClick={() => setOpen(true)}>Installation</Button>
      {app?.links?.actions ? <Button size="sm" variant="plain" href={app.links.actions} external icon="play">Run now</Button> : null}
    </div>
    <HealthSheet app={app} open={open} onClose={() => setOpen(false)} />
  </>;
}

export function SideHealth({ app }: { app: AppJson | null | undefined }) {
  const [open, setOpen] = useState(false);
  const h = health(app);
  return <>
    <button type="button" class="side-health press" onClick={() => setOpen(true)} aria-label={`Installation: ${h.title}. ${h.when ? `Data written ${ago(h.when)}` : ""}`}>
      <span class={`dot dot-${h.tone}`} aria-hidden="true" />
      <span><b>{h.when ? `Updated ${ago(h.when)}` : "No data yet"}</b><small>{h.title}</small></span>
    </button>
    <HealthSheet app={app} open={open} onClose={() => setOpen(false)} />
  </>;
}
