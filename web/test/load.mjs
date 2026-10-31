// Bundles app modules with the app's own esbuild settings and imports them, so node:test can run TypeScript sources.
// One entry gives that module; a list gives one bundle (shared state) with each module as m0, m1, ...
import { createRequire } from "node:module";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

// npm test runs a bundled copy from a temp folder and says where the repo is.
export const web = process.env.SV_REPO_ROOT ? join(process.env.SV_REPO_ROOT, "web") : resolve(dirname(fileURLToPath(import.meta.url)), "..");

export async function load(entry) {
  // Browser globals some modules read when they load.
  globalThis.location ??= { search: "", href: "http://127.0.0.1/", hostname: "127.0.0.1", hash: "" };
  globalThis.self ??= globalThis;
  // esbuild from web/node_modules, wherever this file runs from.
  const esbuild = createRequire(join(web, "package.json"))("esbuild");
  const many = Array.isArray(entry);
  const out = await esbuild.build({
    absWorkingDir: web, bundle: true, format: "esm", platform: "browser", target: "es2020", write: false,
    ...(many ? { stdin: { contents: entry.map((e, i) => `export * as m${i} from "./${e}";`).join("\n"), resolveDir: web, loader: "ts" } } : { entryPoints: [entry] }),
    jsx: "automatic", jsxImportSource: "preact", logLevel: "silent", define: { __SV_AUTH__: "{}" },
    alias: { tweetnacl: "./node_modules/tweetnacl/nacl.min.js" },
  });
  const file = join(mkdtempSync(join(tmpdir(), "sv-web-")), "mod.mjs");
  writeFileSync(file, out.outputFiles[0].text);
  return import(pathToFileURL(file).href);
}
