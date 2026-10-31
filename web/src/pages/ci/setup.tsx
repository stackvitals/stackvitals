// "Set up in your CI": a workflow file built from what this page knows (runner, test files, the features to turn on),
// added in one click through GitHub's editor (no token) or as a pull request opened with a token that can write.
import { useEffect, useMemo, useState } from "preact/hooks";
import { store, useStore } from "../../data/store";
import type { AppJson, CiJson } from "../../data/types";
import { makeApi } from "../../github/client";
import { writeToken } from "../../github/session";
import { filePr } from "../../github/setup";
import { account } from "../../github/token";
import { Button } from "../../ui/Button";
import { CodeBlock, CopyButton, toast } from "../../ui/bits";
import { onPrefill } from "../../ui/prefill";
import { PASTE_FILE_BEFORE, type PrefillLink } from "../../github/links";
import { Field, Select, Stepper, TextInput, Toggle } from "../../ui/controls";
import { Icon } from "../../ui/icons";
import { Facts, Framed, jump } from "./parts";
import { BENEFIT, FEATURES, PRESETS, RUNNERS, TEST_BRANCH, TEST_FILE, TEST_WORKFLOW, byHand, fileLink, guessRunner, scripts, sq, suggestShards, testWorkflow,
  type Feature, type Options, type RunnerId } from "./workflowgen";

type R = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

// Another section asks for a feature: the builder ticks it and comes into view.
const wanted = store<Feature | null>(null);
export function ask(f: Feature) { wanted.set(null); wanted.set(f); jump("ci-setup"); }

const TESTISH = /test|unit|integration|e2e|spec|pytest|jest|vitest|playwright|rspec|surefire|connected/i;
const wfName = (w?: string) => (w || "").split("/").pop()!.replace(/\.ya?ml$/, "");

// The runner and test glob the builder has now (or the guess before it renders), for the commands elsewhere on the page.
const choice = store<{ repo: string; runner: RunnerId | null; tests: string | null } | null>(null);
const runnerGuess = (ci: CiJson) => guessRunner(
  [...(ci.tests || []), ...(ci.new_tests || [])].map((t) => t.id || "").concat((ci.slow_tests || []).map((t) => t.id)).filter(Boolean),
  [...(ci.jobs || []).map((j) => `${wfName(j.workflow)} / ${j.job}`), ...(ci.tests || []).map((t) => t.suite || "")]);
export function useRunner(app: AppJson, ci: CiJson): { runner: RunnerId | null; tests: string | null } {
  const c = useStore(choice);
  const guess = useMemo(() => runnerGuess(ci).runner, [ci]);
  if (c && c.repo === app.repo) return c;
  return { runner: guess, tests: guess ? PRESETS[guess].tests : null };
}

// Every command, for people who want to add them by hand or run them from a laptop, filled in for the runner.
function manual(repo: string, branch: string, r: RunnerId | null, tests: string, extra: string): [string, string, string][] {
  const tail: [string, string, string][] = [
    ["Read any repo's CI from your machine", `stackvitals ci report ${repo} --tests`, "Nothing installed in the repo; read-only."],
    ["Read a GitLab project", "stackvitals ci gitlab group/project", "The same flaky and slow job checks for GitLab pipelines (GITLAB_TOKEN if private)."]];
  if (!r) return tail;
  const p = PRESETS[r], h = byHand(r, extra), g = sq(p.reports);
  return [
    ["Re-run only the failed tests", `stackvitals ci retry --reports ${g} -- ${h.all} --then ${h.failed}`,
      "Inside the same job; a test the data branch calls broken fails the job at once instead of being retried."
        + (p.rerun ? "" : ` ${p.name} can't re-run only failed tests, so the retry runs the same tests again.`)],
    ["Catch a new flaky test before it merges", `stackvitals ci burn-in --base origin/${branch} --times 5 --reports ${g} -- ${h.some}`,
      "Runs the tests a pull request adds or changes several times and fails when one both passes and fails. A known flaky test that passes every repeat is shown as fixed, with the chance it was luck."],
    ["Run only the tests a change can affect", `stackvitals ci impact --base origin/${branch} --tests ${sq(tests)}`,
      'Prints the test files to run, or "all" when a build or settings file changed. Uses the learned map from the data branch.'],
    ["Split tests into even shards", `stackvitals ci shards ${repo} --n 4 --index 1${p.shardFlags ? " " + p.shardFlags : ""}${["pytest", "jest", "vitest", "playwright"].includes(r) ? ` --files ${sq(tests)}` : ""}`,
      "By the times recorded on the default branch; one shard per matrix job."],
    ["Check test reports before CI does", `stackvitals ci validate ${g}`, "Read as the Action reads them; warns about missing file names, durations or counts that don't add up."],
    ["Skip quarantined tests", `stackvitals ci quarantine --reports ${g} -- ${h.all}`, "Passes when only quarantined (known flaky) tests failed."],
    ...tail];
}

function tokenLink(repo: string): string {
  const q = new URLSearchParams({ name: "StackVitals tests", description: `Lets the StackVitals app open one pull request in ${repo}`,
    target_name: repo.split("/")[0]!, expires_in: "7", contents: "write", workflows: "write", pull_requests: "write" });
  return `https://github.com/settings/personal-access-tokens/new?${q}`;
}

export function CiSetup({ app, ci }: { app: AppJson; ci: CiJson }) {
  const c = ci as R;
  const branch = app.default_branch || "main";
  const jobs = (ci.jobs || []).map((j) => ({ name: `${wfName(j.workflow)} / ${j.job}`, min: (j.median_s || 0) / 60 }));
  const testJobs = jobs.filter((j) => TESTISH.test(j.name));
  const guess = useMemo(() => runnerGuess(ci), [ci]);
  const slowest = testJobs.reduce((a, j) => Math.max(a, j.min), 0) || null;
  const flaky = [...(ci.tests || []), ...(ci.jobs || [])].filter((x) => x.state === "flaky").length;
  const flakyTests = (ci.tests || []).filter((x) => x.state === "flaky").length;
  const imp = c.impact as R | null | undefined;

  const [runner, setRunner] = useState<RunnerId | "">(guess.runner || "");
  const [features, setFeatures] = useState<Feature[]>(() => FEATURES.filter((f) => ({
    retry: true, validate: true, quarantine: flaky > 0, burnin: flakyTests > 0, impact: (imp?.recall ?? 0) >= 0.9, shards: (slowest ?? 0) >= 10 }[f])));
  const [edits, setEdits] = useState<{ install?: string; tests?: string }>({});
  const [extra, setExtra] = useState("");
  const [shards, setShards] = useState(suggestShards(slowest));
  const [times, setTimes] = useState(5);
  const asked = useStore(wanted);
  useEffect(() => { if (asked) setFeatures((fs) => (fs.includes(asked) ? fs : FEATURES.filter((f) => f === asked || fs.includes(f)))); }, [asked]);

  const p = runner ? PRESETS[runner] : null;
  const o: Options | null = p ? { repo: app.repo, branch, runner: runner as RunnerId, features, install: edits.install ?? p.install, tests: edits.tests ?? p.tests,
    extra, shards, times } : null;
  const tests = edits.tests ?? (p ? p.tests : "");
  useEffect(() => { choice.set({ repo: app.repo, runner: runner || null, tests: runner ? tests : null }); }, [app.repo, runner, tests]);
  const yaml = o ? testWorkflow(o) : "";
  const hand = runner ? byHand(runner, extra) : null, sc = hand?.script && runner ? scripts(runner, extra, true) : null;
  const link = o ? fileLink(o) : null;
  const toggle = (f: Feature, on: boolean) => setFeatures(FEATURES.filter((x) => (x === f ? on : features.includes(x))));
  const hint: Record<Feature, string | null> = {
    retry: flaky ? `${flaky} flaky test${flaky === 1 ? "" : "s or jobs"} here in the last ${ci.window_days ?? 30} days.` : null,
    burnin: flakyTests ? `${flakyTests} flaky test${flakyTests === 1 ? "" : "s"} got in already; this stops the next one at the pull request.` : null,
    impact: imp?.failures ? `On ${imp.prs} past pull requests it would have run ${imp.caught} of ${imp.failures} real failures and skipped ${Math.round((imp.skipped_share ?? 0) * 100)}% of test files.`
      : "Not measured here yet: treat it as a fast first pass until the replay below shows it catches real failures.",
    shards: slowest ? `The slowest test job takes about ${Math.round(slowest)} minutes.` : null,
    quarantine: flaky ? "Tests someone quarantines (Decide, or /stackvitals quarantine) stop failing builds at once." : null,
    validate: ci.has_test_reports ? null : "No test reports were read here yet; this step says why.",
  };

  return <div class="ci-setup">
    <div class="ci-setup-strip"><span>Workflow builder</span><span>{app.repo} · {branch}</span></div>
    <div class="ci-setup-form form">
      <Field label="1. Test runner" hint={guess.runner ? <>Guessed from {[guess.ids.length ? `test names like ${guess.ids[0]}` : "", guess.names.length ? `job names like ${guess.names[0]}` : ""].filter(Boolean).join(" and ")}. Change it if that's wrong.</>
        : "This repo's data doesn't say which runner it uses, so pick it."}>{(fid) =>
        <Select id={fid} value={runner} onChange={(v) => { setRunner(v); setEdits({}); }}
          options={[...(runner ? [] : [{ value: "" as const, label: "Pick your test runner" }]), ...RUNNERS.map((r) => ({ value: r, label: `${PRESETS[r].name} (${PRESETS[r].lang})` }))]} />}</Field>
      {!guess.runner ? <p class="ci-say"><span class="sv-mark sv-mark-watch" aria-hidden="true" />Couldn't tell the runner from the test or job names here.</p> : null}

      <fieldset class="ci-feats">
        <legend class="field-label">2. What it should do</legend>
        {FEATURES.map((f) => {
          const lid = `ci-feat-${f}`;
          return <div class={"ci-feat" + (features.includes(f) ? " is-on" : "")}>
            <Toggle checked={features.includes(f)} onChange={(v) => toggle(f, v)} labelledBy={lid} />
            <div class="ci-feat-text"><b id={lid}>{BENEFIT[f][0]}</b><span>{BENEFIT[f][1]}</span>{hint[f] ? <small>{hint[f]}</small> : null}</div>
          </div>;
        })}
      </fieldset>

      {p ? <>
        <p class="field-label ci-step">3. Details</p>
        <Field label="Install dependencies" hint="A first guess at how this repo installs what its tests need; change it if yours differs.">{(fid) => <TextInput id={fid} mono value={edits.install ?? p.install} onInput={(v) => setEdits({ ...edits, install: v })} placeholder="Nothing to install first" />}</Field>
        {features.includes("impact") || features.includes("shards") ? <Field label="Test files" hint="A glob of this repo's test files; test impact and shards place them.">{(fid) =>
          <TextInput id={fid} mono value={edits.tests ?? p.tests} onInput={(v) => setEdits({ ...edits, tests: v })} />}</Field> : null}
        <Field label="Extra test arguments" hint={`Added to every ${p.name} run, for example a config file or a project.`}>{(fid) => <TextInput id={fid} mono value={extra} onInput={setExtra} placeholder="None" />}</Field>
        <div class="ci-steppers">
          {features.includes("shards") ? <div class="field"><span class="field-label">Shards</span><Stepper label="Shards" value={shards} onChange={setShards} min={2} max={16} />
            <p class="field-hint">{slowest ? "Suggested from the slowest test job: about one per five minutes." : "Two to start; more once times are recorded."}</p></div> : null}
          {features.includes("burnin") ? <div class="field"><span class="field-label">Burn-in runs</span><Stepper label="Burn-in runs" value={times} onChange={setTimes} min={2} max={20} />
            <p class="field-hint">How many times new and changed tests run on a pull request.</p></div> : null}
        </div>
      </> : null}
      {testJobs.length ? <div class="ci-jobs-now">
        <p class="field-label">Your test jobs now</p>
        <ul>{testJobs.slice(0, 6).map((j) => <li><code>{j.name}</code>{j.min ? <span class="muted"> about {Math.round(j.min)} min</span> : null}</li>)}</ul>
      </div> : null}
    </div>

    <div class="ci-setup-out">
      {o && p ? <>
        <p class="ci-setup-h">What you get</p>
        <Facts rows={[["File", <code>{TEST_FILE}</code>], ["Workflow", TEST_WORKFLOW], ["Runs on", `pushes to ${branch}, pull requests, and by hand`],
          ["Test reports", <><code>{p.reports}</code>, kept as test-results artifacts for StackVitals</>],
          ["Turned on", features.length ? features.map((f) => BENEFIT[f][0]).join(", ") : "Nothing extra: runs the tests and keeps their reports"]]} />
        {link ? <AddIt app={app} branch={branch} yaml={yaml} link={link} /> : null}
        <details class="ci-yaml">
          <summary>Show the file ({yaml.split("\n").length - 1} lines)</summary>
          <CodeBlock title={TEST_FILE} code={yaml} />
        </details>
        <Framed title="What you still do">
          <ul class="ci-todo">
            <li><b>Review and merge it.</b> Nothing reaches your default branch until you press Commit or merge the pull request.</li>
            <li><b>Check the runner details.</b> {p.check}</li>
            {testJobs.length ? <li><b>Retire the old test job</b> ({testJobs.slice(0, 2).map((j) => j.name).join(", ")}) once this one is green, so tests don't run twice.</li> : null}
            <li><b>Read it right away.</b> Add "{TEST_WORKFLOW}" to the workflows list at the top of <code>.github/workflows/stackvitals.yml</code>, so StackVitals reads each run as it ends.</li>
          </ul>
        </Framed>
      </> : <p class="ci-say"><span class="sv-mark sv-mark-neutral" aria-hidden="true" />Pick the test runner to see the workflow file.</p>}
      <details class="ci-manual">
        <summary>The commands one by one, for a workflow you keep yourself or for your machine</summary>
        <p class="muted small">Install with pip install stackvitals (or uv tool install stackvitals), then{p ? `, for ${p.name}` : ""}:</p>
        {!p ? <p class="ci-say"><span class="sv-mark sv-mark-neutral" aria-hidden="true" />Pick the test runner above to fill in the test commands.</p> : null}
        <div class="ci-manual-list">{manual(app.repo, branch, runner || null, tests, extra).map(([t, code, note]) => <div><h4>{t}</h4><CodeBlock inline code={code} note={note} /></div>)}
          {sc && p ? <div><h4>The run-tests script</h4><CodeBlock title="run-tests" code={sc.run.join("\n") + "\n"} note={`Save it as run-tests on your PATH (the workflow writes the same): it turns test files into what ${p.name} takes.`} /></div> : null}
          {sc?.rerun && p ? <div><h4>The rerun-failed script</h4><CodeBlock title="rerun-failed" code={sc.rerun.join("\n") + "\n"} note="Save it as rerun-failed next to run-tests; it runs only what failed last time." /></div> : null}</div>
      </details>
    </div>
  </div>;
}

// The two one-click paths and a copy.
function AddIt({ app, branch, yaml, link }: { app: AppJson; branch: string; yaml: string; link: PrefillLink & { comments: boolean } }) {
  const acc = useStore(account);
  const [step, setStep] = useState<"idle" | "token" | "sending" | "done" | "error">("idle");
  const [draft, setDraft] = useState("");
  const [pasted, setPasted] = useState<string | null>(null);
  const [pr, setPr] = useState<{ number: number; url: string } | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { if (step === "done" || step === "error") setStep("idle"); }, [yaml]);
  const open = async (tok?: string | null) => {
    const token = tok || pasted || (acc ? await writeToken(app) : undefined);
    if (!token) { setStep("token"); return; }
    setStep("sending");
    try {
      const made = await filePr(makeApi(token), { repo: app.repo, base: branch, branch: TEST_BRANCH, file: TEST_FILE, content: yaml,
        message: "Run the tests with StackVitals", title: "Run the tests with StackVitals",
        body: `Adds \`${TEST_FILE}\`, made in the StackVitals app (CI Health, Set up in your CI). Review it: the tests run on this pull request first, and merging turns it on for ${branch}.` });
      setPr(made); setStep("done");
      toast(`Pull request #${made.number} is open`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e)); setStep("error");
    }
  };
  return <div class="ci-add">
    <div class="ci-add-paths">
      <div class="ci-add-path">
        <p class="ci-add-k">No token needed</p>
        <Button variant="filled" href={link.url} external iconEnd="external" onClick={onPrefill(link, "GitHub opened with the file: press Commit changes there")}>Open it on GitHub</Button>
        <p class="ci-add-note">{link.paste ? <>{PASTE_FILE_BEFORE} It lands on {branch}, or on a new branch you pick there, which opens a pull request.</>
          : <>GitHub's editor opens with the file filled in{link.comments ? "" : " (comments left out so the link fits; Copy the file has them)"}. Press <b>Commit changes</b>: commit it to {branch}, or pick a new branch to open a pull request.</>}</p>
      </div>
      <div class="ci-add-path">
        <p class="ci-add-k">With a token that can write</p>
        <Button variant="tinted" icon="prs" loading={step === "sending"} onClick={() => open()}>Open the pull request for me</Button>
        <p class="ci-add-note">Makes the branch {TEST_BRANCH}, commits the file there and opens a pull request{acc ? ` as ${acc.login || "you"}` : ""}. You review and merge it; nothing lands on {branch} by itself.</p>
      </div>
    </div>
    {step === "token" ? <div class="ci-token">
      <p>Paste a fine-grained token for <b>{app.repo}</b> with <b>Contents</b>, <b>Workflows</b> and <b>Pull requests</b> set to read and write
        (<a href={tokenLink(app.repo)} target="_blank" rel="noopener noreferrer">make one, 7 days</a>). It stays in this page's memory and goes only to api.github.com.</p>
      <div class="inline-form">
        <TextInput type="password" mono value={draft} onInput={(v) => setDraft(v.trim())} placeholder="github_pat_…" label="Fine-grained GitHub token" />
        <Button variant="filled" disabled={!draft} onClick={() => { setPasted(draft); const t = draft; setDraft(""); open(t); }}>Use it</Button>
      </div>
    </div> : null}
    <div role="status">{step === "done" && pr ? <p class="note note-good"><Icon name="check" /><span>Pull request <a href={pr.url} target="_blank" rel="noopener noreferrer">#{pr.number}</a> is open.
      Its checks run the new workflow first; merge it when they pass.</span></p> : null}</div>
    <div role="alert">{step === "error" ? <p class="note note-bad"><Icon name="warn" /><span>Not opened: {error} The token needs Contents, Workflows and Pull requests
      (read and write) on {app.repo}; the GitHub link works without one.</span></p> : null}</div>
    <div class="ci-add-more"><CopyButton text={yaml} label="Copy the file" /><span class="ci-add-save">Save it as <code>{TEST_FILE}</code></span></div>
  </div>;
}

