// About's structured parts: the modules table (what each answers, where its data comes from) and the accuracy tables.
import { useEffect, useState } from "preact/hooks";
import { href } from "../../app/router";
import { Button } from "../../ui/Button";
import { Skeleton } from "../../ui/bits";
import { Field, Select } from "../../ui/controls";
import { Card } from "../../ui/Page";
import { Table, type Column } from "../../ui/Table";

interface Mod { id: string; name: string; page: string; answers: string; from: string }
const MODULES: Mod[] = [
  { id: "ci", name: "CI Health", page: "ci", answers: "Which tests and jobs are flaky, failing or slow, and what CI costs.", from: "Your CI runs, jobs, steps and test reports (JUnit, CTRF, Jest, Go, TRX)." },
  { id: "prs", name: "Pull Requests", page: "prs", answers: "Who has to act next on each pull request, and how long reviews wait.", from: "Pull requests, reviews, comments and CODEOWNERS." },
  { id: "delivery", name: "Delivery", page: "delivery", answers: "DORA's metrics, cycle time in four phases and stuck pull requests.", from: "Merged pull requests, deployments and commit statuses; incidents from a pager you connect." },
  { id: "insights", name: "Insights", page: "insights", answers: "What to fix first, ranked by the hours of waiting at stake.", from: "The other modules' history, combined." },
  { id: "community", name: "Community", page: "community", answers: "Whether newcomers get a first answer, stay, and who carries the work.", from: "Issues and pull requests from first-time contributors, stars and traffic." },
  { id: "deps", name: "Dependencies", page: "deps", answers: "Known vulnerabilities, waiting security updates, licences and supply chain.", from: "Your lockfiles scanned with OSV-Scanner; package names looked up on deps.dev, Scorecard and the registries." },
  { id: "investment", name: "Investment", page: "investment", answers: "Where merged work went each month: features, fixes, maintenance.", from: "Merged pull requests, sorted by label, linked issue type, title or the files changed." },
  { id: "portal", name: "Portal", page: "portal", answers: "What an org owns, who owns it and how each repo scores.", from: "Every repo in the org, CODEOWNERS, teams and catalog-info.yaml files." },
  { id: "standing", name: "Where you stand", page: "standing", answers: "How this repo compares with similar public repos.", from: "A daily crawl of about 90,000 public repos, grouped by language and size." },
  { id: "explore", name: "Explore", page: "explore", answers: "Any question the pages don't answer, in SQL.", from: "The summary tables every module writes: one row per pull request, job and test." },
];

export function ModuleTable() {
  return <Table rows={MODULES} name="modules" caption="What StackVitals measures" search={false} columns={[
    { key: "name", label: "Module", primary: true, render: (m) => <a class="ab-mod" href={href(m.page)}>{m.name}</a> },
    { key: "answers", label: "What it answers" },
    { key: "from", label: "Where the data comes from", render: (m) => <span class="ab-from">{m.from}</span> }]} />;
}

type Cards = typeof import("../accuracy-data.js").CARDS;
interface Acc { id: string; title: string; check: string; result: string; n: number; labeller: string; weak: string; link: string }

export function Accuracy() {
  const [cards, setCards] = useState<Cards | null>(null);
  const [pick, setPick] = useState("");
  useEffect(() => { import("../accuracy-data.js").then((m) => setCards(m.CARDS)); }, []);
  if (!cards) return <Card><Skeleton lines={4} /></Card>;
  const rows: Acc[] = cards.map((c) => ({ id: c.id, title: c.title, check: c.rows[0]?.[0] || "", result: c.rows[0]?.[1] || "", n: c.rows.length,
    labeller: c.labeller, weak: c.weak, link: c.link }));
  const cols: Column<Acc>[] = [
    { key: "title", label: "Rule", primary: true, render: (r) => <a class="ab-mod" id={`acc-${r.id}`} href={`#acc-rows`} onClick={(e) => { e.preventDefault(); setPick(r.id);
      document.getElementById("acc-rows")?.scrollIntoView({ behavior: "smooth", block: "start" }); }}>{r.title}</a> },
    { key: "check", label: "Headline check" },
    { key: "result", label: "Result", num: true, render: (r) => <b class="ab-result">{r.result}</b> },
    { key: "n", label: "Checks", num: true },
    { key: "weak", label: "Weak spot", render: (r) => <span class="ab-weak"><span class="sv-mark sv-mark-watch" aria-hidden="true" />{r.weak}</span> },
  ];
  const c = cards.find((x) => x.id === pick) || cards[0]!;
  return <>
    <Table rows={rows} columns={cols} name="accuracy" caption="How accurate each rule is" search={false} />
    <div class="ab-detail" id="acc-rows">
      <div class="ab-detail-head">
        <h3 class="ab-h3">Every check behind one rule</h3>
        <Field label="Rule">{(fid) => <Select id={fid} value={c.id} onChange={setPick} options={cards.map((x) => ({ value: x.id, label: x.title }))} />}</Field>
      </div>
      <dl class="ab-facts">
        <div><dt>What it claims</dt><dd>{c.claim}</dd></div>
        <div><dt>Labels</dt><dd>{c.labeller}</dd></div>
        <div><dt>Weak spot</dt><dd>{c.weak}</dd></div>
      </dl>
      <Table rows={c.rows.map(([check, result, note], i) => ({ id: `${c.id}-${i}`, check, result, note }))} name={`accuracy-${c.id}`} caption={`${c.title}: every check`} search={false}
        columns={[{ key: "check", label: "Check", primary: true }, { key: "result", label: "Result", num: true, render: (r) => <b class="ab-result">{r.result}</b> },
          { key: "note", label: "Range and notes", render: (r) => r.note || <span class="muted">–</span> }]} />
      <div class="ab-foot"><Button size="sm" variant="tinted" href={c.link} external iconEnd="external">Method and labels</Button></div>
    </div>
  </>;
}
