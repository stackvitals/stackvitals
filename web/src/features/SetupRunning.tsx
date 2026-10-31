// Setup for a repo that already runs StackVitals: its health, what it writes, and the ways to change or re-run it.
import type { PageProps } from "../app/routes";
import { ago } from "../data/format";
import { demoMode } from "../data/repos";
import { Button } from "../ui/Button";
import { Pill } from "../ui/bits";
import { Icon } from "../ui/icons";
import { Card, GroupedList, ListRow, Page, Section } from "../ui/Page";
import { health } from "./Health";

const MOD: Record<string, string> = { ci: "CI Health", flow: "Pull Requests", delivery: "Delivery", insights: "Insights", community: "Community", portal: "Portal",
  alerts: "Alerts", deps: "Dependencies", supply: "Supply chain", vulns: "Vulnerabilities" };

export function Running({ app }: { app: NonNullable<PageProps["app"]> }) {
  const h = health(app), l = app.links || {};
  const wf = l.workflow ? `https://github.com/${app.repo}/edit/${app.default_branch || "main"}/.github/workflows/${l.workflow}` : null;
  return <Page title={`${app.repo} is set up`} subtitle="StackVitals already runs here. Change what it does, run it now, or set up another repo."
    toolbar={<Button variant="plain" href="#/setup?pick=1" icon="plus">Set up another repo</Button>}>
    <div class={`note note-${h.tone === "good" ? "good" : h.tone === "watch" ? "watch" : "bad"}`} role="status"><Icon name={h.tone === "good" ? "check" : "clock"} />
      <span><b>{h.tone === "good" ? "Running" : h.title}.</b> Data written {ago(h.when)}{app.run?.number ? `, run #${app.run.number}` : ""}
        {app.run?.next ? `; next run ${ago(app.run.next).replace(" ago", "")}` : "; it runs on the workflow's schedule"}.</span></div>
    <Section title="What it writes" description="Each module and when it last wrote its file.">
      <GroupedList label="Modules">{Object.entries(app.modules || {}).map(([k, m]) => <ListRow title={MOD[k] || k} subtitle={m.file}
        trailing={m.updated ? <Pill tone="good">{ago(m.updated)}</Pill> : <Pill tone="neutral">not yet</Pill>} />)}</GroupedList>
    </Section>
    <Section title="Change it">
      <Card class="go-card"><div class="go-buttons">
        {l.actions ? <Button variant="filled" href={l.actions} external icon="play">Run it now</Button> : null}
        <Button variant="tinted" href="#/settings" icon="settings">Change the settings</Button>
        {wf ? <Button variant="tinted" href={wf} external iconEnd="external">Edit the workflow</Button> : null}
        {demoMode ? null : <Button variant="plain" href={`#/setup?repo=${encodeURIComponent(app.repo)}&check=1`} icon="refresh">Check the setup again</Button>}
      </div></Card>
    </Section>
  </Page>;
}

