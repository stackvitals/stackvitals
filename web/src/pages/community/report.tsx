// The community report for any public repo: built here as a command, since it reads that repo's whole history with
// thousands of API calls under your own token and runs the Python analysis, which a browser tab can't.
import { useState } from "preact/hooks";
import type { AppJson } from "../../data/types";
import { Button } from "../../ui/Button";
import { CodeBlock, Pill } from "../../ui/bits";
import { Field, NumberInput, Select, TextInput } from "../../ui/controls";
import { Facts, Panel } from "../deps/blocks";
import { REPO, reportCommand, type Out } from "./command";

export function MachineReport({ app }: { app: AppJson }) {
  const [repo, setRepo] = useState(app.repo);
  const [months, setMonths] = useState(12);
  const [out, setOut] = useState<Out>("html");
  const bad = !!repo.trim() && !REPO.test(repo.trim());
  const page = app.modules?.community?.page;
  return <div class="columns">
    <Panel title="This repo" state={<Pill tone="good" icon={null}>done by the workflow</Pill>}
      bar={page ? <Button size="sm" variant="tinted" href={page} external iconEnd="external">Open the printable page</Button> : null}>
      <Facts rows={[["Repo", <span class="mono-soft">{app.repo}</span>], ["Printable page", page ? "Published beside the app" : "Not published here"]]} />
      <p>Every run rebuilds this report for {app.repo}: the page above, and the printable page and badges the command's --html writes. Nothing to run.</p>
    </Panel>
    <Panel title="Any other public repo" state={<Pill tone="neutral" icon={null}>from your machine</Pill>}>
      <p>It reads the repo's issues, pull requests and contributors with thousands of API calls under your own read-only token, then runs the analysis in Python, so it can't run in this tab.</p>
      <div class="blk-form">
        <Field label="Repo" error={bad ? "Write it as owner/name" : null}>{(id) => <TextInput id={id} mono value={repo} onInput={setRepo} placeholder="owner/name" maxLength={140} />}</Field>
        <Field label="History on the first run" hint="Months to read back.">{(id) => <NumberInput id={id} value={months} onInput={setMonths} min={1} max={60} unit="months" />}</Field>
        <Field label="Output">{(id) => <Select id={id} value={out} onChange={setOut} options={[{ value: "html", label: "Page and badges in a folder" }, { value: "text", label: "Text in the terminal" }, { value: "json", label: "JSON file" }]} />}</Field>
      </div>
      <CodeBlock inline code={reportCommand(repo, months, out)} note="pip install stackvitals first; it uses GITHUB_TOKEN or your gh login, and writes nothing to GitHub." />
    </Panel>
  </div>;
}
