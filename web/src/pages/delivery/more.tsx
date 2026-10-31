// Delivery's in-depth tabs that load only when opened: AI-assisted work, issues and sprints, and the merge queue.
import { useState } from "preact/hooks";
import { BarChart } from "../../charts/BarChart";
import { dateLabel, day, hours, pct } from "../../data/format";
import type { AppJson } from "../../data/types";
import { EmptyState } from "../../ui/bits";
import { Card, Columns, Stat, Stats } from "../../ui/Page";
import { safeHref } from "../../ui/Button";
import { Table } from "../../ui/Table";
import { Framed, Mark, Panel, SubHead } from "./blocks";

type R = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
const gh = (app: AppJson, p: string) => `https://github.com/${app.repo}${p}`;
const ext = { target: "_blank", rel: "noopener noreferrer" };
const n0 = (v: unknown) => (v ?? "–") as string;
const AFTER: [string, string, (v: any) => string][] = [["n", "Merged PRs", n0], ["merge_rate", "Merge rate", pct], ["pickup_p75_h", "Pickup P75", hours], ["review_p75_h", "Review P75", hours],
  ["size_p75", "Size P75, lines", n0], ["ci_n", "Merged since the CI history began", n0], ["ci_failed_share", "A CI run on the PR failed", pct],
  ["flaky_share", "A failed run passed on re-run", pct], ["reverted_share", "Reverted later", pct], ["failed_deploy_share", "Shipped in a deployment with an incident", pct]];
const MATCHED = [["reverted", "Reverted"], ["ci_failed", "A CI run failed"], ["failed_deploy", "Shipped in a failed deployment"], ["merged", "Merged"], ["merged_by_others", "Merged by someone else"]];
const TYPES: R = { REQUIREMENT: "Stories and features", BUG: "Bugs", TASK: "Tasks", INCIDENT: "Incidents" };

function verdict(c: R | undefined): [string, boolean] {
  if (!c || c.verdict === "too few" || c.gap == null) return ["too few to compare", false];
  const pts = (x: number) => `${x >= 0 ? "+" : ""}${Math.round(x * 100)}`, unit = (x: number) => (Math.abs(Math.round(x * 100)) === 1 ? "point" : "points");
  if (c.verdict === "no measurable difference") return [`no measurable difference (could detect ${Math.round(c.detectable * 100)} ${unit(c.detectable)} or more)`, false];
  return [`${c.verdict === "higher" ? "more often" : "less often"}: ${pts(c.gap)} ${unit(c.gap)}, likely ${pts(c.low)} to ${pts(c.high)}`, c.verdict === "higher"];
}

function Compared({ title, rows, peers }: { title: string; rows?: R; peers?: string | null }) {
  return <div><Framed title={title}>
    <Table name={`ai-${title.slice(0, 12)}`} search={false} rows={MATCHED.filter(([k]) => rows?.[k!]).map(([k, label]) => {
      const c = rows![k!], [text, warn] = verdict(c);
      return { label, text, warn, matched: c.of ? `${c.matched} of ${c.of}${c.matched_share != null ? ` (${pct(c.matched_share)})` : ""}` : "–" };
    })} columns={[{ key: "label", label: "Outcome", primary: true },
      { key: "text", label: "Against like for like", render: (r) => (r.warn ? <Mark tone="watch">{r.text}</Mark> : r.text) },
      { key: "matched", label: "Matched", num: true }]} empty={<Card><p class="blk-note">Too few to compare yet.</p></Card>} /></Framed>
    {peers ? <p class="blk-note dl-after">{peers}</p> : null}</div>;
}

// What arrives for review against what merges, agents' and people's; the queue waiting now; what open PRs can expect.
function ReviewLoad({ load, expected }: { load: R; expected: R[] }) {
  const weeks: R[] = load.weeks || [], last = weeks[weeks.length - 1] || {}, r = load.reviewers || {};
  const sum = (x: R) => (x?.agent || 0) + (x?.person || 0);
  const known = expected.filter((e) => e.p50_h != null).sort((a, b) => (b.p75_h || 0) - (a.p75_h || 0));
  return <>
    <SubHead title="Review load" note="agents add pull requests faster than reviewers grow" />
    <Stats>
      <Stat label="Opened this week" value={sum(last.opened)} note={`${last.opened?.agent ?? 0} by agents; ${sum(last.merged)} merged`} />
      <Stat label="Waiting for a first review" value={sum(load.waiting)} note={`${load.waiting?.agent ?? 0} from agents, drafts left out`} />
      <Stat label="Reviewers with open requests" value={r.n ?? 0} note={`the busiest holds ${r.max_open ?? 0}; ${pct(r.agent_share)} of requests are for agents' PRs`} />
    </Stats>
    <Framed title="Week by week" note="opened and merged, agents and people"><Table name="review-weeks" search={false} rows={[...weeks].reverse()} columns={[
      { key: "week_end", label: "Week to", primary: true, raw: (w) => day(w.week_end) },
      { key: "oa", label: "Opened by agents", num: true, raw: (w) => w.opened?.agent ?? 0 }, { key: "op", label: "Opened by people", num: true, raw: (w) => w.opened?.person ?? 0 },
      { key: "ma", label: "Merged, agents", num: true, raw: (w) => w.merged?.agent ?? 0 }, { key: "mp", label: "Merged, people", num: true, raw: (w) => w.merged?.person ?? 0 }]} /></Framed>
    {known.length ? <Framed title="Review an open pull request can expect" note="from similar ones merged here (same kind and size)">
      <Table name="expected-review" search={false} rows={known.slice(0, 50)} columns={[
        { key: "pr", label: "Pull request", primary: true, raw: (e) => `#${e.pr}` }, { key: "kind", label: "By", filter: true, raw: (e) => (e.kind === "agent" ? "Agent" : e.kind === "person" ? "Person" : e.kind) },
        { key: "p50_h", label: "Review, typical", num: true, render: (e) => hours(e.p50_h) }, { key: "p75_h", label: "Review, 3 in 4 within", num: true, render: (e) => hours(e.p75_h) },
        { key: "similar", label: "Similar PRs", num: true }]} /></Framed> : null}
  </>;
}

// Of the lines squash-merged PRs added, the share still in the default branch 30 and 90 days later.
function Survival({ s }: { s: R }) {
  const cell = (age: string, who: string) => { const x = s[age]?.[who]; return x ? `${pct(x.share)} (${x.prs} PRs)` : "–"; };
  return <>
    <SubHead title="Code that lasted" note="lines still in the default branch, by git blame; squash-merged PRs only" />
    <Stats>
      <Stat label="People's PRs, 30 days" value={cell("30", "people")} />
      <Stat label="Agents' PRs, 30 days" value={cell("30", "agents")} />
      <Stat label="People's PRs, 90 days" value={cell("90", "people")} />
      <Stat label="Agents' PRs, 90 days" value={cell("90", "agents")} />
    </Stats>
  </>;
}

export function AI({ ai, survival }: { ai: R; survival?: R }) {
  const o = ai.outcomes || {}, w = o.window, b = ai.baseline, a = ai.agent_prs || {}, cov = o.coverage || {}, m = o.matched || {};
  const total = (x: R) => (x?.agent?.n || 0) + (x?.assisted?.n || 0) + (x?.others?.n || 0);
  if (!w || !total(w)) return <Card><EmptyState icon="delivery" title="No merged pull requests in the last 6 months.">This fills in after Team Flow reads some.</EmptyState></Card>;
  const months: R[] = o.monthly || [], side = (k: string) => w[k] || {};
  const g = b?.matched?.merged_by_others;
  const pts = (x: number) => `${x >= 0 ? "+" : ""}${Math.round(x * 100)}`;
  const peers = g ? `Similar public repos (${b.matched.repos} ${b.group}): merged by someone else ${pts(g.gap)} ${Math.abs(Math.round(g.gap * 100)) === 1 ? "point" : "points"} (likely ${pts(g.low)} to ${pts(g.high)}) against people's PRs of the same repo, month and size.` : null;
  const cp = ai.copilot;
  return <>
    <Stats>
      <Stat label="People's PRs with an AI marker" value={pct(cov.marked_share)} note={`${cov.marked ?? 0} of ${cov.people_prs ?? 0}; ${cov.authors_marking ?? 0} of ${cov.authors ?? 0} authors`} />
      <Stat label="Coding agents' PRs merged" value={side("agent").n ?? 0} note={`last 6 months; from an agent's account or branch (codex/, claude/, copilot/)${a.n ? `; ${pct(a.merged_share)} of the account's ${a.n} PRs merged` : ""}`} />
      <Stat label="Agents' PRs merged, similar repos" value={b ? pct(b.agent_merged) : "–"} note={b ? `the crawl's median of ${b.repos} ${b.group}; outside contributors ${pct(b.outsider_merged)}` : "no crawl file yet"} />
      <Stat label="Reviewed by an AI bot" value={ai.ai_reviewed_prs?.n ?? 0} note="merged PRs" />
    </Stats>
    {cp ? <><SubHead title={`Copilot in ${cp.org}, last ${cp.window_days} days`} note={`GitHub's reports, ${cp.days_kept} days kept since ${day(cp.first_day)}`} />
      <Stats>
        <Stat label="Monthly active users" value={cp.monthly_active_users ?? "–"} note={`${cp.monthly_active_agent_users ?? 0} used the agent`} />
        <Stat label="Suggestions accepted" value={pct(cp.acceptance)} />
        <Stat label="PRs by Copilot, org" value={cp.org_prs_by_copilot} note={`${cp.org_prs_merged_by_copilot} merged`} />
        <Stat label="PRs by Copilot, this repo" value={cp.repo_prs_by_copilot} note={`${cp.repo_prs_merged_by_copilot} merged`} />
      </Stats></> : null}
    <Columns>
      <Compared title="AI-marked PRs against the same authors' other PRs" rows={m.assisted} />
      <Compared title="Coding agents' PRs against people's of the same month and size" rows={m.agent} peers={peers} />
    </Columns>
    <Columns>
      <Framed title="Raw shares, not matched"><Table name="ai-after" search={false} rows={AFTER.map(([k, label, f]) => { const v = (x: R) => f(x[k]) + (k === "merge_rate" && x.merge_rate_n ? ` of ${x.merge_rate_n}` : "");
          return { k, label, g: v(side("agent")), a: v(side("assisted")), o: v(side("others")) }; })}
        columns={[{ key: "label", label: "Measure", primary: true }, { key: "g", label: "Agents", num: true }, { key: "a", label: "AI-marked", num: true }, { key: "o", label: "Others", num: true }]} /></Framed>
      <Panel title="People's merged PRs with an AI marker" state={<span class="muted">per month</span>}>
        {months.length ? <BarChart label="Share of people's merged PRs with an AI marker, per month" kind="share" height={180}
          bars={months.map((x) => { const n = (x.assisted?.n || 0) + (x.others?.n || 0); return { label: dateLabel(x.month), value: n ? (x.assisted?.n || 0) / n : 0 }; })} /> : <p class="blk-note">No months yet.</p>}
        <Table name="ai-months" search={false} rows={[...months].reverse()} columns={[
          { key: "month", label: "Month", primary: true }, { key: "gn", label: "Agents", num: true, raw: (x) => x.agent?.n || 0 },
          { key: "an", label: "AI-marked", num: true, raw: (x) => x.assisted?.n || 0 }, { key: "on", label: "Others", num: true, raw: (x) => x.others?.n || 0 }]} /></Panel>
    </Columns>
    {ai.spend ? <><SubHead title="What the AI tools cost" note={`last ${ai.spend.window_days} days; Cursor: its current billing cycle`} />
      <Stats>
        <Stat label="AI spend" value={`$${Number(ai.spend.total_usd).toLocaleString()}`} note={Object.entries(ai.spend.providers || {}).map(([k, v]) => `${k} $${Number(v).toLocaleString()}`).join(", ")} />
        <Stat label="Per merged AI-involved PR" value={ai.spend.per_ai_pr_usd == null ? "–" : `$${Number(ai.spend.per_ai_pr_usd).toLocaleString()}`} note={`${ai.spend.ai_prs} agents' and AI-marked PRs merged; all API use counts, not only coding`} />
        {ai.spend.cursor_agent_requests != null ? <Stat label="Cursor agent requests" value={ai.spend.cursor_agent_requests} /> : null}
      </Stats>
      {ai.spend.tools ? <Framed title="The coding tools side by side" note="same days"><Table name="ai-tools" search={false} caption="The coding tools side by side, same days"
        rows={Object.entries(ai.spend.tools).map(([k, v]) => ({ k: k === "claude_code" ? "Claude Code" : "Cursor", ...(v as R) }) as R)} columns={[
          { key: "k", label: "Tool", primary: true }, { key: "lines_added", label: "Lines added", num: true },
          { key: "commits", label: "Commits", num: true, render: (x: R) => (x.commits == null ? "–" : String(x.commits)) },
          { key: "prs", label: "PRs opened", num: true, render: (x: R) => (x.prs == null ? "–" : String(x.prs)) },
          { key: "acceptance", label: "Edits accepted", num: true, render: (x: R) => (x.acceptance == null ? "–" : pct(x.acceptance)) },
          { key: "use", label: "Use", num: true, raw: (x: R) => x.sessions ?? x.agent_requests, render: (x: R) => (x.sessions != null ? `${x.sessions} sessions` : `${x.agent_requests} agent requests`) }]} /></Framed> : null}
    </> : null}
    {Object.keys(ai.by_agent || {}).length ? <Framed title="Each coding agent" note="last 6 months; rates need 10 PRs">
      <Table name="ai-agents" search={false} rows={Object.entries(ai.by_agent).map(([k, v]) => ({ k, ...(v as R) }) as R)} columns={[
        { key: "k", label: "Agent", primary: true, raw: (r) => { const s = String(r.k).replace(/ agent$/, ""); return s.charAt(0).toUpperCase() + s.slice(1); } },
        { key: "prs", label: "Merged PRs", num: true }, { key: "merge_rate", label: "Merge rate", num: true, render: (r) => pct(r.merge_rate) },
        { key: "rounds", label: "Review rounds, median", num: true, raw: (r) => r.review_rounds_p50, render: (r) => r.review_rounds_p50 ?? "–" },
        { key: "review", label: "Review P75", num: true, raw: (r) => r.window?.review_p75_h, render: (r) => hours(r.window?.review_p75_h) },
        { key: "ci", label: "CI failed", num: true, raw: (r) => r.window?.ci_failed_share, render: (r) => pct(r.window?.ci_failed_share) },
        { key: "rev", label: "Reverted", num: true, raw: (r) => r.window?.reverted_share, render: (r) => pct(r.window?.reverted_share) }]} /></Framed> : null}
    {ai.leaderboard ? <><Framed title="Coding agents across public repos" note={`the crawl's last ${ai.leaderboard.window_days ?? 180} days; agents seen in 10+ repos`}>
      <Table name="ai-leaderboard" search={false} rows={Object.entries(ai.leaderboard.agents || {}).map(([k, v]) => ({ k, ...(v as R) }) as R)} columns={[
        { key: "k", label: "Agent", primary: true, raw: (r) => { const s = String(r.k); return s.charAt(0).toUpperCase() + s.slice(1); } },
        { key: "repos", label: "Repos", num: true }, { key: "prs", label: "Decided PRs", num: true },
        { key: "merged", label: "Merged", num: true, render: (r) => pct(r.merged) },
        { key: "others", label: "Merged by someone else", num: true, raw: (r) => r.merged_by_others, render: (r) => pct(r.merged_by_others) },
        { key: "gap", label: "Against people's PRs", num: true, raw: (r) => r.vs_people?.gap,
          render: (r) => (r.vs_people ? `${r.vs_people.gap >= 0 ? "+" : ""}${Math.round(r.vs_people.gap * 100)} pts` : "–") },
        { key: "here", label: "Here", num: true, raw: (r) => (ai.by_agent || {})[`${r.k} agent`]?.merge_rate,
          render: (r) => pct((ai.by_agent || {})[`${r.k} agent`]?.merge_rate) }]} /></Framed>
      <p class="blk-note">Against people's PRs: the gap in merged share with people's pull requests of the same repo, month and size. "Here" is this repo's own merge rate for that agent.</p></> : null}
    {ai.review_load ? <ReviewLoad load={ai.review_load} expected={ai.expected_review || []} /> : null}
    <p class="blk-note">Totals only, never a person, and an association rather than a cause. Like-for-like comparisons follow AIDev's and Watanabe's designs: a person's AI-marked PRs against the same person's other PRs of a similar size; coding agents' PRs (their account, or an agent's branch such as codex/) against people's PRs of the same month and size, since an agent has no "same author". Unmarked PRs can still have had AI help. CI shares cover PRs merged since the CI history began; failed deployments only deployments of up to 5 PRs.</p>
    {survival ? <Survival s={survival} /> : null}
  </>;
}

export function Issues({ t }: { t: R }) {
  return <>
    <Stats>
      <Stat label="Issues read" value={t.issues} note={`from ${(t.sources || []).map((x: string) => (x === "jira" ? "Jira" : x === "linear" ? "Linear" : x)).join(" and ")}`} />
      <Stat label="Merged PRs naming an issue" value={pct(t.merged_prs ? t.linked_prs / t.merged_prs : null)} note={`${t.linked_prs} of ${t.merged_prs}`} />
      <Stat label="Tracker incidents" value={t.incidents} note="in DORA's failure rate and recovery" />
    </Stats>
    <Framed title="Lead and cycle time, finished issues" note="lead from created, cycle from the first in-progress status"><Table name="issue-times" search={false} rows={Object.entries(t.lead_time || {}).map(([k, v]) => ({ k, ...(v as R) }))} columns={[
      { key: "k", label: "Type", primary: true, raw: (r) => TYPES[r.k] || r.k }, { key: "n", label: "Done", num: true },
      ...["lead_p50_h", "lead_p75_h", "cycle_p50_h", "cycle_p75_h"].map((k) => ({ key: k, label: k.replace(/_h$/, "").replace("_p", " P").replace(/^./, (c) => c.toUpperCase()), num: true, render: (r: R) => hours(r[k]) }))]} /></Framed>
    <Framed title="Sprints and cycles" note="carried over: still open when it closed"><Table name="sprints" search={false} rows={[...(t.planning || [])].reverse()} columns={[
      { key: "name", label: "Sprint", primary: true }, { key: "state", label: "State", raw: (x) => String(x.state || "").toLowerCase() },
      { key: "scope", label: "Scope", num: true }, { key: "done", label: "Done", num: true }, { key: "carried_over", label: "Carried over", num: true },
      { key: "added_after_start", label: "Added after start", num: true },
      { key: "points_done", label: "Points done", num: true, render: (x) => (x.points_scope == null ? "–" : `${x.points_done} of ${x.points_scope}`) }]}
      empty={<Card><EmptyState icon="clock" title="No sprints or cycles in the last 180 days.">Teams that work without them see lead and cycle time only.</EmptyState></Card>} /></Framed>
    {t.by_field_team ? <Framed title="Issues done by the tracker's team field"><Table name="issue-field-teams" search={false} caption="Issues done by the tracker's team field"
      rows={Object.entries(t.by_field_team).map(([k, v]) => ({ k, done: v }))} columns={[
        { key: "k", label: "Team", primary: true }, { key: "done", label: "Done", num: true }]} /></Framed> : null}
    {t.by_team ? <>
      <Framed title="Issues done by team" note="each assignee named by an [identity] alias"><Table name="issue-teams" search={false} rows={Object.entries(t.by_team.teams || {}).map(([k, v]) => ({ k, ...(v as R) }))} columns={[
        { key: "k", label: "Team", primary: true }, { key: "done", label: "Done", num: true }]}
        empty={<Card><EmptyState icon="community" title="No assignee is matched to a team yet.">Map each one under [identity] aliases, like "jira:&lt;account id&gt;" = "their-login".</EmptyState></Card>} /></Framed>
      {t.by_team.by_email ? <p class="blk-note">{t.by_team.by_email} of them matched because the assignee's email name is their GitHub login.</p> : null}
      {t.by_team.unmatched ? <p class="blk-note">{t.by_team.unmatched} done issue(s) have an assignee no alias names; add them under [identity] aliases to count them for a team.</p> : null}
      {(t.by_team.suggested || []).length ? <>
        <p class="blk-note">These look like the same person but are not counted until you confirm them. Paste the lines you agree with under [identity.aliases]:</p>
        <pre class="diff" tabIndex={0} style={{ overflow: "auto", fontSize: "0.8125rem" }}><code>{t.by_team.suggested.map((s: R) => `${s.line}  # ${s.issues} issue(s)`).join("\n")}</code></pre>
      </> : null}
    </> : null}
  </>;
}

// Change risk: this repo's own backtest first; the open PRs it scores only when that backtest says the score works here.
export function Risk({ r, repo }: { r: R; repo?: string }) {
  const bt = r.backtest;
  return <>
    <Stats>
      <Stat label="Needed a fix or were reverted" value={r.troubled ?? 0} note="merged PRs a fix soon changed, or a revert undid" />
      <Stat label="Ranks trouble here (AUC)" value={bt ? bt.auc.toFixed(2) : "–"} note={bt ? `0.5 is chance; learnt on ${bt.train} older PRs, checked on ${bt.test} newer (${bt.test_troubled ?? 0} of them needed a fix)` : "not enough history yet"} />
      <Stat label="Trouble in its riskiest fifth" value={bt ? pct(bt.top_fifth_trouble) : "–"} note={bt ? `against ${pct(bt.overall_trouble)} of all newer PRs` : ""} />
    </Stats>
    {r.open ? <Framed title="Open pull requests by change risk" note="riskiest first"><Table name="change-risk" caption="Open pull requests by change risk" rows={r.open as R[]} initialSort={{ key: "risk", desc: true }} columns={[
      { key: "pr", label: "Pull request", primary: true, raw: (s) => s.pr,
        render: (s) => (repo ? <a href={`https://github.com/${repo}/pull/${s.pr}`} target="_blank" rel="noopener noreferrer">#{s.pr}</a> : `#${s.pr}`) },
      { key: "level", label: "Risk", filter: true, render: (s) => <Mark tone={s.level === "high" ? "bad" : s.level === "medium" ? "watch" : "good"}>{String(s.level).charAt(0).toUpperCase() + String(s.level).slice(1)}</Mark> },
      { key: "risk", label: "Chance it needs a fix", num: true, render: (s) => pct(s.risk) },
      { key: "reasons", label: "Why", render: (s) => <span class="muted">{(s.reasons || []).join("; ") || "nothing stands out"}</span> }]} /></Framed>
      : <Card><EmptyState icon="clock" title="No score shown.">{r.note}</EmptyState></Card>}
    <p class="blk-note">A pull request counts as having needed a fix when a fix (by its title or a label) changed the same files within 14 days, or a revert undid it, the lightweight form of SZZ. On 13 public repos the score ranked trouble with AUC 0.72 to 0.80 on six and near chance on three, so each repo is checked on its own history first.</p>
  </>;
}

// What changed before each incident: deployments and pull requests in the 72 hours before it began, likeliest first.
export function Changed({ timelines, repo }: { timelines: R[]; repo?: string }) {
  const link = (ref: string) => (repo && ref.startsWith("#") ? <a href={`https://github.com/${repo}/pull/${ref.slice(1)}`} target="_blank" rel="noopener noreferrer">{ref}</a> : ref);
  const tone = (k: string): "accent" | "watch" | "neutral" => (k === "deployment" ? "accent" : k === "dependency" || k === "config" ? "watch" : "neutral");
  return <>
    <SubHead title="What changed before each incident" note={`the ${timelines[0]?.window_hours ?? 72} hours before it began; likeliest first`} />
    {timelines.map((t) => <Framed title={`${t.incident.source === "issue" ? "Issue" : "Pull request"} #${t.incident.number}`} note={`began ${day(t.incident.created)}`}>
      <Table name={`changed-${t.incident.number}`} search={false} rows={t.candidates.slice(0, 6).map((c: R, i: number) => ({ ...c, rank: i + 1, id: `${i}` }))} columns={[
        { key: "rank", label: "Rank", num: true },
        { key: "kind", label: "Kind", render: (c: R) => <Mark tone={tone(c.kind)}>{String(c.kind).charAt(0).toUpperCase() + String(c.kind).slice(1)}</Mark> },
        { key: "ref", label: "Change", primary: true, render: (c: R) => <>{link(c.ref)}{c.title ? <span class="muted"> {c.title}</span> : null}</> },
        { key: "why", label: "Why it's here", render: (c: R) => <span class="muted">{c.why}</span> }]}
        empty={<Card><p class="blk-note">Nothing was deployed or merged in the {t.window_hours ?? 72} hours before it.</p></Card>} /></Framed>)}
    <p class="blk-note">Ranked by: the deployment the incident is tied to (or the last one before it), pull requests a revert later undid, the ones that shipped in that deployment, then closeness in time. Dependency and configuration changes are marked. A starting point, not a verdict.</p>
  </>;
}

export function Queue({ app, q }: { app: AppJson; q: R }) {
  const rm = Object.entries(q.removals || {}) as [string, number][];
  return <>
    <Stats>
      <Stat label="Through the queue" value={q.prs} note={`${q.merged} merged, last ${q.window_days} days`} />
      <Stat label="Entering to merge, median" value={hours(q.p50_h)} note={`9 in 10 within ${hours(q.p90_h)}`} />
      <Stat label="Taken out" value={rm.reduce((s, [, v]) => s + v, 0)} note={rm.map(([k, v]) => `${k.toLowerCase().replace(/_/g, " ")} ${v}`).join(", ") || "none"} />
      <Stat label="Taken out by a flaky job" value={(q.removed_by_flakes || []).length} note={`${q.failed_runs} of ${q.runs} merge-group runs failed`} />
    </Stats>
    <Framed title="Removals that a flaky job caused"><Table name="queue-flakes" search={false} rows={(q.removed_by_flakes || []) as R[]} columns={[
      { key: "pr", label: "Pull request", primary: true, render: (x) => <a href={gh(app, `/pull/${x.pr}`)} {...ext}>#{x.pr}</a> },
      { key: "at", label: "Taken out", render: (x) => day(x.at) }, { key: "jobs", label: "Flaky jobs", raw: (x) => x.jobs.join(", ") }]}
      empty={<Card><EmptyState icon="check" title="No removal followed a flaky job.">A pull request taken out after a merge-group run that failed only on known flaky jobs shows here.</EmptyState></Card>} /></Framed>
  </>;
}


// The bug backlog week by week: opened, closed, still open, and the oldest open bugs (DevLake's weekly bug retro).
export function Bugs({ b, repo }: { b: R; repo?: string }) {
  const weeks = (b.weeks || []) as R[];
  const last = weeks[weeks.length - 1] || {};
  const link = (x: R) => safeHref(x.url) ? <a href={safeHref(x.url)}>{x.id}</a> : x.src === "github" && repo ? <a href={`https://github.com/${repo}/issues/${x.id}`}>#{x.id}</a> : String(x.id);
  return <>
    <Stats>
      <Stat label="Open bugs" value={b.open ?? 0} note={b.median_open_days == null ? "none open" : `half older than ${b.median_open_days} days`} />
      <Stat label="Opened this week" value={last.opened ?? 0} />
      <Stat label="Closed this week" value={last.closed ?? 0} />
    </Stats>
    <Panel title="Bugs still open at the end of each week"><BarChart label="Bugs still open at the end of each week" kind="count" height={160}
      bars={weeks.map((w) => ({ label: dateLabel(w.week), value: w.open }))} /></Panel>
    <Framed title="Week by week" note="newest first"><Table name="bug-weeks" search={false} rows={[...weeks].reverse()} columns={[
      { key: "week", label: "Week of", primary: true, render: (x: R) => dateLabel(x.week) }, { key: "opened", label: "Opened", num: true },
      { key: "closed", label: "Closed", num: true }, { key: "open", label: "Open at the end", num: true }]} /></Framed>
    {(b.oldest || []).length ? <Framed title="Oldest open bugs" note={`from ${(b.sources || []).join(", ")}`}>
      <Table name="bug-oldest" search={false} rows={b.oldest} columns={[
        { key: "id", label: "Bug", primary: true, render: link }, { key: "days", label: "Open for (days)", num: true }]} /></Framed> : null}
  </>;
}

// Each recent release: what it shipped, the share that were fixes, and what followed it.
export function Releases({ rows, repo }: { rows: R[]; repo?: string }) {
  const pr = (n: number) => repo ? <a href={`https://github.com/${repo}/pull/${n}`}>#{n}</a> : `#${n}`;
  return <Framed title="What each release shipped" note="and what followed it in the next two weeks"><Table name="releases" search={false} caption="What each release shipped and what followed it (two weeks)" rows={rows} columns={[
    { key: "tag", label: "Release", primary: true, render: (x: R) => repo ? <a href={`https://github.com/${repo}/releases/tag/${encodeURIComponent(x.tag)}`}>{x.tag}</a> : x.tag },
    { key: "at", label: "Out", render: (x: R) => day(x.at) }, { key: "prs", label: "PRs", num: true },
    { key: "fix_share", label: "Fixes", num: true, render: (x: R) => (x.fix_share == null ? "–" : pct(x.fix_share)) },
    { key: "reverted", label: "Its PRs reverted", raw: (x: R) => x.reverted.length, render: (x: R) => (x.reverted.length ? <>{x.reverted.map((n: number, i: number) => <>{i ? ", " : ""}{pr(n)}</>)}</> : "none") },
    { key: "incidents_after", label: "Incidents after", num: true, render: (x: R) => `${x.incidents_after}${x.settled ? "" : " so far"}` }]} /></Framed>;
}

// Each recent deployment: what it shipped, who wrote it, its lead time and the incidents blamed on it.
export function Deploys({ rows, repo }: { rows: R[]; repo?: string }) {
  const pr = (n: number) => repo ? <a href={`https://github.com/${repo}/pull/${n}`}>#{n}</a> : `#${n}`;
  const list = (ns: number[]) => ns.length ? <>{ns.slice(0, 8).map((n, i) => <>{i ? ", " : ""}{pr(n)}</>)}{ns.length > 8 ? ` +${ns.length - 8}` : ""}</> : "none";
  return <Framed title="Deployments in the window" note="newest first; what each shipped, its lead time and incidents"><Table name="deploys" search={false} caption="Deployments in the window, newest first" rows={rows} columns={[
    { key: "finished", label: "Finished", primary: true, render: (x: R) => day(x.finished) },
    { key: "sha", label: "Commit", render: (x: R) => x.sha && repo ? <a href={`https://github.com/${repo}/commit/${x.sha}`}><code>{String(x.sha).slice(0, 7)}</code></a> : (x.name || "–") },
    { key: "prs", label: "Pull requests", raw: (x: R) => x.prs.length, render: (x: R) => list(x.prs) },
    { key: "authors", label: "Authors", num: true }, { key: "lead_hours", label: "Lead time", num: true, render: (x: R) => (x.lead_hours == null ? "–" : hours(x.lead_hours)) },
    { key: "incidents", label: "Incidents", raw: (x: R) => x.incidents.length, render: (x: R) => (x.incidents.length ? x.incidents.join(", ") : "none") }]} /></Framed>;
}

// DORA for any dates in the last year, from compact rows, counted as the window's numbers are (DevLake's rules).
const median = (v: number[]) => { const s = [...v].sort((a, b) => a - b); return s.length ? s[Math.floor((s.length - 1) / 2)] : null; };
export function Range({ rows }: { rows: R }) {
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  const [from, setFrom] = useState(iso(new Date(Date.now() - 30 * 864e5)));
  const [to, setTo] = useState(iso(new Date()));
  const end = iso(new Date(new Date(to).getTime() + 864e5));
  const deps = ((rows.deployments || []) as [string, boolean, number | null][]).filter(([f]) => f >= from && f < end);
  const prs = ((rows.prs || []) as [string, number][]).filter(([f]) => f >= from && f < end);
  const weeks = Math.max(1, Math.ceil((new Date(end).getTime() - new Date(from).getTime()) / (7 * 864e5)));
  const perWeek = Array.from({ length: weeks }, (_, w) => { const s = iso(new Date(new Date(from).getTime() + w * 7 * 864e5)), e = iso(new Date(new Date(from).getTime() + (w + 1) * 7 * 864e5));
    return new Set(deps.filter(([f]) => f >= s && f < e).map(([f]) => f.slice(0, 10))).size; });
  const failed = deps.filter(([, bad]) => bad);
  const recov = median(failed.map(([, , h]) => h).filter((h): h is number => h != null));
  const lead = median(prs.map(([, h]) => h));
  return <>
    <p class="blk-note">Any dates in the last year. Deployment days a week is the median week (weeks with none count), as DevLake counts it.</p>
    <div class="range-pick">
      <label>From <input type="date" value={from} max={to} onInput={(e) => setFrom((e.target as HTMLInputElement).value)} /></label>{" "}
      <label>To <input type="date" value={to} min={from} onInput={(e) => setTo((e.target as HTMLInputElement).value)} /></label>
    </div>
    <Stats>
      <Stat label="Deployments" value={deps.length} note={`${median(perWeek) ?? 0} deployment days in the median week`} />
      <Stat label="Lead time" value={lead == null ? "–" : hours(lead)} note={`median of ${prs.length} PRs shipped`} />
      <Stat label="Change fail rate" value={deps.length ? pct(failed.length / deps.length) : "–"} note={`${failed.length} deployments followed by an incident`} />
      <Stat label="Recovery" value={recov == null ? "–" : hours(recov)} note="median, failed deployments" />
    </Stats>
  </>;
}

// The Sonar quality gate and measures, with how each moved over the last month (DevLake's SonarQube dashboards).
export function Quality({ q }: { q: R }) {
  const m = q.measures || {}, before = q.month_ago || {};
  const moved = (k: string, worseUp = true) => before[k] == null || m[k] == null ? undefined
    : `${m[k] - before[k] >= 0 ? "+" : ""}${Math.round((m[k] - before[k]) * 10) / 10} in a month${(m[k] > before[k]) === worseUp && m[k] !== before[k] ? " (worse)" : ""}`;
  return <>
    <Stats>
      <Stat label="Quality gate" value={<span class={`dl-gate dl-gate-${q.gate === "OK" ? "good" : q.gate === "ERROR" ? "bad" : "none"}`}>{q.gate === "OK" ? "passed" : q.gate === "ERROR" ? "failed" : (q.gate || "none")}</span>} note={(q.failing || []).length ? `failing: ${q.failing.join(", ")}` : `${q.project}, read ${q.day}`} />
      <Stat label="Bugs" value={m.bugs ?? "–"} note={moved("bugs")} />
      <Stat label="Vulnerabilities" value={m.vulnerabilities ?? "–"} note={moved("vulnerabilities")} />
      <Stat label="Code smells" value={m.code_smells ?? "–"} note={moved("code_smells")} />
      <Stat label="Coverage" value={m.coverage == null ? "–" : `${m.coverage}%`} note={moved("coverage", false)} />
      <Stat label="Duplication" value={m.duplicated_lines_density == null ? "–" : `${m.duplicated_lines_density}%`} note={moved("duplicated_lines_density")} />
    </Stats>
    {(q.days || []).length > 7 ? <BarChart label="Coverage by week" kind="count" height={140} bars={(q.days as R[]).filter((x) => x.coverage != null).filter((_x, i, a) => (a.length - 1 - i) % 7 === 0).map((x) => ({ label: dateLabel(x.day), value: x.coverage }))} /> : null}
  </>;
}
