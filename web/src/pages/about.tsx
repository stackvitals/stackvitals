// About: what StackVitals is, how it works (the numbered pipeline), what it measures, how accurate it is (its own lazy
// chunk), what it costs and needs, privacy in short, what each permission is for, how to remove it, and links.
import "./about.css";
import type { ComponentChildren } from "preact";
import type { PageProps } from "../app/routes";
import { Button } from "../ui/Button";
import { CodeBlock, InfoButton } from "../ui/bits";
import { Icon, type IconName } from "../ui/icons";
import { Card, Columns, Page, Section } from "../ui/Page";
import { Table } from "../ui/Table";
import { Accuracy, ModuleTable } from "./about/parts";

const local = () => ["localhost", "127.0.0.1", "[::1]"].includes(location.hostname);

const PERMISSIONS = [
  ["contents: write", "Saves history to the stackvitals-data branch; changes .github/stackvitals.toml when someone with write access asks.", "Nothing is saved."],
  ["actions: read", "Reads your CI runs, their jobs and test reports.", "CI health stays empty."],
  ["actions: write", "Re-runs a job once when only known flakes failed (only with rerun flaky on).", "Known flakes are not re-run."],
  ["checks: read / write", "Sees which pull requests have failing checks; posts the StackVitals verdict check (only when it's on).", "No verdict check."],
  ["statuses, deployments: read", "Reads commit statuses and production deployments for delivery.", "Delivery guesses deployments from workflow names."],
  ["issues: write", "The weekly digest, answers to /stackvitals commands, one issue per flaky test (when on).", "No digest, no answers on GitHub."],
  ["pull-requests: write", "One comment on a pull request whose CI failed, edited in place (when on).", "No comments on pull requests."],
].map(([perm, why, without]) => ({ id: perm!, perm: perm!, why: why!, without: without! }));

const STEPS: [IconName, string, (repo: string) => string][] = [
  ["prs", "GitHub", () => "Your CI runs, pull requests, issues and deployments."],
  ["bolt", "The workflow", () => "Runs in your Actions after every CI run and every 3 hours; reads with the workflow's own token, about a minute."],
  ["lock", "stackvitals-data", (repo) => `A branch in ${repo}: every number with its history, every decision with who, why and until when.`],
  ["overview", "This page", () => (local() ? "Served on your machine by stackvitals ui from a copy of that branch; it keeps working offline."
    : /\.github\.io$/.test(location.hostname) ? "Served by GitHub Pages from that branch. Static files only; nothing runs on a server."
    : "Static files that read that branch from GitHub; nothing runs on a server.")],
];

// Label and value rows: one fact per row, never a sentence with the label buried in it.
const Facts = ({ rows }: { rows: [string, ComponentChildren][] }) =>
  <dl class="ab-facts">{rows.map(([k, v]) => <div><dt>{k}</dt><dd>{v}</dd></div>)}</dl>;
const code = (s: string) => <code class="code-inline">{s}</code>;

const LINKS: [string, string, string][] = [
  ["Quickstart", "quickstart", "Set it up in about five minutes."],
  ["Privacy", "privacy", "What each token can reach and what leaves your repo, file by file."],
  ["Methods", "methods", "How every number is counted, with its ranges."],
  ["Accuracy", "accuracy", "Each rule replayed on public history."],
  ["Limitations", "limitations", "What it can't tell you yet."],
  ["Questions people ask", "faq", "Cost, data, and how it differs from other tools."],
];

export default function About({ app }: PageProps) {
  const repo = app?.repo || "your repo";
  return <Page title="About StackVitals" subtitle="What it is, how it works, what it measures and how far to trust it.">
    <Section title="What it is" description="In two sentences.">
      <Card class="ab-lede">
        <p class="ab-lede-text">StackVitals measures how your team ships: flaky tests, waiting reviews, delivery speed, dependencies and newcomers, each number with its history and sample size.
          It runs as a workflow inside your own repo and keeps everything on a branch there, so there is no StackVitals server and no account.</p>
        <dl class="ab-cells">
          <div><dt>Runs in</dt><dd>Your GitHub Actions</dd></div>
          <div><dt>Keeps data in</dt><dd><code class="code-inline">stackvitals-data</code></dd></div>
          <div><dt>Server</dt><dd>None</dd></div>
          <div><dt>Price</dt><dd>Free, MIT licence</dd></div>
        </dl>
      </Card>
    </Section>

    <Section title="How it works" description="Four steps, in order, all inside your repo.">
      <ol class="pipeline" aria-label="How data moves">{STEPS.map(([icon, name, text], i) => <li class="pipe-node" style={{ animationDelay: `${i * 70}ms` }}>
        <span class="pipe-step">Step {i + 1}</span>
        <span class="pipe-icon"><Icon name={icon} /></span><b>{name}</b><span class="pipe-text">{text(repo)}</span>
        {i < STEPS.length - 1 ? <i class="packet" aria-hidden="true" /> : null}
      </li>)}</ol>
    </Section>

    <Section title="What it measures" description="One module per question. Open a module to see it for this repo.">
      <ModuleTable />
    </Section>

    <Section title="How accurate it is" description="Each rule checked on public data. Pick a rule's name to read every check behind it. A model's labels say so until a person audits them."
      info={<InfoButton info={{ title: "Accuracy", doc: "accuracy.md", body: "Each card replays a rule on public history and reports what it got right, with ranges and the weak spot it still has." }} />}>
      <Accuracy />
    </Section>

    <Columns>
      <Section title="What it costs and needs" description="Free; it uses your own Actions minutes."
        info={<InfoButton info={{ title: "Cost", doc: "faq.md", body: "MIT-licensed, no paid tier, no account and no StackVitals-hosted backend. Optional integrations use services and keys you choose." }} />}>
        <Card><Facts rows={[
          ["Price", "Free. No paid tier, no account."],
          ["Actions minutes", "About a minute per run on a small repo, after each CI run and every 3 hours. Free on public repos; private repos use the plan's minutes."],
          ["Needs", <>A GitHub repo with Actions on, and the workflow file (<a href="#/setup">Setup</a> adds it).</>],
          ["Optional", "GitHub Pages to open this app on a public repo; a token to apply changes from the app; keys for the connectors you add."],
        ]} /></Card>
      </Section>
      <Section title="Privacy in short" description="Your data stays in your repo."
        info={<InfoButton info={{ title: "Privacy", doc: "privacy.md", body: "What each token can reach and what leaves your repo, file by file." }} />}>
        <Card><Facts rows={[
          ["Stored", <>In {repo}'s {code("stackvitals-data")} branch; git history is the audit log.</>],
          ["Your code", "Never sent anywhere."],
          ["Leaves GitHub", <>Package names, for the dependency check (off with {code("[deps] outside_lookups = false")}); the chat webhook you set.</>],
          ["Public pages", <>A GitHub Pages site is public, even for a private repo. View private repos with {code(`stackvitals ui ${app?.repo || "owner/repo"}`)}.</>],
          ["Tokens pasted here", "Kept in this page's memory (or this tab's storage, if you tick keep, until the tab closes); sent only to api.github.com."],
        ]} /></Card>
      </Section>
    </Columns>

    <Section title="How the numbers are counted" description="Sample sizes always, guesses never."
      info={<InfoButton info={{ title: "Methods", doc: "methods.md", body: "Wilson ranges for shares, order-statistic ranges for medians, Kaplan-Meier for waiting times and false-alarm control for weekly changes." }} />}>
      <Card><Facts rows={[
        ["Sample sizes", "Every number carries one; below the minimum it says \"not enough data\" instead of guessing."],
        ["DORA", "Counted the way Apache DevLake's dashboards count it, from your own deployments."],
        ["Peer comparisons", "From a daily crawl of public repos, grouped by language and size."],
        ["People", "No person is ranked or timed on a public page."],
      ]} /></Card>
    </Section>

    <Section title="What each permission is for" description="And what stops working without it.">
      <Table name="permissions" caption="Permissions" search={false} rows={PERMISSIONS} columns={[
        { key: "perm", label: "Permission", primary: true, render: (p) => <span class="mono-soft">{p.perm}</span> },
        { key: "why", label: "Why" }, { key: "without", label: "Without it", render: (p) => <span class="muted">{p.without}</span> }]} />
    </Section>

    <Columns>
      <Section title="Remove StackVitals" description="Three steps; nothing is left behind.">
        <Card><ol class="about-steps">
          <li>Delete <code class="code-inline">.github/workflows/{app?.links?.workflow || "stackvitals.yml"}</code>.</li>
          <li>Delete the <code class="code-inline">stackvitals-data</code> branch.</li>
          <li>Turn GitHub Pages off, or point it elsewhere, in {app ? <a href={`https://github.com/${app.repo}/settings/pages`} target="_blank" rel="noopener noreferrer">Settings, Pages</a> : "Settings, Pages"}.</li>
        </ol>
        {app ? <CodeBlock inline code={`git push origin --delete stackvitals-data`} /> : null}</Card>
      </Section>
      <Section title="Report a security problem" description="Privately, to the maintainers.">
        <Card><p>Use the Security tab of the repository that hosts the StackVitals Action and choose "Report a vulnerability"; it reaches the maintainers privately.</p>
          <div class="about-btn"><Button variant="tinted" href="https://github.com/stackvitals/stackvitals/security/advisories/new" external iconEnd="external">Report a vulnerability</Button></div></Card>
      </Section>
    </Columns>

    <Section title="Read more" description="The guides behind this page, in Help.">
      <Table name="about-links" caption="Read more" search={false} rows={LINKS.map(([title, id, what]) => ({ id, title, what }))} columns={[
        { key: "title", label: "Guide", primary: true, render: (r) => <a class="ab-mod" href={`#/help/${r.id}`}>{r.title}</a> },
        { key: "what", label: "What's in it" }]} />
    </Section>
  </Page>;
}
