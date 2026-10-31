// The "Set up in your CI" workflow: one GitHub Actions file that runs a repo's tests with the stackvitals ci commands
// (retry, burn-in, impact, shards, quarantine, validate), plus the runner guess from what data.json knows. No UI here.
import { newFile, type PrefillLink } from "../../github/links";
import { SETUP_GO, installSteps, pyJson } from "../../github/workflow";

export const TEST_FILE = ".github/workflows/stackvitals-tests.yml";
export const TEST_WORKFLOW = "Tests (StackVitals)";
export const TEST_BRANCH = "stackvitals-tests";

export const FEATURES = ["retry", "burnin", "impact", "shards", "quarantine", "validate"] as const;
export type Feature = (typeof FEATURES)[number];
export const RUNNERS = ["pytest", "jest", "vitest", "go", "maven", "gradle", "dotnet", "rspec", "playwright"] as const;
export type RunnerId = (typeof RUNNERS)[number];

// Pinned to full commit SHAs like the repo's own workflows.
const CHECKOUT = "actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09 # v5.1.0";
const SETUP_PY = "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1 # v6.3.0";
const SETUP_NODE = "actions/setup-node@a0853c24544627f65ddf259abe73b1d18a591444 # v5.0.0";
const SETUP_JAVA = "actions/setup-java@b843ebf9b913146b38da2eaa7aeddf76074ae1ad # v6.1.0";
const SETUP_DOTNET = "actions/setup-dotnet@a98b56852c35b8e3190ac28c8c2271da59106c68 # v6.0.0";
const SETUP_RUBY = "ruby/setup-ruby@7f797815d8adceb1c412e7abefdd1ab4abc47a5f # v1.335.0";
const UPLOAD = "actions/upload-artifact@b7c566a772e6b6bfb58ed0dc250532a479d7789f # v6.0.0";

export interface Runner {
  id: RunnerId; name: string; lang: string;
  setup: string[];            // the language setup step(s), as YAML lines at step level
  install: string;            // a first guess at installing dependencies; people can change it
  reports: string;            // where the runner writes its test reports (a glob)
  tests: string;              // the repo's test files (a glob), for test impact and shards
  run: string[];              // bash: run "$@" (test files or classes), or everything with none; write the report
  rerun: string[] | null;     // bash: run only what failed last time, or null when the runner can't
  shardFlags: string;         // extra stackvitals ci shards flags
  check: string;              // what to look at before merging, in plain words
}

const NODE = [`- uses: ${SETUP_NODE}`, "  with:", "    node-version: 22", "    cache: npm"];
const JAVA = (cache: string) => [`- uses: ${SETUP_JAVA}`, "  with:", "    distribution: temurin", "    java-version: 21", `    cache: ${cache}`];
// A file path keeps only its class name (FooTest); a class from the recorded times (com.acme.FooTest) stays whole.
const CLASS_NAME = 'case "$a" in */*|*.java|*.kt|*.cs) b=$(basename "$a"); n="${b%.*}" ;; *) n="$a" ;; esac';

export const PRESETS: Record<RunnerId, Runner> = {
  pytest: { id: "pytest", name: "pytest", lang: "Python",
    setup: [`- uses: ${SETUP_PY}`, "  with:", '    python-version: "3.12"', "    cache: pip"],
    install: "if [ -f requirements.txt ]; then pip install -r requirements.txt; else pip install -e .; fi; pip install pytest",
    reports: "reports/*.xml", tests: "tests/**/test_*.py",
    run: ['pytest "$@" --junitxml=reports/junit.xml{X}'], rerun: ["pytest --lf --junitxml=reports/junit.xml{X}"], shardFlags: "--py-paths",
    check: "The install line: requirements.txt if there is one, else the package itself." },
  jest: { id: "jest", name: "Jest", lang: "JavaScript", setup: NODE, install: "npm ci",
    reports: "reports/*.json", tests: "src/**/*.test.*",
    run: ['npx jest --ci --json --outputFile=reports/jest.json{X} "$@"'], rerun: ["npx jest --ci --onlyFailures --json --outputFile=reports/jest.json{X}"], shardFlags: "",
    check: "npm ci needs a package-lock.json; change it for yarn or pnpm." },
  vitest: { id: "vitest", name: "Vitest", lang: "JavaScript", setup: NODE, install: "npm ci",
    reports: "reports/*.xml", tests: "src/**/*.test.*",
    run: ['npx vitest run --reporter=default --reporter=junit --outputFile.junit=reports/vitest.xml{X} "$@"'], rerun: null, shardFlags: "",
    check: "npm ci needs a package-lock.json; change it for yarn or pnpm. Vitest can't re-run only failed tests, so a retry runs the same tests again." },
  go: { id: "go", name: "go test", lang: "Go",
    setup: [`- uses: ${SETUP_GO}`, "  with:", "    go-version-file: go.mod"], install: "go mod download",
    reports: "reports/*.json", tests: "**/*_test.go",
    run: [
      "pkgs=()",
      'for a in "$@"; do case "$a" in *.go) pkgs+=("./$(dirname "$a")") ;; *) pkgs+=("$a") ;; esac; done',
      '[ ${#pkgs[@]} -gt 0 ] || pkgs=(./...)',
      `go test -count=1 -json{X} $(printf '%s\\n' "\${pkgs[@]}" | sort -u) > reports/go.json || { grep '"Action":"fail"' reports/go.json || true; exit 1; }`],
    rerun: [
      `tests=$(grep '"Action":"fail"' reports/go.json | grep -o '"Test":"[^"/]*' | cut -d'"' -f4 | sort -u | paste -sd'|' -)`,
      `pkgs=$(grep '"Action":"fail"' reports/go.json | grep '"Test":' | grep -o '"Package":"[^"]*' | cut -d'"' -f4 | sort -u)`,
      '[ -n "$tests" ] || exit 1',
      `go test -count=1 -json{X} -run "^($tests)$" $pkgs > reports/go.json || { grep '"Action":"fail"' reports/go.json || true; exit 1; }`],
    shardFlags: "", check: "Test results go to reports/go.json; failures are printed in the log." },
  maven: { id: "maven", name: "Maven (Surefire)", lang: "Java or Kotlin", setup: JAVA("maven"), install: "",
    reports: "**/target/surefire-reports/*.xml", tests: "**/src/test/**/*Test.*",
    run: ["names=()", 'for a in "$@"; do ' + CLASS_NAME + '; names+=("$n"); done',
      'if [ ${#names[@]} -gt 0 ]; then set -- "-Dtest=$(IFS=,; echo "${names[*]}")" -Dsurefire.failIfNoSpecifiedTests=false; fi',
      'mvn -B test{X} "$@"'],
    rerun: null, shardFlags: "", check: "Java 21: change java-version if the project needs another. Maven can't re-run only failed tests, so a retry runs the same tests again." },
  gradle: { id: "gradle", name: "Gradle", lang: "Java or Kotlin", setup: JAVA("gradle"), install: "",
    reports: "**/build/test-results/test/*.xml", tests: "**/src/test/**/*Test.*",
    run: ["args=()", 'for a in "$@"; do ' + CLASS_NAME + '; args+=(--tests "$n"); done', './gradlew test --continue{X} "${args[@]}"'],
    rerun: null, shardFlags: "", check: "Uses ./gradlew test; an Android project may want testDebugUnitTest. Gradle can't re-run only failed tests, so a retry runs the same tests again." },
  dotnet: { id: "dotnet", name: "dotnet test", lang: "C#", setup: [`- uses: ${SETUP_DOTNET}`, "  with:", "    dotnet-version: 10.0.x"], install: "dotnet restore",
    reports: "reports/*.trx", tests: "**/*Tests.cs",
    run: ['filter=""', 'for a in "$@"; do ' + CLASS_NAME + '; filter="${filter:+$filter|}FullyQualifiedName~$n"; done',
      'if [ -n "$filter" ]; then set -- --filter "$filter"; fi', 'dotnet test --logger trx --results-directory reports{X} "$@"'],
    rerun: null, shardFlags: "", check: "The .NET 10 SDK builds older targets too. dotnet test can't re-run only failed tests, so a retry runs the same tests again." },
  rspec: { id: "rspec", name: "RSpec", lang: "Ruby", setup: [`- uses: ${SETUP_RUBY}`, "  with:", "    bundler-cache: true"], install: "",
    reports: "reports/*.xml", tests: "spec/**/*_spec.rb",
    run: ["mkdir -p tmp", `echo 'RSpec.configure { |c| c.example_status_persistence_file_path = "tmp/rspec-status.txt" }' > "$RUNNER_TEMP/sv_rspec.rb"`,
      "paths=()", 'for a in "$@"; do case "$a" in */*|*.rb) paths+=("$a") ;; *) paths+=("$(echo "$a" | tr . /).rb") ;; esac; done',
      'bundle exec rspec --require "$RUNNER_TEMP/sv_rspec.rb" --format progress --format RspecJunitFormatter --out reports/rspec.xml{X} "${paths[@]}"'],
    rerun: ['bundle exec rspec --require "$RUNNER_TEMP/sv_rspec.rb" --only-failures --format progress --format RspecJunitFormatter --out reports/rspec.xml{X}'],
    shardFlags: "", check: "The Gemfile needs rspec_junit_formatter (it writes the report); Ruby comes from .ruby-version." },
  playwright: { id: "playwright", name: "Playwright", lang: "JavaScript", setup: NODE, install: "npm ci && npx playwright install --with-deps",
    reports: "reports/*.xml", tests: "tests/**/*.spec.*",
    run: ['PLAYWRIGHT_JUNIT_OUTPUT_NAME=reports/playwright.xml npx playwright test --reporter=line,junit{X} "$@"'],
    rerun: ["PLAYWRIGHT_JUNIT_OUTPUT_NAME=reports/playwright.xml npx playwright test --last-failed --reporter=line,junit{X}"], shardFlags: "",
    check: "npm ci needs a package-lock.json; the browsers install on each run." },
};

// What each choice does, in one sentence each (also the workflow's header comments).
export const BENEFIT: Record<Feature, [string, string]> = {
  retry: ["Re-run only failed tests", "When tests fail, only those run again in the same job, so one flake doesn't fail the build; a test StackVitals knows is broken fails at once."],
  burnin: ["Catch new flaky tests on pull requests", "Runs the tests a pull request adds or changes several times and fails if one both passes and fails, before it merges."],
  impact: ["Run only affected tests on pull requests", "Runs only the test files a change can affect, learned from this repo's own history; build or settings changes run everything."],
  shards: ["Split into even shards", "Splits the tests into parallel jobs by their recorded times, so every shard ends at about the same time."],
  quarantine: ["Skip quarantined tests", "Known flaky tests on the quarantine list still run and report, but can't fail the build."],
  validate: ["Check the test reports", "Reads each report the way StackVitals does and warns about missing names, times or counts; it never fails the build."],
};

export interface Options {
  repo: string; branch: string; runner: RunnerId; features: Feature[]; install: string; tests: string; extra: string;
  shards: number; times: number; comments?: boolean;
}

const has = (o: Options, f: Feature) => o.features.includes(f);
// A shell word in single quotes (globs reach stackvitals unexpanded).
export const sq = (s: string) => `'${s.replace(/'/g, `'\\''`)}'`;
const runLines = (body: string[], extra: string) => body.map((l) => l.replace("{X}", extra.trim() ? " " + extra.trim() : ""));

// The bodies of the run-tests and rerun-failed scripts the workflow writes (rerun-failed is null when the runner can't).
// `hand` is for a laptop, where RUNNER_TEMP isn't set.
export function scripts(r: RunnerId, extra = "", hand = false): { run: string[]; rerun: string[] | null } {
  const p = PRESETS[r], temp = hand && [...p.run, ...(p.rerun || [])].some((l) => l.includes("RUNNER_TEMP"));
  const head = ["#!/usr/bin/env bash", "set -eu", ...(temp ? ['RUNNER_TEMP="${RUNNER_TEMP:-${TMPDIR:-/tmp}}"'] : []), "mkdir -p reports"];
  return { run: [...head, ...runLines(p.run, extra)], rerun: p.rerun ? [...head, ...runLines(p.rerun, extra)] : null };
}

// The runner's own commands to type by hand ({files} where the test files go); runners that turn files into packages
// or classes, or need a setup line, use the run-tests and rerun-failed scripts instead.
export function byHand(r: RunnerId, extra = ""): { all: string; some: string; failed: string; script: boolean } {
  const p = PRESETS[r];
  if (p.run.length !== 1) return { all: "run-tests", some: "run-tests {files}", failed: p.rerun ? "rerun-failed" : "run-tests", script: true };
  const line = runLines(p.run, extra)[0]!;
  return { all: line.replace(/ ?"\$@"/, ""), some: line.replace('"$@"', "{files}"), failed: p.rerun ? runLines(p.rerun, extra)[0]! : line.replace(/ ?"\$@"/, ""), script: false };
}

// The stackvitals ci command lines the workflow runs, also listed for people who want them one by one.
export function commands(o: Options): { test: string; burnin: string; validate: string; pick: string[] } {
  const p = PRESETS[o.runner], g = sq(p.reports);
  const files = has(o, "impact") || has(o, "shards") ? "run-tests $FILES" : "run-tests";
  let test = files;
  if (has(o, "retry")) test = `stackvitals ci retry --reports ${g} -- ${test} --then ${p.rerun ? "rerun-failed" : files}`;
  if (has(o, "quarantine")) test = `stackvitals ci quarantine --reports ${g} -- ${test}`;
  const pick: string[] = [];
  if (has(o, "impact")) pick.push(`stackvitals ci impact --base "origin/$BASE" --tests ${sq(o.tests)}`);
  if (has(o, "shards")) pick.push(`stackvitals ci shards "$GITHUB_REPOSITORY" --n ${o.shards} --index "$SHARD"${p.shardFlags ? " " + p.shardFlags : ""}`
    + (["pytest", "jest", "vitest", "playwright"].includes(o.runner) ? ` --files ${sq(o.tests)}` : ""));
  return { test, pick, burnin: `stackvitals ci burn-in --base "origin/$BASE" --times ${o.times} --reports ${g} -- run-tests {files}`,
    validate: `stackvitals ci validate ${g}` };
}

// The whole workflow file. `comments: false` leaves every comment out.
export function testWorkflow(o: Options): string {
  const p = PRESETS[o.runner], c = o.comments !== false;
  const out: string[] = [];
  const add = (indent: number, line: string, note?: string) => out.push(" ".repeat(indent) + line + (c && note ? `   # ${note}` : ""));
  const say = (indent: number, text: string) => { if (c) out.push(" ".repeat(indent) + "# " + text); };
  const block = (indent: number, lines: string[]) => { for (const l of lines) out.push(l ? " ".repeat(indent) + l : ""); };
  const uses = (indent: number, ref: string) => add(indent, "- uses: " + (c ? ref : ref.split(" # ")[0]!));
  const cmd = commands(o);
  const sv = o.features.length > 0;
  const deep = has(o, "burnin") || has(o, "impact");
  const learned = has(o, "retry") || has(o, "burnin") || has(o, "impact");
  const shard = has(o, "shards") ? Math.max(2, Math.min(16, Math.round(o.shards))) : 0;
  const picking = has(o, "impact") || shard > 0;

  if (c) {
    out.push(`# Made in the StackVitals app (CI Health, "Set up in your CI") for ${o.repo}: runs your tests with ${p.name}`);
    out.push("# and keeps the test reports, so StackVitals can tell flaky tests from real failures.");
    for (const f of FEATURES) if (has(o, f)) out.push(`#   ${BENEFIT[f][0]}: ${BENEFIT[f][1]}`);
  }
  add(0, `name: ${TEST_WORKFLOW}`);
  add(0, "on:");
  add(2, "push:");
  add(4, `branches: [${pyJson(o.branch)}]`);
  add(2, "pull_request:");
  add(2, "workflow_dispatch:");
  add(0, "permissions:");
  add(2, "contents: read", "check out the code; read the quarantine list on the stackvitals-data branch");
  add(2, "actions: read", "read the test times recorded in earlier runs (shards)");
  add(0, "concurrency:");
  add(2, "group: tests-${{ github.ref }}");
  add(2, "cancel-in-progress: ${{ github.event_name == 'pull_request' }}", "a new push to a pull request stops its older run");
  add(0, "jobs:");

  // The code, what StackVitals learned, the language, the dependencies and the commands.
  const common = () => {
    uses(6, CHECKOUT);
    if (deep) { add(8, "with:"); add(10, "fetch-depth: 0", "the whole history, to compare a pull request with its base"); }
    if (learned) {
      add(6, "- name: Read what StackVitals learned");
      say(8, "Known broken and flaky tests and the learned test map, from the data branch; without it the commands still run.");
      add(8, "run: |");
      add(10, `git fetch --no-tags${deep ? "" : " --depth=1"} origin stackvitals-data:refs/remotes/origin/stackvitals-data || echo "No stackvitals-data branch yet."`);
    }
    for (const [i, l] of p.setup.entries()) add(6, i === 0 ? l.replace(/^- uses: (.*)$/, (_m, r: string) => "- uses: " + (c ? r : r.split(" # ")[0]!)) : l);
    if (o.install.trim()) { add(6, "- name: Install dependencies"); add(8, "run: |"); add(10, o.install.trim()); }
    if (sv) out.push(...installSteps(6, c));
    add(6, "- name: Write the test commands");
    say(8, `run-tests runs the files it is given (all tests with none) and writes ${p.reports}${p.rerun && has(o, "retry") ?"; rerun-failed runs only what failed" : ""}.`);
    add(8, "run: |");
    const sc = scripts(o.runner, o.extra);
    block(10, ['mkdir -p "$RUNNER_TEMP/bin"', "cat > \"$RUNNER_TEMP/bin/run-tests\" <<'EOF'", ...sc.run, "EOF"]);
    if (sc.rerun && has(o, "retry")) block(10, ["cat > \"$RUNNER_TEMP/bin/rerun-failed\" <<'EOF'", ...sc.rerun, "EOF"]);
    block(10, ['chmod +x "$RUNNER_TEMP"/bin/*', 'echo "$RUNNER_TEMP/bin" >> "$GITHUB_PATH"']);
  };

  add(2, "tests:");
  if (shard) {
    add(4, `name: tests (shard \${{ matrix.shard }} of ${shard})`);
    add(4, "strategy:");
    add(6, "fail-fast: false");
    add(6, "matrix:");
    add(8, `shard: [${Array.from({ length: shard }, (_, i) => i + 1).join(", ")}]`);
  }
  add(4, "runs-on: ubuntu-latest");
  add(4, "steps:");
  common();
  if (picking) {
    add(6, "- name: Pick the tests");
    add(8, "id: pick");
    add(8, "env:");
    add(10, "GITHUB_TOKEN: ${{ github.token }}");
    add(10, "EVENT: ${{ github.event_name }}");
    add(10, "BASE: ${{ github.base_ref }}");
    if (shard) add(10, "SHARD: ${{ matrix.shard }}");
    add(8, "run: |");
    const lines = ['files=""', "skip=false"];
    if (has(o, "impact")) lines.push(
      'if [ "$EVENT" = pull_request ]; then',
      `  if picked=$(${cmd.pick[0]}); then`,
      '    if [ -z "$picked" ]; then echo "No test can be affected by this change, so none run."; skip=true',
      '    elif [ "$picked" != all ]; then files="$picked"; fi',
      '  else echo "Test impact could not run; every test runs."; fi',
      "fi");
    if (shard) lines.push(
      'if [ "$skip" = false ] && [ -z "$files" ]; then',
      `  if out=$(${cmd.pick[cmd.pick.length - 1]}); then`,
      '    if [ -n "$out" ]; then files="$out"; else skip=true; fi',
      '  else echo "No recorded test times yet: shard 1 runs every test this time."; [ "$SHARD" = 1 ] || skip=true; fi',
      ...(has(o, "impact") ? ['elif [ -n "$files" ] && [ "$SHARD" != 1 ]; then skip=true'] : []),
      "fi");
    lines.push('echo "files=$files" >> "$GITHUB_OUTPUT"', 'echo "skip=$skip" >> "$GITHUB_OUTPUT"');
    block(10, lines);
  }
  const ran = picking ? "steps.pick.outputs.skip != 'true'" : "";
  add(6, "- name: Run the tests");
  if (ran) add(8, `if: ${ran}`);
  if (picking || has(o, "quarantine")) {
    add(8, "env:");
    if (picking) add(10, "FILES: ${{ steps.pick.outputs.files }}");
    if (has(o, "quarantine")) add(10, "GITHUB_TOKEN: ${{ github.token }}", "reads the quarantine list");
  }
  add(8, "run: |");
  add(10, cmd.test);
  if (has(o, "validate")) {
    add(6, "- name: Check the test reports");
    add(8, `if: always()${ran ? ` && ${ran}` : ""}`);
    add(8, "continue-on-error: true", "a report problem is a warning, never a failed build");
    add(8, "run: |");
    add(10, cmd.validate);
  }
  add(6, "- name: Keep the test reports");
  say(8, "StackVitals reads test reports from artifacts whose name says test-results.");
  add(8, `if: always()${ran ? ` && ${ran}` : ""}`);
  add(8, "uses: " + (c ? UPLOAD : UPLOAD.split(" # ")[0]!));
  add(8, "with:");
  add(10, `name: test-results${shard ? "-${{ matrix.shard }}" : ""}`);
  add(10, `path: ${pyJson(p.reports)}`);
  add(10, "if-no-files-found: ignore");
  add(10, "retention-days: 14");

  if (has(o, "burnin")) {
    add(6, `- name: Run new and changed tests ${o.times} times`);
    say(8, "On pull requests: fails when one of them both passes and fails (after the reports above are kept).");
    add(8, `if: always() && github.event_name == 'pull_request'${shard ? " && matrix.shard == 1" : ""}`);
    add(8, "env:");
    add(10, "BASE: ${{ github.base_ref }}");
    add(8, "run: |");
    add(10, cmd.burnin);
  }
  return out.join("\n") + "\n";
}

// GitHub's editor on the new file: filled in with comments when the link fits, else without them; past that the file name
// only, with the whole commented file to paste. `comments` says whether what lands in GitHub keeps them.
export function fileLink(o: Options): PrefillLink & { comments: boolean } {
  const full = testWorkflow(o), first = newFile(o.repo, o.branch, TEST_FILE, full);
  if (!first.paste) return { ...first, comments: true };
  const bare = newFile(o.repo, o.branch, TEST_FILE, testWorkflow({ ...o, comments: false }), full);
  return { ...bare, comments: !!bare.paste };
}

// The runner guess: test ids weigh most, then job, workflow and report artifact names.
const NAME_HINTS: [RunnerId, RegExp][] = [
  ["pytest", /\bpytest\b|\bpython\b|\btox\b|\bnox\b|\bpy3\d*\b/i], ["vitest", /\bvitest\b/i], ["jest", /\bjest\b/i], ["playwright", /\bplaywright\b/i],
  ["go", /\bgo[- ]?test\b|\bgolang(ci)?\b|\bgotestsum\b/i], ["gradle", /gradle|\bassemble|\bdetekt\b|\bktlint\b|connectedAndroidTest|\bandroid\b/i],
  ["maven", /\bmvn\b|\bmaven\b|\bsurefire\b/i], ["dotnet", /\bdotnet\b|\.net\b|\bxunit\b|\bnunit\b|\bmstest\b/i], ["rspec", /\brspec\b|\bruby\b|\brails\b/i],
];
const ID_HINTS: [RunnerId, RegExp][] = [
  ["pytest", /\.py::|(^|[/.])test_\w+\.py|::test_\w+/], ["go", /^Test[A-Z0-9_]\w*(\/|$)|::Test[A-Z0-9_]\w*(\/|$)/], ["vitest", /\.(test|spec)\.[cm]?[jt]sx? > /],
  ["jest", /\.(test|spec)\.[cm]?[jt]sx?(::| )/], ["playwright", / › /], ["rspec", /_spec\.rb|^\.\/spec\//],
  ["maven", /^([a-z_]\w*\.)+[A-Z]\w*Tests?\.\w+$|^[A-Z]\w*Test\.\w+$/], ["dotnet", /^([A-Z]\w*\.){2,}[A-Z]\w*Tests?\.\w+$/],
];

export interface Guess { runner: RunnerId | null; ids: string[]; names: string[] }

export function guessRunner(testIds: string[], names: string[]): Guess {
  const score: Partial<Record<RunnerId, number>> = {};
  const why: Record<string, { ids: string[]; names: string[] }> = {};
  const hit = (r: RunnerId, n: number, kind: "ids" | "names", text: string) => {
    score[r] = (score[r] || 0) + n;
    const w = (why[r] ||= { ids: [], names: [] });
    if (w[kind].length < 2 && !w[kind].includes(text)) w[kind].push(text);
  };
  for (const id of testIds.slice(0, 200)) for (const [r, rx] of ID_HINTS) if (rx.test(id)) { hit(r, 3, "ids", id); break; }
  for (const n of names) for (const [r, rx] of NAME_HINTS) if (rx.test(n)) hit(r, 2, "names", n);
  // Java-style test names alone can't tell Maven from Gradle: the build's job names decide.
  if (score.maven && (score.gradle || 0) > 0) { score.gradle! += score.maven; why.gradle!.ids = why.maven!.ids; delete score.maven; }
  const best = (Object.entries(score) as [RunnerId, number][]).sort((a, b) => b[1] - a[1])[0];
  if (!best) return { runner: null, ids: [], names: [] };
  return { runner: best[0], ...why[best[0]]! };
}

// A suggested shard count from the slowest test job: about one shard per five minutes, 2 to 8.
export function suggestShards(minutes: number | null): number {
  return minutes ? Math.max(2, Math.min(8, Math.ceil(minutes / 5))) : 2;
}
