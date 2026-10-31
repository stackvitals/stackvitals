// Community: newcomers waiting for a first answer, how fast maintainers answer, quarter by quarter, who carries the
// merged work (bus factor, no names), whether newcomers stay, and stars and traffic over time.
import "./community.css";
import { useState } from "preact/hooks";
import type { PageProps } from "../app/routes";
import { BarChart } from "../charts/BarChart";
import { MetricHero, Watchlist, metricItem, trendTones, useRange } from "../charts/MetricHero";
import { points, type Metric } from "../charts/metric";
import { useFiles } from "../data/files";
import { count, day, hours, pct } from "../data/format";
import type { AppJson, CiChange, CommunityFull, Km, Num, Peer } from "../data/types";
import { Button } from "../ui/Button";
import { ChangePill, EmptyState, InfoButton, PageSkeleton, Pill } from "../ui/bits";
import { Card, Columns, Page, Section } from "../ui/Page";
import { Table } from "../ui/Table";
import { Facts, Framed, Panel } from "./deps/blocks";
import { MachineReport } from "./community/report";

type R = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
const no = (x: unknown): x is null | undefined => x === null || x === undefined;
// A median that counts items still waiting: "over N" when more than half have no answer yet.
const kmValue = (km?: Km | null) => (!km ? "–" : !no(km.median) ? hours(km.median) : km.at_least ? `over ${hours(km.at_least)}` : "–");
const kmRange = (km?: Km | null) => (!km || no(km.low) ? "–" : `${hours(km.low)} ${no(km.high) ? "or more" : `to ${hours(km.high)}`}`);
const KM_DOC = "methods.md#waiting-times-kaplan-meier";
const fig = (v: unknown, note?: unknown) => <>{v as string}{note ? <small>{note as string}</small> : null}</>;

// The change from the quarter before, in words: "up 3", "down 2.0h", "same".
function change(now: Num, before: Num, f: (v: number) => string): string {
  if (no(now) || no(before)) return "no quarter before to compare";
  const d = now - before;
  return d === 0 ? "same as the quarter before" : `${d > 0 ? "up" : "down"} ${f(Math.abs(d))} on the quarter before`;
}

// This week against the four before, as a table: what moved beyond noise and what held.
function ThisWeek({ changes }: { changes?: CiChange[] }) {
  if (!changes) return null;
  const run = changes.filter((c) => !c.note && !c.shown_with);
  const fmt = (c: CiChange, v: Num, base?: boolean) => (no(v) ? "–" : c.unit === "share" ? pct(v) : c.unit === "count" ? `${v}${base ? " a week" : ""}` : `${(+v).toFixed(1)} ${c.unit}`);
  const size = (c: CiChange) => (!c.detectable ? "–" : c.unit === "share" ? `${Math.round(c.detectable * 100)} points` : `${c.detectable >= 3 ? Math.round(c.detectable) : c.detectable.toFixed(1)}×`);
  const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
  return <Framed title="This week against the four before" note="As the weekly digest reads it.">
    <Table name="community-week" caption="This week against the four weeks before" search={false} rows={run.map((c, i) => ({ id: c.metric || String(i), c }))} columns={[
      { key: "label", label: "Measure", primary: true, raw: (r) => r.c.label, render: (r) => cap(r.c.label) },
      { key: "now", label: "This week", num: true, raw: (r) => r.c.now, render: (r) => fmt(r.c, r.c.now) },
      { key: "base", label: "Four weeks before", num: true, raw: (r) => r.c.base, render: (r) => fmt(r.c, r.c.base, true) },
      { key: "moved", label: "Moved", raw: (r) => (r.c.changed ? r.c.direction || "moved" : "steady"),
        render: (r) => (r.c.changed ? <Pill tone="watch" icon={null}>{r.c.direction === "up" ? "Rose" : "Fell"}</Pill> : <Pill tone="neutral" icon={null}>Steady within noise</Pill>) },
      { key: "detectable", label: "Smallest change it would catch", raw: (r) => r.c.detectable ?? null, render: (r) => size(r.c) }]}
      empty={<Card><EmptyState icon="clock" title="Too few this week to compare.">This week is set against the four weeks before once there are enough items.</EmptyState></Card>} />
  </Framed>;
}

// The headline: last quarter's median first answer, its change, one plain line, then the quarters as bars.
function Answers({ c }: { c: CommunityFull }) {
  const q = (c.quarters || []).filter((x) => !no(x.median_hours));
  const last = q[q.length - 1], prev = q[q.length - 2];
  const now = c.facts?.first_answer_hours ?? last?.median_hours;
  return <div class="hero">
    <div class="hero-name"><span>First answer, median</span><InfoButton info={{ title: "First answer", doc: "modules.md#community",
      body: "Hours from an outside issue or pull request to its first reply from someone other than the author, over the last 90 days." }} /></div>
    <div class="hero-num num">{hours(now)}</div>
    <div class="hero-meta">{last && prev ? <><ChangePill kind="hours" from={prev.median_hours!} to={last.median_hours!} better="down" />
      <span class="hero-date">{last.quarter} against {prev.quarter}</span></> : <span class="hero-date">last 90 days</span>}</div>
    {q.length > 1 ? <BarChart label="Median first answer by quarter" kind="hours" height={180}
      bars={q.map((x, i) => ({ label: x.quarter, value: x.median_hours!, tone: i === q.length - 1 ? "accent" : "neutral" }))} /> : null}
  </div>;
}

// Time to the project's answer in each place people ask, one row per channel.
function Channels({ c }: { c: CommunityFull & R }) {
  const iss = c.answers?.issues, disc = c.answers?.discussions;
  const rows = [
    iss ? { id: "issues", channel: "Outside issues", km: iss.km as Km, items: (iss as R).items ?? null, extra: iss.responders ? `${iss.responders} regular responders count as the project` : "" } : null,
    disc ? { id: "discussions", channel: "Discussions", km: disc.km as Km, items: null, extra: no(disc.answer_chosen) ? "" : `${pct(disc.answer_chosen)} of questions have an accepted answer` } : null,
    c.forum ? { id: "forum", channel: "Forum", km: c.forum.km as Km, items: c.forum.topics, extra: `anyone answered ${pct(c.forum.anyone_answered)}, solved ${pct(c.forum.solved_share)} (${c.forum.days} days)` } : null,
    c.chat ? { id: "chat", channel: "Chat", km: c.chat.km as Km, items: c.chat.topics, extra: `anyone answered ${pct(c.chat.anyone_answered)} (${c.chat.days} days)` } : null,
  ].filter(Boolean) as { id: string; channel: string; km?: Km; items: number | null; extra: string }[];
  const left = (c.answers as R | null)?.left_out;
  return <Framed title="The project's answer, by channel" note="Median with items still waiting counted (Kaplan-Meier)."
    action={<InfoButton info={{ title: "Project's answer", doc: KM_DOC, body: "Median time to the first reply from a maintainer or a regular responder (10+ others' issues answered or 2+ others' PRs first-reviewed this year), with items still waiting counted." }} />}>
    <Table name="answer-channels" caption="The project's answer by channel" search={false} rows={rows} columns={[
      { key: "channel", label: "Channel", primary: true },
      { key: "median", label: "Median answer", num: true, raw: (r) => r.km?.median ?? r.km?.at_least ?? null, render: (r) => (r.km?.too_few ? <span class="muted">too few</span> : kmValue(r.km)) },
      { key: "range", label: "Likely range", raw: (r) => r.km?.low ?? null, render: (r) => kmRange(r.km) },
      { key: "answered", label: "Answered", num: true, raw: (r) => r.km?.answered ?? null },
      { key: "waiting", label: "Still waiting", num: true, raw: (r) => r.km?.waiting ?? null },
      { key: "closed", label: "Closed unanswered", num: true, raw: (r) => r.km?.closed_unanswered ?? 0 },
      { key: "extra", label: "Also", raw: (r) => r.extra, render: (r) => r.extra || <span class="muted">–</span> }]}
      empty={<Card><EmptyState icon="clock" title="No outside items yet.">The project's answer shows once outside issues arrive.</EmptyState></Card>} />
    <p class="blk-note">{rows.some((r) => r.km?.too_few) ? "Too few means under 10 answered, too few to say. " : ""}{left ? `${count(left.items, "item")} from ${count(left.accounts, "account")} that opened many on one day (automated) are left out.` : "A median needs 10 answered items."}</p>
  </Framed>;
}

// What the project says about itself, beside what it does.
function Stated({ c }: { c: CommunityFull }) {
  const x = c.context!, km = c.answers?.issues?.km;
  const said = x.response_policy, m = km?.median;
  const kept = said && !no(m) ? m <= said.hours : null;
  const has = (v: unknown, word?: string) => (v ? <Pill tone="good" icon={null}>{word || "yes"}</Pill> : <Pill tone="neutral" icon={null}>no</Pill>);
  const files = [
    { id: "contributing", what: "Contributing guide", has: has(x.contributing), detail: said ? `promises an answer ${said.said}` : "no response time promised" },
    { id: "governance", what: "Governance file", has: has(x.governance), detail: "how decisions are made" },
    { id: "security", what: "Security policy", has: has(x.security_policy), detail: "how to report a vulnerability" },
    { id: "coc", what: "Code of conduct", has: has(x.code_of_conduct), detail: x.code_of_conduct || "–" },
    { id: "funding", what: "Funding links", has: has(x.funding?.length), detail: x.funding?.length ? x.funding.join(", ").toLowerCase().replace(/_/g, " ") : "–" },
    { id: "discussions", what: "Discussions", has: has(x.discussions, "on"), detail: "GitHub Discussions" },
    { id: "maintainers", what: "Listed maintainers", has: x.maintainers_listed ? <span class="num">{x.maintainers_listed}</span> : has(false), detail: "named in the repo" },
    { id: "owners", what: "Code owners", has: x.code_owners ? <span class="num">{x.code_owners}</span> : has(false), detail: "in CODEOWNERS" },
  ];
  return <>
    <Columns>
      <Panel title="The promise" class={kept === null ? "" : kept ? "is-good" : "is-bad"}
        state={kept === null ? <Pill tone="neutral" icon={null}>{said ? "can't tell yet" : "none made"}</Pill> : <Pill tone={kept ? "good" : "bad"}>{kept ? "Kept" : "Not kept"}</Pill>}>
        <Facts rows={[["Promised answer", said ? said.said : "No promise in the contributing guide"], ["Median first answer", kmValue(km)],
          ["Likely range", kmRange(km)], ["Where it's read", x.contributing ? "The contributing guide" : "No contributing guide"]]} />
      </Panel>
      <Panel title="In the project's words" bar={<Button size="sm" variant="tinted" href="#/settings?module=community">{x.stated ? "Change what it says" : "Say who maintains it and how it works"}</Button>}>
        <Facts rows={[["Who maintains it", x.stated?.capacity || <span class="muted">Not said yet</span>], ["How it works", x.stated?.norms || <span class="muted">Not said yet</span>]]} />
      </Panel>
    </Columns>
    <Framed title="Files and channels" note="What the repo has, read on each run.">
      <Table name="community-files" caption="Community files and channels" search={false} rows={files} columns={[
        { key: "what", label: "Item", primary: true }, { key: "has", label: "Has it", raw: () => "", render: (r) => r.has }, { key: "detail", label: "Detail" }]} />
    </Framed>
  </>;
}

function People({ c }: { c: CommunityFull }) {
  const d = c.dependency, t = c.tenure, o = c.orgs;
  const peer = (x: Peer | undefined, f: (v: number) => string) => (x ? [f(x.typical), `${f(x.low)} to ${f(x.high)}`] : ["–", "no public benchmark yet"]);
  const work = d ? [
    { id: "bus", what: "Bus factor", you: String(d.bus_factor), peers: peer(d.peers?.bus_factor, String), means: "the fewest people behind half the merged pull requests" },
    { id: "top", what: "Most active person's share", you: pct(d.top_share), peers: peer(d.peers?.top_share, (v) => pct(v)), means: "of the merged pull requests" },
    { id: "people", what: "People merging work", you: String(d.people), peers: ["–", "–"], means: `${d.merged} merged pull requests` },
  ] : [];
  const groups = [["Newcomers", "first contributions", t?.newcomers], ["Regulars", "from people who came before", t?.regulars]] as const;
  return <>
    {d ? <Framed title="Who carries the merged work" note={`Last ${d.days || 180} days, no names; low means the work rests on few people.`}
      action={<InfoButton info={{ title: "Bus factor", doc: "chaoss.md", body: "The fewest people behind half of the merged pull requests. Low means the work rests on few people." }} />}>
      <Table name="carries-work" caption="Who carries the merged work" search={false} rows={work} columns={[
        { key: "what", label: "Measure", primary: true }, { key: "you", label: "This repo", num: true },
        { key: "typical", label: "Similar repos, typical", num: true, raw: (r) => r.peers[0] }, { key: "range", label: "Middle half", raw: (r) => r.peers[1] },
        { key: "means", label: "What it counts" }]} />
    </Framed> : <Card><EmptyState icon="community" title="Not enough merged work yet.">Who carries the work shows once people have merged 20 pull requests in 180 days.</EmptyState></Card>}
    <Framed title="First answers, newcomers against regulars" note={`Last ${t?.days || 90} days.`}>
      <Table name="tenure" caption="First answers by tenure" search={false} rows={groups.map(([g, what, x]) => ({ id: g, g, what, x }))} columns={[
        { key: "g", label: "Who asked", primary: true },
        { key: "n", label: "Items", num: true, raw: (r) => r.x?.n ?? null, render: (r) => r.x?.n ?? "–" },
        { key: "median", label: "Median first answer", num: true, raw: (r) => r.x?.median_h ?? null, render: (r) => hours(r.x?.median_h) },
        { key: "day", label: "Within a day", num: true, raw: (r) => r.x?.answered_1d_share ?? null, render: (r) => pct(r.x?.answered_1d_share) },
        { key: "what", label: "Counts" }]} />
    </Framed>
    {o ? <Framed title="Organisations behind the work" note="From public profiles; unknown is counted, never guessed.">
      <Facts class="is-figures" rows={[
        ["Elephant factor", fig(o.factor ?? "–", o.factor ? "fewest organisations behind half the work with a known one" : "can't tell: most work has no known organisation")],
        ["No known organisation", fig(pct(o.unknown_share), `${o.people} people, ${o.merged} merged pull requests`)]]} />
      {o.orgs.length ? <Table name="orgs" caption="Organisations" search={false} rows={o.orgs} columns={[{ key: "org", label: "Organisation", primary: true },
        { key: "prs", label: "Merged PRs", num: true }, { key: "share", label: "Share", num: true, render: (r) => pct(r.share) }]} /> : null}
    </Framed> : null}
  </>;
}

const FACT_NAME: Record<string, string> = { first_answer_hours: "First answer to outside PRs", newcomer_answered_share: "Newcomers answered within 2 weeks",
  newcomer_return_rate: "Newcomers who come back within 90 days" };
const factValue = (kind: string, v: Num) => (kind === "hours" ? hours(v) : pct(v));

// The score's parts against similar public repos, and the crawl's newcomer table: who came back, by how long they waited.
function Bench({ c }: { c: CommunityFull & R }) {
  const sc = c.score as R | null, lever = c.lever as R | null;
  if (!sc?.facts && !lever) return <Card><EmptyState icon="community" title="No public benchmark yet.">
    {c.has_bench ? "Too few of this repo's facts have a comparison yet; two are needed for a score." : "The score compares this repo with similar public repos once the public benchmark file is published."}</EmptyState></Card>;
  const by: R[] = lever?.by_answer || [];
  const outcomes: R[] = lever?.by_outcome || [];
  return <>
    {sc?.facts ? <Framed title="How the score is made" note={`Against ${sc.repos} public repos (${sc.group}).`}>
      <Facts class="is-figures" rows={[["Score", fig(`${sc.score}/100`, "the average of Better than")], ["Compared with", fig(sc.repos, sc.group)],
        (sc.left_out || []).length ? ["Left out for too little data", <span class="cm-left">{(sc.left_out as string[]).map((k) => FACT_NAME[k] || k).join(", ")}<small>a missing fact is never scored as zero</small></span>] : null]} />
      <Table name="community-score" caption="How the score is made" search={false} rows={sc.facts} columns={[
        { key: "name", label: "Fact", primary: true }, { key: "you", label: "This repo", num: true, render: (f: R) => factValue(f.kind, f.you) },
        { key: "typical", label: "Typical", num: true, render: (f: R) => factValue(f.kind, f.typical) },
        { key: "better_than", label: "Better than", num: true, render: (f: R) => `${f.better_than}%` }]} />
    </Framed> : <Card><EmptyState icon="clock" title="No score yet.">Two facts with a public comparison are needed.</EmptyState></Card>}
    {by.length ? <Columns ratio="lead">
      <Panel title="Newcomers who came back, by their first wait">
        <p class="blk-how">Share back within 90 days, by how long their first pull request waited: {Number(lever!.newcomers).toLocaleString("en-US")} newcomers in {Number(lever!.repos).toLocaleString("en-US")} public repos.</p>
        <BarChart label="Share of newcomers who came back within 90 days, by first answer" kind="share" height={180}
          bars={by.map((b) => ({ label: b.bucket, value: b.returned, tone: b.bucket.includes("no answer") || b.bucket.includes("never") ? "bad" as const : "accent" as const }))} />
      </Panel>
      {outcomes.length ? <Framed title="By what happened to the first pull request">
        <Table name="newcomer-outcomes" caption="Newcomers who came back by outcome" search={false} rows={outcomes.map((x) => ({ ...x, id: x.outcome }) as R)} columns={[
          { key: "outcome", label: "Outcome", primary: true }, { key: "newcomers", label: "Newcomers", num: true, render: (x) => Number(x.newcomers).toLocaleString("en-US") },
          { key: "returned", label: "Came back", num: true, render: (x) => pct(x.returned, 1) }]} />
        <p class="blk-note">An association across repos, not proof that answering brings a given newcomer back.</p>
      </Framed> : null}
    </Columns> : null}
  </>;
}

function Growth({ c }: { c: CommunityFull }) {
  const [ranges, setRange] = useRange();
  const [pick, setPick] = useState<string | null>(null);
  const tr = c.traffic;
  const ms = ([
    { id: "stars", name: "Stars", sub: `New stars by week; ${(c.stars?.stars ?? 0).toLocaleString("en-US")} in total`, kind: "count", better: "up", period: "week", points: points(c.stars?.weeks),
      meaning: (v) => `${count(v, "new star")} that week.`, info: { title: "Stars", body: "Each point is the stars gained that week (GitHub's history, no names). The total is every star the repo has now." } },
    { id: "views", name: "Views", sub: `per day; ${tr?.views_total ?? 0} in ${tr?.days ?? 0} days`, kind: "count", better: "up", period: "day", points: points(tr?.views),
      meaning: (v) => `${count(v, "view")} that day.` },
    { id: "clones", name: "Clones", sub: `per day; ${tr?.clones_total ?? 0} in all`, kind: "count", better: "up", period: "day", points: points(tr?.clones),
      meaning: (v) => `${count(v, "clone")} that day.` },
  ] as Metric[]).filter((m) => m.points.length);
  const refs = (tr?.referrers || []).map((r) => (Array.isArray(r) ? { referrer: r[0], count: r[1] } : r));
  if (!ms.length) return <Card><EmptyState icon="community" title="No stars or traffic recorded yet.">GitHub keeps 14 days of traffic; StackVitals keeps it from the first run on.</EmptyState></Card>;
  const m = ms.find((x) => x.id === pick) || ms[0]!;
  return <>
    {c.stars || tr ? <Facts class="is-figures cm-figs" rows={[
      c.stars ? ["Stars in total", fig((c.stars.stars ?? 0).toLocaleString("en-US"))] : null,
      c.stars ? ["New stars, last 12 weeks", fig(c.stars.gained_12w ?? "–", no(c.stars.growth_12w) ? null : `${pct(c.stars.growth_12w, 1)} growth`)] : null,
      tr?.views_total ? ["Views", fig(tr.views_total.toLocaleString("en-US"), `in ${tr.days ?? 0} days`)] : null,
      tr?.views_total ? ["Unique visitors", fig(((tr as R).visitors_total ?? 0).toLocaleString("en-US"), "a day, added up")] : null,
      tr?.clones_total ? ["Clones", fig(tr.clones_total.toLocaleString("en-US"), `in ${tr.days ?? 0} days`)] : null,
    ]} /> : null}
    <Columns ratio="lead">
      <Card><MetricHero metric={m} ranges={ranges} setRange={setRange} height={220} /></Card>
      <Watchlist label="Stars and traffic" items={ms.map((x) => metricItem(x, ranges[x.period] || 12))} selected={m.id} onSelect={setPick} tones={trendTones(ms, ranges)} />
    </Columns>
    {refs.length ? <Framed title="Where visitors came from" note={(tr as R)?.referrers_day ? `GitHub's top sites on ${day((tr as R).referrers_day)}.` : "GitHub's top sites."}>
      <Table name="referrers" caption="Referrers" search={false} rows={refs} columns={[
        { key: "referrer", label: "Site", primary: true, nowrap: true }, { key: "count", label: "Views", num: true }]} /></Framed> : null}
  </>;
}

export default function Community({ app }: PageProps) {
  const f = useFiles<{ c: CommunityFull }>({ c: "community.json" });
  if (!f.ready) return <PageSkeleton />;
  const c = f.c;
  const title = "Community", sub = "Outside contributors and newcomers: who is waiting, how fast they hear back, and whether they come back.";
  if (!c || !app) return <Page title={title} subtitle={sub}><EmptyState icon="community" title="Community hasn't run here yet."
    action={<Button variant="filled" href="#/settings" icon="settings">Turn it on</Button>}>Add <code class="code-inline">community</code> to the workflow's modules.</EmptyState>
    {app ? <Section title="From your machine" description="The same report for any public repo, from a terminal with a read-only token."><MachineReport app={app} /></Section> : null}</Page>;
  return <Main app={app} c={c} title={title} sub={sub} />;
}

function Main({ app, c, title, sub }: { app: AppJson; c: CommunityFull; title: string; sub: string }) {
  const q = c.quarters || [], last = q[q.length - 1] || ({} as NonNullable<CommunityFull["quarters"]>[number]), before = q[q.length - 2] || ({} as typeof last);
  const waiting = c.waiting || [];
  const gh = (w: { kind: string; n: number }) => `https://github.com/${app.repo}/${w.kind === "issue" ? "issues" : "pull"}/${w.n}`;
  const fu = c.funnel as R | null | undefined;
  return <Page title={title} subtitle={sub} toolbar={app.modules?.community?.page ? <Button variant="plain" href={app.modules.community.page} iconEnd="external">Printable page</Button> : null}>
    <Section title="Waiting for an answer" description="First-time contributors whose issue or pull request has no human answer yet. Answer in one click on GitHub."
      action={<Pill tone={c.waiting_total ? "watch" : "good"}>{c.waiting_total ? `${c.waiting_total} waiting` : "All answered"}</Pill>}>
      <Framed title="Newcomers waiting" note="Longest wait first.">
        <Table name="newcomers-waiting" caption="Newcomers waiting" rows={waiting} initialSort={{ key: "days", desc: true }} columns={[
          { key: "n", label: "Item", primary: true, raw: (w) => w.n, render: (w) => <a href={gh(w)} target="_blank" rel="noopener noreferrer">{w.kind === "issue" ? "Issue" : "Pull request"} #{w.n}</a> },
          { key: "kind", label: "Kind", filter: true, raw: (w) => (w.kind === "issue" ? "issue" : "pull request") },
          { key: "created", label: "Opened", render: (w) => day(w.created) },
          { key: "days", label: "Waiting", num: true, render: (w) => count(w.days, "day") },
          { key: "go", label: "Answer", raw: () => "", render: (w) => <Button size="sm" variant="tinted" href={gh(w)} external iconEnd="external">Reply</Button> }]}
          empty={<Card><EmptyState icon="check" title="No newcomer is waiting.">First-time contributors whose issue or pull request has no answer yet show up here.</EmptyState></Card>} />
      </Framed>
    </Section>

    <Section title="How fast people hear back" description="The first reply to an outside issue or pull request, by channel, and this week against the four before.">
      <Columns ratio="lead">
        <Card><Answers c={c} /></Card>
        <Facts class="is-figures cm-side" rows={[
          ["Score", fig(c.score ? `${c.score.score}/100` : "–", c.score ? "against similar public repos" : "after launch, against public repos")],
          ["Answered within a day", fig(pct(c.facts?.answered_1d_share), no(c.facts?.answered_1d_share) ? "not enough outside items to say" : "of outside contributors heard back")],
          ["Project's answer, outside issues", fig(kmValue(c.answers?.issues?.km), "median, waiting items counted")],
        ]} />
      </Columns>
      <Channels c={c} />
      <ThisWeek changes={c.changes} />
    </Section>

    <Section title="What the project states" description="What the repo promises and says about itself, beside what it does.">
      {c.context ? <Stated c={c} /> : <Card><EmptyState icon="about" title="Not read yet.">The next run reads the contributing guide, governance and funding files.</EmptyState></Card>}
    </Section>

    {q.length ? <Section title="Quarter by quarter" description={`${last.quarter || "This quarter"} against ${before.quarter || "the one before"}.`}>
      <Facts class="is-figures cm-figs" rows={[
        ["Items from outside", fig(last.items ?? "–", change(last.items, before.items, String))],
        ["First answer, median", fig(hours(last.median_hours), change(last.median_hours, before.median_hours, hours))],
        ["Answered within a day", fig(pct(last.within_1d), change(last.within_1d, before.within_1d, (v) => `${Math.round(v * 100)} points`))],
        ["Newcomers", fig(last.newcomers ?? "–", change(last.newcomers, before.newcomers, String))]]} />
      <Framed title="Every quarter" note="Oldest first.">
        <Table name="quarters" caption="Quarters" search={false} rows={q} columns={[
          { key: "quarter", label: "Quarter", primary: true }, { key: "items", label: "Items", num: true, render: (r) => r.items ?? "–" },
          { key: "median_hours", label: "First answer", num: true, render: (r) => hours(r.median_hours) },
          { key: "within_1d", label: "Within a day", num: true, render: (r) => pct(r.within_1d) }, { key: "newcomers", label: "Newcomers", num: true, render: (r) => r.newcomers ?? "–" }]} />
      </Framed>
    </Section> : null}

    <Section title="Who carries the work" description="How spread the merged work is, and whether newcomers wait longer than regulars."><People c={c} /></Section>

    <Section title="Do newcomers stay" description="Newcomers by the month they first contributed, and who came back with new work. A month too recent says –.">
      <Facts class="is-figures cm-figs" rows={[
        ["Newcomers who came back", fig(pct(c.facts?.newcomer_return_rate ?? fu?.return_rate), fu ? `${fu.returned} of ${fu.judged} judged, within 90 days` : null)],
        ["Newcomers answered within 2 weeks", fig(pct((c.facts as R | undefined)?.newcomer_answered_share), "first pull requests that got a reply")],
        ["Maintainers", fig(fu?.maintainers ?? "–", fu ? `${fu.regulars ?? 0} regulars` : null)]]} />
      <Framed title="Newcomer cohorts" note="By the month of their first contribution.">
        <Table name="cohorts" caption="Newcomer cohorts" search={false} rows={c.cohorts?.months || []} columns={[{ key: "month", label: "First contributed", primary: true },
          { key: "newcomers", label: "Newcomers", num: true },
          { key: "back_by_90d", label: "Back within 90 days", num: true, render: (r) => (r.back_by_90d === null ? "–" : `${r.back_by_90d} (${pct(r.back_by_90d / r.newcomers)})`) },
          { key: "back_90_180d", label: "Back 90 to 180 days on", num: true, render: (r) => (r.back_90_180d === null ? "–" : `${r.back_90_180d} (${pct(r.back_90_180d / r.newcomers)})`) }]}
          empty={<Card><EmptyState icon="community" title="No newcomers in the last year.">Each month's first-time contributors show here.</EmptyState></Card>} />
      </Framed>
    </Section>

    <Section title="Against similar public repos" description="Where the score comes from, and what the public record says about answering newcomers."><Bench c={c} /></Section>

    <Section title="Stars and traffic" description="Pick a row to chart it. Drag across the chart to read a day."><Growth c={c} /></Section>

    <Section title="The report for another repo" description="This page is the report for this repo, rebuilt by every run. For any other public repo, it runs from your machine.">
      <MachineReport app={app} /></Section>
  </Page>;
}
