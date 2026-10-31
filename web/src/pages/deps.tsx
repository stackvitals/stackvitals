// Dependencies: known vulnerabilities by severity with whether your code reaches them, the update pull requests the bots
// opened and security updates waiting past 48 hours, and the supply chain (licences, drift, Scorecards, runtimes).
import "./deps.css";
import { useState } from "preact/hooks";
import type { PageProps } from "../app/routes";
import { BarChart } from "../charts/BarChart";
import { useFiles } from "../data/files";
import { day, hours, short } from "../data/format";
import type { AppJson, DepsFull, SupplyJson, Vuln, VulnsJson } from "../data/types";
import { Decide } from "../features/Decide";
import { Button } from "../ui/Button";
import { CodeBlock, EmptyState, InfoButton, PageSkeleton, Pill, type PillTone } from "../ui/bits";
import { Icon } from "../ui/icons";
import { Card, Columns, Page, Section, Stat, Stats } from "../ui/Page";
import { Table } from "../ui/Table";
import { Facts, Framed, Panel } from "./deps/blocks";
import { ScoreFacts, SecurityFacts, effortWord } from "./deps/security";
import { CheckPackage, CodeScanning, ScanLockfile, YourCode } from "./deps/tools";

type R = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

const RANK: Record<string, number> = { critical: 0, high: 1, moderate: 2, low: 3, unrated: 4 };
const SEV_TONE: Record<string, PillTone> = { critical: "bad", high: "bad", moderate: "watch" };
const ext = { target: "_blank", rel: "noopener noreferrer" };
const accept = (app: AppJson, pkg: string) => <Decide app={app} kind="package" id={pkg} verbs={["accept"]} label="Accept the risk" />;
const Pkg = ({ name, version }: { name: string; version?: string | undefined }) => <><span class="mono-soft">{short(name, 50)}</span> <span class="muted">{version || ""}</span></>;
const REACH_INFO = { title: "Your code", doc: "modules.md#dependency-steward", body: <>Whether your code reaches the vulnerable part. <b>Calls it</b>: govulncheck found a call path
  (Go). <b>Imports the package</b>: an import, never a call path (Python, JavaScript and Rust). <b>Unknown</b> means no free tool tells it for that language yet, so it
  says unknown rather than guess. Fix what your code calls first.</> };

function Vulns({ app, v, s }: { app: AppJson; v: VulnsJson; s: SupplyJson | null }) {
  const [sev, setSev] = useState<number | null>(null);
  const open = v.open || [];
  // Whether the code calls the vulnerable function: known only where govulncheck ran (Go); elsewhere unknown, never "not called".
  const called = Object.fromEntries((s?.reachability?.findings || []).flatMap((x) => [x.id, ...(x.aliases || [])].map((id) => [id, x.reach])));
  const reachOf = (x: Vuln) => called[x.id] || (x.aliases || []).map((a) => called[a]).find(Boolean)
    || (x.imported === true ? "imports it" : x.imported === false ? "no direct import" : "unknown");
  const keys = ["critical", "high", "moderate", "low", "unrated"];
  const bars = [{ label: "Malware", value: open.filter((x) => x.malware).length, tone: "bad" as const },
    ...keys.map((k) => ({ label: k[0]!.toUpperCase() + k.slice(1), value: open.filter((x) => !x.malware && (RANK[x.severity || ""] ?? 4) === RANK[k]).length, tone: (RANK[k]! <= 1 ? "bad" : RANK[k] === 2 ? "watch" : "neutral") as "bad" }))]
    .filter((b) => b.value || (b.label !== "Malware" && b.label !== "Unrated"));
  const reached = open.filter((x) => ["called", "imports it", "imported"].includes(reachOf(x))).length;
  const pick = sev === null ? null : bars[sev];
  return <>
    <Columns ratio="lead">
      <Card><div class="hero">
        <div class="hero-name"><span>{pick ? `${pick.label}${pick.label === "Malware" ? "" : " severity"}` : "Open vulnerabilities"}</span><InfoButton info={REACH_INFO} /></div>
        <div class="hero-num num">{pick ? pick.value : open.length}</div>
        <div class="hero-meta"><span class="hero-date">{pick ? `of ${open.length} open` : `in ${new Set(open.map((x) => `${x.ecosystem}:${x.package}`)).size} packages, ${(v.closed || []).length} fixed lately`}</span></div>
        <p class="hero-meaning">{!open.length ? "No known vulnerability in this repo's lockfiles." : reached ? `${reached} of them sit in code your project imports or calls. Fix ${reached === 1 ? "that one" : "those"} first.`
          : "None is known to sit in code your project imports or calls."}</p>
        {open.length ? <BarChart label="Open vulnerabilities by severity" bars={bars} height={170} onPick={setSev} /> : null}
      </div></Card>
      <Stats>
        <Stat label="Open" value={open.length} />
        <Stat label="Malware" value={open.filter((x) => x.malware).length} />
        <Stat label="Critical or high" value={open.filter((x) => (RANK[x.severity || ""] ?? 4) <= 1).length} />
        <Stat label="With a fix" value={open.filter((x) => x.fixed).length} />
        <Stat label="Fixed lately" value={(v.closed || []).length} />
      </Stats>
    </Columns>
    <Framed title="Open vulnerabilities" note="Most severe first; filter by ecosystem, severity or your code.">
    <Table name="vulnerabilities" caption="Known vulnerabilities" rows={open} initialSort={{ key: "severity", desc: false }} columns={[
      { key: "package", label: "Package", primary: true, nowrap: true, render: (x) => <><span class="mono-soft">{short(x.package, 50)}</span>{x.dev ? <div class="muted small">development only</div> : null}</> },
      { key: "version", label: "Version", nowrap: true, render: (x) => x.version || "–" },
      { key: "ecosystem", label: "Ecosystem", filter: true },
      { key: "id", label: "Advisory", nowrap: true, render: (x) => <><a href={`https://osv.dev/vulnerability/${encodeURIComponent(x.id)}`} {...ext}>{x.id}</a>{x.ignored ? <> <span title={`${x.ignored.reason || "no reason given"}${x.ignored.until ? `, until ${x.ignored.until}` : ""}`}><Pill tone="neutral">ignored</Pill></span></> : null}</> },
      { key: "severity", label: "Severity", filter: true, raw: (x) => (x.malware ? -1 : RANK[x.severity || ""] ?? 4),
        render: (x) => (x.malware ? <Pill tone="bad">malware</Pill> : <Pill tone={SEV_TONE[x.severity || ""] || "neutral"} icon={null}>{x.severity || "unrated"}</Pill>) },
      { key: "fixed", label: "Fixed in", nowrap: true, render: (x) => x.fixed ? <span title={x.fix_plan?.command}>{x.fixed}{x.fix_plan ? <span class="muted small"> ({x.fix_plan.bump} jump)</span> : null}</span> : <span class="muted">no fix yet</span> },
      { key: "reach", label: "Your code", filter: true, raw: reachOf, render: (x) => { const r = x.reach?.level || reachOf(x), path = x.reach?.path?.join(" > ");
        return r === "called" ? <b title={path}>calls it</b> : r === "imported" || r === "imports it" ? <span title={path}>imports the package</span> : r === "required" ? "only requires it"
          : r === "no direct import" ? <span class="muted" title="It may still run through another package">no direct import</span> : <span class="muted">unknown</span>; } },
      { key: "file", label: "Lockfile", nowrap: true, render: (x) => <span class="mono-soft small">{short(x.file, 40)}</span> },
      { key: "first_seen", label: "Open since", nowrap: true, render: (x) => day(x.first_seen) },
      { key: "accept", label: "Decide", raw: () => "", render: (x) => accept(app, x.package) }]}
      empty={<Card><EmptyState icon="check" title="No known vulnerability in this repo's lockfiles." /></Card>} />
    <p class="blk-note">Your code comes from govulncheck (Go) or the imports list (Python, JavaScript, Rust) run in your workflow; without them it says unknown rather than guess.</p>
    </Framed>
    <Framed title="Where this comes from">
      <Facts rows={[["Scanner", v.scanner || "–"], ["Lockfiles read", <span class="num">{(v.files || []).length}</span>], ["Branch", <span class="mono-soft">{v.ref || "–"}</span>],
        ["Scanned", day(v.generated)], ["Advisories", v.offline ? "OSV's downloaded databases (no package names sent)" : "OSV"],
        v.skipped?.length ? ["Too large to scan", <span class="mono-soft">{v.skipped.join(", ")}</span>] : null]} />
    </Framed>
  </>;
}

// The three most used licences, for the note under the count.
const top = (l: R) => Object.entries(l.by_licence || {}).slice(0, 3).map(([k, n]) => `${k} ${n}`).join(", ") || null;

function Supply({ app, s }: { app: AppJson; s: SupplyJson }) {
  const l = s.licences || {}, sc = s.scorecards || {}, deny = s.policy?.deny || [];
  const cards = [...(sc.drops || []).map((x) => ({ ...x, kind: "dropped", now: x.after })), ...(sc.low || []).map((x) => ({ ...x, kind: "low", now: x.score })),
    ...(sc.below_policy || []).map((x) => ({ ...x, kind: "policy", now: x.score }))] as { project: string; kind: string; now?: number; before?: number; since?: string; packages: string[] }[];
  const r = s.reachability;
  return <>
    <Facts class="is-figures dp-supply-facts" rows={[
      ["Packages", <>{s.packages ?? "–"}<small>{Object.entries(s.systems || {}).map(([k, n]) => `${k.toLowerCase()} ${n}`).join(", ") || "–"}</small></>],
      ["Against the licence rule", <>{deny.length ? (l.denied || []).length : "–"}<small>{deny.length ? `${(l.accepted || []).length} accepted by a decision` : <a href="#/settings?module=deps">Set a rule</a>}</small></>],
      ["No known licence", <>{l.unknown ?? "–"}<small>packages</small></>],
      ["Licences in use", <>{Object.keys((l as R).by_licence || {}).length || "–"}<small>{top(l as R) || "–"}</small></>],
      ["Scorecard drops", <>{(sc.drops || []).length}<small>{sc.checked ?? 0} of {sc.projects ?? 0} projects scored</small></>],
    ]} />
    <Framed title="Where this comes from">
      <Facts rows={[["Package list", "GitHub's SBOM of the default branch"], ["Read on", day(s.generated)],
        ["Licences and Scorecards", s.outside_lookups === false ? "Outside lookups off (docs/privacy.md): none" : "deps.dev and OpenSSF Scorecard"],
        ["Licence rule", deny.length ? <span class="mono-soft">{deny.join(", ")}</span> : <a href="#/settings?module=deps">None set</a>],
        s.policy?.min_scorecard != null ? ["Minimum Scorecard", <span class="num">{s.policy.min_scorecard}</span>] : null]} />
    </Framed>
    {(l.denied || []).length ? <Framed title="Against the licence rule" note="Accept one to keep it, with the reason in the log."><Table name="licence-denied" caption="Licences against the rule" rows={l.denied!} columns={[
      { key: "name", label: "Package", primary: true, nowrap: true, render: (p) => <Pkg name={p.name} version={p.version} /> },
      { key: "licence", label: "Licence" }, { key: "system", label: "Ecosystem", filter: true },
      { key: "accept", label: "Decide", raw: () => "", render: (p) => accept(app, p.name) }]} /></Framed> : null}
    {Object.keys((l as R).by_licence || {}).length ? <Framed title="Licences in use" note="Packages by licence, the twelve most used."><Card><BarChart label="Packages by licence" kind="count" height={180}
      bars={Object.entries((l as R).by_licence as Record<string, number>).slice(0, 12).map(([k, n]) => ({ label: k, value: n, tone: deny.includes(k) ? "bad" as const : "accent" as const }))} /></Card></Framed> : null}
    {(s.drift || []).length ? <Framed title="Licences that changed" note="Between quarters, from deps.dev."><Table name="licence-drift" caption="Licence changes" rows={s.drift!} columns={[
      { key: "name", label: "Package", primary: true, render: (x) => <span class="mono-soft">{x.name}</span> },
      { key: "from", label: "Was", render: (x) => x.from }, { key: "from_quarter", label: "Until" },
      { key: "to", label: "Now", render: (x) => x.to }, { key: "to_quarter", label: "Since" }]} /></Framed> : null}
    {cards.length ? <Framed title="Scorecards to look at" note="OpenSSF Scorecard of the projects behind your packages.">
      <Table name="scorecards" caption="Scorecards" rows={cards} columns={[
        { key: "project", label: "Project", primary: true, render: (x) => <a href={`https://${x.project}`} {...ext}>{x.project.replace("github.com/", "")}</a> },
        { key: "kind", label: "Why", filter: true, raw: (x) => x.kind, render: (x) => (x.kind === "dropped" ? `fell from ${x.before} since ${day(x.since)}` : x.kind === "policy" ? `under this repo's minimum (${s.policy?.min_scorecard})` : "under 4") },
        { key: "now", label: "Scorecard", num: true }, { key: "packages", label: "Used as", raw: (x) => x.packages.join(" "), render: (x) => <span class="mono-soft">{short(x.packages.join(", "), 60)}</span> }]} />
      <p class="blk-note">Scorecard is one input shown here; it never decides a package's verdict, which rests on upgrade outcomes, maintainers and advisories.</p></Framed> : null}
    {(s.runtimes || []).length ? <Framed title="Runtimes" note="Support dates from endoflife.date."><Table name="runtimes" caption="Runtimes" search={false} rows={s.runtimes!} columns={[
      { key: "runtime", label: "Runtime", primary: true, nowrap: true, render: (x) => <span class="mono-soft">{x.runtime} {x.version}</span> },
      { key: "use", label: "Use", filter: true, raw: (x) => (x.use === "tests" ? "tested on" : "runs on") },
      { key: "status", label: "Status", filter: true, render: (x) => (x.status === "end of life" ? <Pill tone={x.use === "tests" ? "neutral" : "bad"}>out of support since {x.eol || "?"}</Pill>
        : x.status === "behind the newest patch" ? <Pill tone="watch">behind the newest patch</Pill> : x.status === "unknown" ? <Pill tone="neutral">not listed</Pill> : <Pill tone="good">{`supported${x.eol ? ` until ${x.eol}` : ""}`}</Pill>) },
      { key: "latest", label: "Newest release", nowrap: true, render: (x) => (x.latest ? <>{x.latest}{(x as R).latest_date ? <span class="muted"> ({day((x as R).latest_date)})</span> : null}</> : "–") },
      { key: "file", label: "Named in", nowrap: true, render: (x) => <span class="mono-soft small">{short(x.file, 50)}</span> }]} />
      <p class="blk-note">Lockfile scans don't see runtime flaws, and a line out of support gets no security fixes. Old lines in a test matrix are often kept on purpose, so only what the project runs on is marked red.</p></Framed> : null}
    {r?.error ? <p class="note note-watch small">The govulncheck file couldn't be read: {r.error}</p> : null}
    {(r?.findings || []).length ? <Framed title="Reachability" note={`From ${r!.scanner || "govulncheck"} in this repo's workflow: ${r!.counts?.called ?? 0} called, ${r!.counts?.imported ?? 0} imported only, ${r!.counts?.required ?? 0} required only.`}>
      <Table name="reachability" caption="Reachability" rows={r!.findings!} columns={[
        { key: "id", label: "Advisory", primary: true, nowrap: true, render: (x) => <a href={`https://pkg.go.dev/vuln/${x.id}`} {...ext}>{x.id}</a> },
        { key: "reach", label: "Your code", filter: true, render: (x) => (x.reach === "called" ? <b>calls it</b> : x.reach === "imported" ? "imports the package" : "only requires the module") },
        { key: "module", label: "Module", nowrap: true, render: (x) => <Pkg name={x.module || ""} version={x.version} /> },
        { key: "fixed", label: "Fixed in", render: (x) => x.fixed || "no fix yet" },
        { key: "path", label: "How", raw: (x) => (x.path || []).join(" "), render: (x) => <span class="mono-soft small">{short((x.path || []).join(" → "), 60)}</span> }]} /></Framed> : null}
  </>;
}

const PROBE_TONE = (r: R): PillTone => (r.result === "pass" ? "good" : r.result === "fail" ? (r.risk === "critical" || r.risk === "high" ? "bad" : "watch") : "neutral");

export default function Deps({ app }: PageProps) {
  const f = useFiles<{ deps: DepsFull; supply: SupplyJson; vulns: VulnsJson; security: R }>({ deps: "deps.json", supply: "supply.json", vulns: "vulns.json", security: "security.json" });
  if (!f.ready) return <PageSkeleton />;
  const d = f.deps, s = f.supply, v = f.vulns, sec = f.security;
  const tools = (a: AppJson) => <Section title="Before a package lands" description="Check one package here, scan a lockfile from your machine, and let your workflow say whether your code reaches each vulnerability.">
    <CheckPackage app={a} f={{ deps: d, supply: s, vulns: v }} />
    <div class="dp-gap"><Columns><ScanLockfile v={v} /><YourCode app={a} v={v} s={s} /></Columns></div>
  </Section>;
  if (!app || (!d && !s && !v && !sec)) return <Page title="Dependencies" subtitle="Update pull requests, security updates and supply-chain checks.">
    <EmptyState icon="deps" title="No update bot has opened a pull request here.">Dependabot or Renovate updates appear here once they do; a pull request that changes a lockfile also gets the dependency check.</EmptyState>
    {app ? tools(app) : null}</Page>;
  const open = d?.open || [];
  const gh = (pr: number) => `https://github.com/${app.repo}/pull/${pr}`;
  return <Page title="Dependencies" subtitle={d ? `Update pull requests from ${(d.bots || []).join(" and ") || "the update bots"}, from the history StackVitals keeps.` : "Known vulnerabilities and the supply chain of this repo's dependencies."}>
    {(d?.quiet_days ?? 0) >= 30 ? <div class="note note-watch"><Icon name="clock" /><span>No update pull request for {d!.quiet_days} days. Dependabot pauses itself after 90 days without
      interaction; check its settings if this repo still has dependencies to update.</span></div> : null}

    {sec ? <Section title="This repo's own security" description="OpenSSF Scorecard's checks, run by your workflow on this repo (private repos too), each with what to do."
      action={<Pill tone={sec.score == null ? "neutral" : sec.score >= 7 ? "good" : sec.score >= 4 ? "watch" : "bad"}>{sec.score == null ? "not scored" : `${sec.score} of 10`}</Pill>}>
      {sec.weakened ? <div class="note note-watch"><Icon name="warn" /><span>Branch protection is weaker than last week.</span></div> : null}
      <ScoreFacts sec={sec} />
      <Framed title="Checks" note="Failing first; each with the risk, the effort and what to do.">
        <Table name="security-probes" caption="Security checks" rows={sec.probes || []} initialSort={{ key: "result", desc: false }} columns={[
          { key: "probe", label: "Check", primary: true, raw: (r: R) => r.why, render: (r: R) => <><span>{r.why}</span><div class="muted small mono-soft">{r.probe}</div></> },
          { key: "result", label: "Result", filter: true, render: (r: R) => <Pill tone={PROBE_TONE(r)}>{r.result === "unknown" ? "can't read" : r.result}</Pill> },
          { key: "risk", label: "Risk", filter: true },
          { key: "effort", label: "Effort to fix", filter: true, raw: (r: R) => effortWord(r.effort) },
          { key: "fix", label: "What to do", render: (r: R) => r.result === "fail" ? <><span>{r.fix}</span>{(r.findings || []).slice(0, 3).map((x: R) => <div class="muted small mono-soft">{x.path}{x.job ? ` (${x.job})` : ""}: {short(x.detail, 80)}</div>)}</>
            : (r.guarded || []).length ? <span class="muted small">guarded: {r.guarded[0].guarded}</span> : <span class="muted">–</span> }]}
          empty={<Card><EmptyState icon="clock" title="Not checked yet.">The weekly security step fills this in on its next run.</EmptyState></Card>} />
      </Framed>
      {sec.facts ? <SecurityFacts f={sec.facts} repo={app.repo} /> : null}
    </Section> : <Section title="This repo's own security" description="OpenSSF Scorecard's checks, run by your workflow on this repo (private repos too).">
      <Card><EmptyState icon="clock" title="Not checked yet.">The security step runs once a week; this fills in after its first run with this version.</EmptyState></Card></Section>}

    {v ? <Section title="Known vulnerabilities" description="In every lockfile, every ecosystem. Tap a bar to read one severity; fix what your code reaches first.">
      <Vulns app={app} v={v} s={s} /></Section> : <Section title="Known vulnerabilities" description="In every lockfile, every ecosystem.">
      <Card><EmptyState icon="clock" title="No scan yet.">The vulnerability scan runs with the dependency check; this fills in after its next run. Turn it on under <a href="#/settings?module=deps">Settings</a> if it's off.</EmptyState></Card></Section>}

    {d ? <Section title="Update pull requests" description="What the bots opened, oldest first. A security update open past 48 hours is overdue."
      action={<Pill tone={d.security_overdue?.length ? "bad" : "good"}>{d.security_overdue?.length ? `${d.security_overdue.length} overdue` : "None overdue"}</Pill>}>
      <Stats>
        <Stat label="Open updates" value={open.length} />
        <Stat label="Security updates past 48 h" value={(d.security_overdue || []).length} />
        <Stat label="Merged, last 90 days" value={d.merged_90d ?? "–"} />
        <Stat label="Time to merge, median" value={hours(d.merge_median_hours)} />
        <Stat label="Last one opened" value={d.last_opened ? day(d.last_opened) : "–"} note={d.quiet_days !== undefined ? `${d.quiet_days} days ago` : null} />
      </Stats>
      <Framed title="Open update pull requests" note="Longest open first.">
        <Table name="dependency-updates" caption="Open update pull requests" rows={open} initialSort={{ key: "age_hours", desc: true }} columns={[
          { key: "pr", label: "PR", primary: true, nowrap: true, render: (u) => <a href={gh(u.pr)} {...ext}>#{u.pr}</a> },
          { key: "package", label: "Package", nowrap: true, render: (u) => <span class="mono-soft">{short(u.package || "–", 50)}</span> },
          { key: "security", label: "Kind", filter: true, raw: (u) => (u.security ? "security" : "update"), render: (u) => (u.security ? <Pill tone="bad">security</Pill> : <Pill tone="neutral">update</Pill>) },
          { key: "from", label: "From", nowrap: true, raw: (u) => u.from || "", render: (u) => u.from || <span class="muted">–</span> },
          { key: "to", label: "To", nowrap: true, raw: (u) => u.to || "", render: (u) => u.to || <span class="muted">not in the title</span> },
          { key: "bump", label: "Change", filter: true, raw: (u) => u.bump || "", render: (u) => u.bump || <span class="muted">–</span> },
          { key: "ecosystem", label: "Ecosystem", filter: true },
          { key: "age_hours", label: "Open for", num: true, render: (u) => hours(u.age_hours) },
          { key: "decision", label: "Decision", raw: (u) => u.decision?.verb || "", render: (u) => (u.decision
            ? <span class="muted">accepted until {u.decision.until}{u.decision.reason ? `: ${u.decision.reason}` : ""}</span>
            : u.package ? accept(app, u.package) : null) }]}
          empty={<Card><EmptyState icon="check" title="No update is waiting." /></Card>} />
      </Framed>
      <Panel title="Accept a known risk" state={<Pill tone="neutral" icon={null}>as a comment</Pill>}>
        <p>Takes a security update off the overdue list until the date, with the reason kept in the log. Accept the risk on a row does the same in one click; this is the comment form.</p>
        <CodeBlock inline code="/stackvitals accept package:<name> for 30d because <reason>" note="Paste on any issue or pull request in this repo." />
      </Panel>
    </Section> : null}

    {s ? <Section title="Supply chain" description="Licences, licence changes, Scorecard drops, runtimes out of support and reachability."
      info={<InfoButton info={{ title: "Supply chain", doc: "modules.md#dependency-steward", body: "Read from GitHub's SBOM of the default branch, with licences from deps.dev and OpenSSF Scorecards. Outside lookups can be turned off in the settings." }} />}>
      <Supply app={app} s={s} /></Section> : <Section title="Supply chain" description="Licences, licence changes, Scorecard drops, runtimes out of support and reachability.">
      <Card><EmptyState icon="clock" title="Not read yet." action={<Button size="sm" variant="tinted" href="#/settings?module=deps">Settings</Button>}>The supply chain shows once the dependency check reads GitHub's SBOM.</EmptyState></Card></Section>}

    <Section title="GitHub's Security tab" description="The vulnerabilities and security checks as code scanning alerts, added as one new workflow file.">
      <CodeScanning app={app} sast={sec?.facts?.workflows?.sast} /></Section>

    {tools(app)}
  </Page>;
}
