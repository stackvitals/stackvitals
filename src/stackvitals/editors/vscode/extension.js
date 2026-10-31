// Marks flaky and broken tests in the editor, read through the user's own git from the stackvitals-data branch.
"use strict";

const vscode = require("vscode");
const { execFile } = require("child_process");
const path = require("path");
const { findMarks, describe } = require("./marks");

const TEST_FILE = /test|spec/i;
const RELOAD_MS = 30 * 60 * 1000;
const folders = new Map();
let diagnostics;

function git(cwd, args) {
  return new Promise((resolve) => execFile("git", args, { cwd, maxBuffer: 64 << 20, windowsHide: true },
    (err, out) => resolve(err ? null : out)));
}

function ref(folder) {
  const given = vscode.workspace.getConfiguration("stackvitals", folder.uri).get("dataRef");
  // A ref is passed to git, so anything that could read as an option is refused.
  return typeof given === "string" && /^[\w.][\w./-]*$/.test(given) ? given : "origin/stackvitals-data";
}

async function load(folder) {
  const raw = await git(folder.uri.fsPath, ["show", `${ref(folder)}:docs/data.json`]);
  let data = null;
  try {
    data = raw ? JSON.parse(raw) : null;
  } catch {
    data = null; // a half-written or foreign file marks nothing
  }
  const remote = ((await git(folder.uri.fsPath, ["remote", "get-url", "origin"])) || "").trim();
  const repo = (remote.match(/github\.com[:/]([\w.-]+\/[\w.-]+?)(?:\.git)?$/) || [])[1] || null;
  const tests = data && Array.isArray(data.tests) ? data.tests : [];
  folders.set(folder.uri.toString(), { tests, repo });
  return tests.filter((t) => t && (t.state === "flaky" || t.state === "broken")).length;
}

function mark(doc) {
  if (doc.uri.scheme !== "file") return;
  const folder = vscode.workspace.getWorkspaceFolder(doc.uri);
  const known = folder && folders.get(folder.uri.toString());
  const rel = folder ? path.relative(folder.uri.fsPath, doc.uri.fsPath).split(path.sep).join("/") : "";
  if (!known || !TEST_FILE.test(rel)) {
    diagnostics.delete(doc.uri);
    return;
  }
  diagnostics.set(doc.uri, findMarks(doc.getText(), rel, known.tests).map((m) => {
    const range = new vscode.Range(m.line, m.col, m.line, m.col + m.length);
    const d = new vscode.Diagnostic(range, describe(m.test), vscode.DiagnosticSeverity.Warning);
    d.source = "StackVitals";
    const proof = (Array.isArray(m.test.evidence) ? m.test.evidence : []).slice(-1)[0];
    d.code = known.repo && proof && Number.isInteger(proof.run)
      ? { value: "latest evidence", target: vscode.Uri.parse(`https://github.com/${known.repo}/actions/runs/${proof.run}/attempts/${proof.att || 1}`) }
      : m.test.state;
    return d;
  }));
}

async function reload(fetch) {
  let count = 0;
  for (const folder of vscode.workspace.workspaceFolders || []) {
    if (fetch) {
      const [remote, branch] = ref(folder).split(/\/(.+)/);
      // "+": the data branch is squashed now and then, which a plain fetch would refuse.
      await git(folder.uri.fsPath, ["fetch", "--quiet", remote, `+${branch}:refs/remotes/${remote}/${branch}`]);
    }
    count += await load(folder);
  }
  vscode.workspace.textDocuments.forEach(mark);
  return count;
}

function activate(context) {
  diagnostics = vscode.languages.createDiagnosticCollection("stackvitals");
  const timers = new Map();
  const later = (doc) => {
    clearTimeout(timers.get(doc.uri.toString()));
    timers.set(doc.uri.toString(), setTimeout(() => mark(doc), 300));
  };
  const every = setInterval(() => reload(false), RELOAD_MS);
  context.subscriptions.push(
    diagnostics,
    { dispose: () => clearInterval(every) },
    vscode.workspace.onDidOpenTextDocument(mark),
    vscode.workspace.onDidChangeTextDocument((e) => later(e.document)),
    vscode.workspace.onDidCloseTextDocument((doc) => diagnostics.delete(doc.uri)),
    vscode.workspace.onDidChangeWorkspaceFolders(() => reload(false)),
    vscode.commands.registerCommand("stackvitals.refresh", async () => {
      const n = await reload(true);
      vscode.window.showInformationMessage(n ? `StackVitals: ${n} flaky or broken test${n === 1 ? "" : "s"} marked.`
        : "StackVitals: no flaky or broken tests found on the data branch.");
    }),
  );
  reload(false);
}

function deactivate() {}

module.exports = { activate, deactivate };
