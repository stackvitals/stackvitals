// CI Health's lower sections that load on their own: when a flake began, quarantine and tickets, test impact with what it
// learned, the runs left out of flake counts, likely causes, and the builder that sets the CI commands up in a workflow.
import { useState } from "preact/hooks";
import { useFiles } from "../../data/files";
import { day, short } from "../../data/format";
import type { AppJson, CiJson } from "../../data/types";
import { valueAt, type SettingsFile } from "../../features/settingsModel";
import { Button } from "../../ui/Button";
import { CodeBlock, EmptyState, Pill } from "../../ui/bits";
import { Card, Columns, Section, Stat, Stats } from "../../ui/Page";
import { Table } from "../../ui/Table";
import { Facts, Framed, Panel } from "./parts";
import { CiSetup, ask, useRunner } from "./setup";
import { PRESETS, sq } from "./workflowgen";

type R = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
const ext = { target: "_blank", rel: "noopener noreferrer" };
const KIND_HELP: Record<string, string> = {
  infrastructure: "the runner itself (disk, shutdown, service busy)", network: "a host or connection that didn't answer",
  concurrency: "a race or deadlock between threads", timing: "a wait or timeout that ran out", "resource leak": "files or sockets left open",
  "async wait": "a UI or async step checked too early", time: "time zones, daylight saving or the clock", randomness: "a random seed or input",
  "floating point": "rounding in a numeric comparison", "shared state": "data left behind by another test", io: "a file or permission on disk",
  ordering: "results compared in a fixed order that isn't guaranteed" };
export const kindHelp = (k?: string | null) => (k ? KIND_HELP[k] || k : "");

// When a test or job began to flake: a Fisher test on runs before vs after its first flake (ci/analyze.py _began).
export function Began({ b, app }: { b: R; app: AppJson }) {
  const landed: string[] = b.landed || [];
  return <Panel title="Before and after the first flake" state={b.clear ? <Pill tone="watch">Began with a change</Pill> : <Pill tone="neutral" icon={null}>May have flaked all along</Pill>}>
    <Facts rows={[
      ["First flake", <span class="num">{day(b.first)}</span>],
      ["Runs before it", <span class="num">{b.runs_before} runs, none flaked</span>],
      ["Runs since", <span class="num">{b.flakes} flakes in {b.runs_after} runs</span>],
      ["Chance it's luck", <span class="num">p = {b.p}{b.clear ? ": unlikely, so something that landed around then probably started it" : ": too few runs before the first flake to say"}</span>],
      b.clear && ["Pushed the day before", landed.length ? <ul class="ci-landed">{landed.map((sha) => <li><a class="mono-soft" href={`https://github.com/${app.repo}/commit/${sha}`} {...ext}>{sha.slice(0, 7)}</a></li>)}</ul>
        : "Nothing reached the default branch: look at what changed outside the code (runners, services, data)."],
    ]} />
  </Panel>;
}

// Quarantine: what is on the list now, the expiry rule, overdue tests, the runners it works with and the tickets filed.
export function Quarantine({ ci }: { ci: CiJson }) {
  const f = useFiles<{ q: string[]; tk: R; settings: SettingsFile }>({ q: "../ci/quarantine.json", tk: "../ci/tickets.json", settings: "settings.json" });
  const [cmds, setCmds] = useState(false);
  const tests = new Set((ci.tests || []).map((t) => t.id));
  const expired: string[] = (ci as R).quarantine_expired || [];
  const values = f.settings?.values;
  const maxDays = valueAt(values, "ci.quarantine.max_days") as number | undefined;
  const on = valueAt(values, "automation.quarantine");
  const listed = (f.q || []).filter((id) => tests.has(id) || !tests.size);
  const tickets: R[] = Object.entries(f.tk || {}).filter(([id]) => tests.has(id)).map(([id, t]) => ({ ...(t as R), ticket: (t as R).id, id }));
  const jiraUrl = valueAt(values, "connectors.jira.url") as string | undefined;
  return <Section title="Quarantine and tickets" description="Flaky tests can stop failing builds while they wait for a fix; each can get its own Jira or Linear ticket.">
    <Stats>
      <Stat label="In quarantine now" value={f.ready ? (f.q ? listed.length : "–") : "…"} note={f.q ? "known flaky, still run and reported" : "the list lives on the data branch"} />
      <Stat label="Past the time limit" value={expired.length} note={maxDays ? `out after ${maxDays} days: they fail builds again` : "no limit set ([ci.quarantine] max_days)"} />
      <Stat label="Flaky-test tickets" value={tickets.length ? `${tickets.filter((t) => t.open).length} open` : "–"} note={tickets.length ? `${tickets.length} filed, closed once fixed` : "off: set flaky_tickets under Jira or Linear"} />
    </Stats>
    {on === false || on === "off" ? <p class="ci-say"><span class="sv-mark sv-mark-neutral" aria-hidden="true" />Quarantine is turned off in the settings.</p> : null}
    <Columns>
      <Framed title="Quarantined tests" note={maxDays ? `${maxDays}-day limit` : undefined}>
        <Table name="quarantine" caption="Quarantined tests" search={false} rows={listed.map((id) => ({ id, overdue: expired.includes(id) }))} columns={[
          { key: "id", label: "Test", primary: true, render: (r) => <a class="mono-soft" href={`#/ci/test/${encodeURIComponent(r.id)}`}>{short(r.id, 70)}</a> },
          { key: "overdue", label: "Time limit", raw: (r) => (r.overdue ? "overdue" : "within"), render: (r) => (r.overdue ? <Pill tone="watch">Overdue</Pill> : <Pill tone="neutral" icon={null}>Within</Pill>) }]}
          empty={<Card><EmptyState icon="check" title={f.q ? "Nothing is quarantined." : "No quarantine list readable here."}>{f.q ? "" : "It's written to ci/quarantine.json on the data branch when quarantine is on."}</EmptyState></Card>} />
      </Framed>
      <Framed title="Tickets per flaky test">
        <Table name="flaky-tickets" caption="Tickets per flaky test" search={false} rows={tickets} columns={[
          { key: "key", label: "Ticket", primary: true, render: (t) => (t.tracker === "jira" && jiraUrl ? <a href={`${jiraUrl.replace(/\/$/, "")}/browse/${t.key}`} {...ext}>{t.key}</a> : <span>{t.key}</span>) },
          { key: "tracker", label: "Tracker", raw: (t) => (t.tracker === "jira" ? "Jira" : t.tracker === "linear" ? "Linear" : t.tracker || "–") },
          { key: "id", label: "Test", render: (t) => <span class="mono-soft">{short(t.id, 50)}</span> },
          { key: "open", label: "State", filter: true, raw: (t) => (t.open ? "open" : "closed"), render: (t) => <Pill tone={t.open ? "watch" : "good"}>{t.open ? "Open" : "Closed when fixed"}</Pill> }]}
          empty={<Card><EmptyState icon="about" title="No tickets filed here.">Set flaky_tickets = true and ticket_project (Jira) or ticket_team (Linear) in Settings; a ticket opens when a test turns flaky and closes when it's fixed.</EmptyState></Card>} />
      </Framed>
    </Columns>
    <Panel title="Apply it in your test command" class="ci-apply"
      bar={<><Button size="sm" variant="tinted" iconEnd="down" onClick={() => ask("quarantine")}>Add it to your CI</Button>
        <Button size="sm" variant="plain" expanded={cmds} onClick={() => setCmds(!cmds)} iconEnd={cmds ? "up" : "down"}>The commands</Button></>}>
      <Facts rows={[["pytest", "Still runs a quarantined test, but it can't fail the run"], ["Jest, Vitest, go test, Playwright, Maven Surefire, dotnet test", "Leave it out by name"],
        ["Any other runner (RSpec, Gradle)", "Wrap the test command: it passes when only quarantined tests failed"]]} />
      {cmds ? <CodeBlock title="Workflow step" code={"pytest $(stackvitals ci quarantine --print pytest)\nnpx jest $(stackvitals ci quarantine --print jest)\nstackvitals ci quarantine --reports 'out/*.xml' -- bundle exec rspec"} /> : null}
    </Panel>
  </Section>;
}

// Test impact: the replay on past pull requests, and the folders it learned send failures to which test files.
export function Impact({ app, ci }: { app: AppJson; ci: CiJson }) {
  const run = useRunner(app, ci), branch = app.default_branch || "main";
  const f = useFiles<{ im: { learned?: Record<string, Record<string, number>> } }>({ im: "../ci/impact.json" });
  const [cmd, setCmd] = useState(false);
  const b = (ci as R).impact as R | null | undefined;
  const learned = Object.entries(f.im?.learned || {}).map(([folder, tests]) => {
    const top = Object.entries(tests).sort((a, c) => c[1] - a[1]);
    return { folder: folder || "(top level)", tests: top.length, failures: top.reduce((a, [, n]) => a + n, 0), top: top.slice(0, 3) };
  }).sort((a, c) => c.failures - a.failures);
  return <Section title="Test impact" description="Run only the tests a change can affect. Each past pull request is judged with only what was known before it.">
    {b && b.failures ? <Stats>
      <Stat label="Real failures it would have run" value={`${b.caught} of ${b.failures}`} note={b.recall != null ? `${Math.round(b.recall * 100)}%` : undefined} />
      <Stat label="Test files it would have skipped" value={b.skipped_share != null ? `${Math.round(b.skipped_share * 100)}%` : "–"} note={`over ${b.prs} pull requests`} />
    </Stats> : <Card><EmptyState icon="clock" title={b ? "No real test failure on past pull requests to replay yet." : "Not replayed yet."}>
      {b ? `${b.prs} pull requests read; the replay needs pull requests whose tests failed for real (flaky ones don't count).`
        : "It needs test reports in CI and the Team Flow module (for each pull request's changed files); the next run with both fills it in."}</EmptyState></Card>}
    {learned.length ? <Framed title="What it learned" note="A change in this folder has failed these test files.">
      <Table name="impact-learned" caption="What it learned: a change in this folder has failed these test files" search={false} rows={learned.slice(0, 15)} columns={[
        { key: "folder", label: "Changed folder", primary: true, render: (r) => <span class="mono-soft">{r.folder}</span> },
        { key: "top", label: "Test files that failed", raw: (r) => r.tests, render: (r) => <ul class="ci-cell-list">{r.top.map(([t, n]: [string, number]) =>
          <li><span class="mono-soft">{short(t, 60)}</span> <span class="muted num">{n}×</span></li>)}</ul> },
        { key: "tests", label: "Test files", num: true },
        { key: "failures", label: "Failures", num: true }]} />
    </Framed> : null}
    <Panel title="Pick the tests for a pull request" class="ci-apply"
      bar={<><Button size="sm" variant="tinted" iconEnd="down" onClick={() => ask("impact")}>Add it to your CI</Button>
        <Button size="sm" variant="plain" expanded={cmd} onClick={() => setCmd(!cmd)} iconEnd={cmd ? "up" : "down"}>The command</Button></>}>
      <Facts rows={[["What it prints", 'The test files to run, "all" when a build or settings file changed, or nothing when no test is touched'],
        ["What it reads", "The pull request's changed files and the learned map above, from the data branch"]]} />
      {cmd ? <CodeBlock inline code={`stackvitals ci impact --base origin/${branch} --tests ${sq(run.tests || "<your test files glob>")}`}
        note={run.runner ? `The test files glob for ${PRESETS[run.runner].name}, as in the workflow builder below.` : "Pick the test runner in the builder below to fill in the test files glob."} /> : null}
    </Panel>
  </Section>;
}

// What keeps the flake numbers honest: outages, runner trouble and workflows that rerun on PR edits.
export function Signals({ ci }: { ci: CiJson }) {
  const c = ci as R;
  const edits: string[] = c.pr_edit_workflows || [];
  const rows = [
    c.test_outages ? { id: "outage", what: "Runs where most tests failed at once", n: c.test_outages, means: "An outage, not flakes: left out of every test's flake count." } : null,
    c.infra_events ? { id: "infra", what: "Runs that hit runner or service trouble", n: c.infra_events, means: "Disk full, runner shut down or rate limits." } : null,
    edits.length ? { id: "edits", what: "Workflows that re-run when a pull request's title or labels change", n: edits.length,
      means: <>A pass and a fail on the same code there aren't counted as flakes: {edits.map((w, i) => <>{i ? ", " : ""}<code class="code-inline">{w}</code></>)}</> } : null,
  ].filter((r): r is NonNullable<typeof r> => !!r);
  if (!rows.length) return null;
  return <Framed title="Left out of the flake counts" note="What keeps the flake numbers honest.">
    <Table name="ci-signals" caption="Left out of the flake counts" search={false} rows={rows} columns={[
      { key: "what", label: "What", primary: true }, { key: "n", label: "Count", num: true },
      { key: "means", label: "What it means", raw: (r) => (typeof r.means === "string" ? r.means : ""), render: (r) => r.means }]} />
  </Framed>;
}

// Root causes: flaky tests and jobs by the kind their usual failure looks like.
export function Causes({ rows }: { rows: R[] }) {
  const counts: Record<string, number> = {};
  for (const r of rows) if (r.state === "flaky") counts[r.flake || "not recognised"] = (counts[r.flake || "not recognised"] || 0) + 1;
  const list = Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([kind, n]) => ({ id: kind, kind, n }));
  if (!list.length) return null;
  return <Framed title="Likely causes" note="From each flaky item's usual error.">
    <Table name="likely-causes" caption="Likely causes" search={false} rows={list} columns={[
      { key: "kind", label: "Cause", primary: true, render: (r) => <span class="ci-cap">{r.kind}</span> },
      { key: "n", label: "Flaky tests and jobs", num: true },
      { key: "help", label: "What it usually means", raw: (r) => kindHelp(r.kind), render: (r) => (KIND_HELP[r.kind] ? kindHelp(r.kind) : "–") }]} />
  </Framed>;
}

// The builder that puts the CI commands in a workflow file.
export function Setup({ app, ci }: { app: AppJson; ci: CiJson }) {
  return <Section id="ci-setup" title="Set up in your CI" description="Pick what your test runs should do; the page writes the workflow file and adds it to the repo in one click, through GitHub or as a pull request.">
    <CiSetup app={app} ci={ci} />
  </Section>;
}
