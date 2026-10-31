// npm test: bundles test/*.test.ts with esbuild into a temp folder, then runs them with node --test. No network.
import * as esbuild from "esbuild";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const files = readdirSync(here).filter((f) => f.endsWith(".test.ts")).map((f) => join(here, f));
const out = mkdtempSync(join(tmpdir(), "sv-web-test-"));
try {
  await esbuild.build({ entryPoints: files, outdir: out, bundle: true, platform: "node", format: "esm", target: "node20", outExtension: { ".js": ".mjs" },
    jsx: "automatic", jsxImportSource: "preact", logLevel: "warning", define: { __SV_AUTH__: "{}" }, packages: "external", absWorkingDir: join(here, "..") });
  const run = spawnSync(process.execPath, ["--test", ...readdirSync(out).filter((f) => f.endsWith(".mjs")).map((f) => join(out, f))],
    { stdio: "inherit", cwd: join(here, ".."), env: { ...process.env, SV_REPO_ROOT: join(here, "..", "..") } });
  process.exitCode = run.status ?? 1;
} finally {
  rmSync(out, { recursive: true, force: true });
}
