// Workflow text for the Dependencies page: the code scanning upload (its own file, run after each StackVitals run) and the
// steps that fill the "Your code" column (imports for Python, JavaScript and Rust; govulncheck for Go). No UI here.
import { SETUP_GO, installSteps } from "../../github/workflow";

export const SCAN_FILE = ".github/workflows/stackvitals-code-scanning.yml";
export const SCAN_BRANCH = "stackvitals-code-scanning";

const CHECKOUT = "actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4";
const UPLOAD = "github/codeql-action/upload-sarif@v4";

// A YAML double-quoted string.
const q = (s: string) => JSON.stringify(s);

// Uploads docs/vulns.sarif and docs/security.sarif from the stackvitals-data branch, against the default branch's commit.
export function scanningWorkflow(repo: string, workflowName = "StackVitals"): string {
  const upload = (name: string, file: string, category: string) => [
    `      - name: ${name}`,
    `        if: hashFiles('stackvitals-data/docs/${file}') != ''`,
    `        uses: ${UPLOAD}`,
    "        with:",
    `          sarif_file: stackvitals-data/docs/${file}`,
    `          category: ${category}`,
    "          ref: refs/heads/${{ github.event.repository.default_branch }}",
    "          sha: ${{ github.sha }}"];
  return [
    `# Made in the StackVitals app (Dependencies, "GitHub's Security tab") for ${repo}.`,
    "# After each StackVitals run, uploads its findings to code scanning: known vulnerabilities in every lockfile",
    "# (vulns.sarif) and the weekly security checks (security.sarif), read from the stackvitals-data branch.",
    "name: StackVitals code scanning",
    "on:",
    "  workflow_run:",
    `    workflows: [${q(workflowName)}]`,
    "    types: [completed]",
    "  workflow_dispatch:",
    "permissions:",
    "  contents: read          # reads the stackvitals-data branch",
    "  security-events: write  # uploads the results to code scanning",
    "jobs:",
    "  upload:",
    "    # Runs on the default branch's data only: not after the dependency check on a pull request.",
    "    if: >-",
    "      github.event_name == 'workflow_dispatch' ||",
    "      (github.event.workflow_run.conclusion == 'success' && github.event.workflow_run.event != 'pull_request')",
    "    runs-on: ubuntu-latest",
    "    steps:",
    `      - uses: ${CHECKOUT}`,
    "        with:",
    "          ref: stackvitals-data",
    "          path: stackvitals-data",
    "          persist-credentials: false",
    ...upload("Known vulnerabilities", "vulns.sarif", "stackvitals-vulns"),
    ...upload("Security checks", "security.sarif", "stackvitals-security"),
  ].join("\n") + "\n";
}

export type CodeTool = "imports" | "govulncheck";

// The steps to add before the StackVitals step, and the input that passes their file on.
export function yourCodeSteps(tool: CodeTool): { steps: string; input: string } {
  const checkout = [`      - uses: ${CHECKOUT}`, "        with:", "          persist-credentials: false"];
  if (tool === "govulncheck") return { input: "          govulncheck-json: govulncheck.json", steps: [...checkout,
    `      - uses: ${SETUP_GO}`,
    "        with:",
    "          go-version-file: go.mod",
    "      - name: Which advisories your code calls",
    "        run: |",
    "          go install golang.org/x/vuln/cmd/govulncheck@latest",
    "          govulncheck -format json ./... > govulncheck.json || true"].join("\n") + "\n" };
  return { input: "          imports-json: imports.json", steps: [...checkout, ...installSteps(6),
    "      - name: Which packages your code imports",
    "        run: stackvitals deps imports . --out imports.json"].join("\n") + "\n" };
}

// GitHub's editor on an existing file of the default branch.
export function editLink(repo: string, branch: string, file: string): string {
  return `https://github.com/${repo}/edit/${encodeURIComponent(branch)}/${file.split("/").map(encodeURIComponent).join("/")}`;
}
