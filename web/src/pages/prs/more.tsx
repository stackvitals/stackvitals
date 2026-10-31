// Pull Requests sections that load with the page's lower half: who knows which area, and releases from merges.
import { BarChart } from "../../charts/BarChart";
import { count, pct, secs } from "../../data/format";
import { EmptyState } from "../../ui/bits";
import { Card, Stat, Stats } from "../../ui/Page";
import { Table } from "../../ui/Table";
import { Facts, Framed, Mark, Panel } from "../delivery/blocks";

type R = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

// flow.knowledge: each folder's main author and share of its merged PRs; one person behind most of it is a risk to route around.
export function Knowledge({ k }: { k: R }) {
  const areas: R[] = k.areas || [], hot: R[] = k.hotspots || [];
  const single = areas.filter((a) => a.single_owner);
  const named = areas.some((a) => a.owner);
  if (!areas.length && !hot.length) return <Card><EmptyState icon="prs" title="Not enough merged work to map yet.">Each folder's main author shows once pull requests touching it have merged.</EmptyState></Card>;
  return <>
    <Stats>
      <Stat label="Areas mapped" value={areas.length} note="folders with merged pull requests" />
      <Stat label="Known by one person" value={single.length} note="one author behind most of an area's merged PRs (3 or more)" />
      <Stat label="That person quiet 30+ days" value={single.filter((a) => (a.owner_quiet_days ?? 0) >= 30).length} note="route reviews there before it bites" />
    </Stats>
    <Framed title="Who knows each area" note="busiest first; an area one person carries is marked"><Table name="knowledge" caption="Who knows each area" rows={areas} initialSort={{ key: "prs", desc: true }} columns={[
        { key: "area", label: "Area", primary: true, render: (a: R) => <span class="mono-soft">{a.area}</span> },
        { key: "single_owner", label: "Carried by", filter: true, raw: (a: R) => (a.single_owner ? "One person" : "Several people"),
          render: (a: R) => (a.single_owner ? <Mark tone="watch">One person</Mark> : <Mark tone="good">Several people</Mark>) },
        { key: "prs", label: "Merged PRs", num: true },
        ...(named ? [{ key: "owner", label: "Main author", render: (a: R) => a.owner || "–" }] : []),
        { key: "share", label: "Their share", num: true, render: (a: R) => pct(a.share) },
        { key: "owner_quiet_days", label: "Last active", num: true, raw: (a: R) => a.owner_quiet_days ?? -1,
          render: (a: R) => (a.owner_quiet_days == null ? "–" : a.owner_quiet_days === 0 ? "today" : `${count(a.owner_quiet_days, "day")} ago`) }]}
        empty={<Card><EmptyState icon="check" title="No area mapped yet." /></Card>} /></Framed>
    {hot.length ? <Panel title="Busiest areas" state={<span class="muted">merged PRs, last 90 days</span>}>
      <BarChart label="Busiest areas: merged pull requests in the last 90 days" height={200} bars={hot.map((h) => ({ label: h.area, value: h.prs_90d, tone: "accent" as const }))} /></Panel> : null}
    {named ? null : <Facts rows={[["Names", <>Hidden: this repo is public, so areas are shown without the person behind them. Set <code>knowledge_names = true</code> under <code>[identity]</code> to name them.</>]]} />}
  </>;
}

// flow.delivery: release frequency and merge-to-release time from GitHub releases, with a revert/hotfix failure proxy.
export function Releases({ d }: { d: R }) {
  if (d.source !== "releases") return <Card><EmptyState icon="clock" title="No release in the window.">{d.per_week != null ? `${d.per_week} pull requests merge a week. ` : ""}
    Publishing GitHub releases (or turning on Delivery with deployments) gives merge-to-release time and how often a release needed a fix.</EmptyState></Card>;
  const cf = d.change_fail;
  return <Stats>
    <Stat label="Releases" value={d.releases} note={`${d.per_week} a week`} />
    <Stat label="Merge to release, median" value={secs(d.lead_time_median_s)} note="from merge to the next published release" />
    <Stat label="Releases followed by a fix" value={cf ? pct(cf.rate) : "–"} note={cf ? `${cf.failed} of ${cf.of}${cf.proxy ? "; a revert or hotfix merged before the next release (an estimate)" : ""}` : null} />
    <Stat label="Release to the fixing release, median" value={secs(d.recovery_median_s)} />
  </Stats>;
}
