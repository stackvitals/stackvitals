// Builds the StackVitals app into src/stackvitals/web/app/ plus index.html beside it.
// Usage: node build.mjs [--watch] [--out <dir>]   (--out writes <dir>/index.html and <dir>/app/)
import * as esbuild from "esbuild";
import { copyFileSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { demoFiles } from "./demo/source.mjs";
import { helpFiles, helpReport } from "./scripts/docs.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const watch = args.includes("--watch");
const outArg = args.indexOf("--out");
const webRoot = outArg >= 0 ? resolve(args[outArg + 1]) : resolve(here, "../src/stackvitals/web");
const out = join(webRoot, "app");
// The app's fonts (Latin; Plex Sans 400 and 600, Condensed 700 for display, Mono 400 for code); main.css names them.
const FONTS = {
  "plex-sans-400.woff2": "@fontsource/ibm-plex-sans/files/ibm-plex-sans-latin-400-normal.woff2",
  "plex-sans-600.woff2": "@fontsource/ibm-plex-sans/files/ibm-plex-sans-latin-600-normal.woff2",
  "plex-sans-condensed-700.woff2": "@fontsource/ibm-plex-sans-condensed/files/ibm-plex-sans-condensed-latin-700-normal.woff2",
  "plex-mono-400.woff2": "@fontsource/ibm-plex-mono/files/ibm-plex-mono-latin-400-normal.woff2",
};

// Sign in with GitHub appears only when a relay is set: SV_RELAY=https://... SV_CLIENT_ID=Iv1... npm run build
const AUTH = { relay: process.env.SV_RELAY || "", clientId: process.env.SV_CLIENT_ID || "" };

const pages = readdirSync(join(here, "src/pages")).filter((f) => f.endsWith(".tsx")).map((f) => `src/pages/${f}`);

const options = {
  absWorkingDir: here,
  entryPoints: ["src/main.tsx", ...pages],
  outdir: out,
  outbase: "src",
  entryNames: "[dir]/[name]",
  chunkNames: "chunks/[name]-[hash]",
  bundle: true,
  splitting: true,
  format: "esm",
  target: "es2020",
  minify: true,
  legalComments: "none",
  jsx: "automatic",
  jsxImportSource: "preact",
  external: ["fonts/*"],
  metafile: true,
  logLevel: "warning",
  define: { "process.env.NODE_ENV": '"production"', __SV_AUTH__: JSON.stringify(AUTH) },
  // The sealed box for saving secrets uses tweetnacl's small build (nacl.min.js), not nacl-fast.
  alias: { tweetnacl: "./node_modules/tweetnacl/nacl.min.js" },
};

const bootOptions = {
  absWorkingDir: here,
  entryPoints: ["src/boot.ts"],
  outfile: join(out, "boot.js"),
  bundle: true,
  format: "iife",
  target: "es2020",
  minify: true,
  legalComments: "none",
  logLevel: "warning",
};

function licences() {
  const read = (p) => readFileSync(join(here, p), "utf8").trim();
  return [
    "# Third-party licences",
    "",
    "The StackVitals app bundles these libraries and fonts. Each keeps its own licence, copied in full below.",
    "",
    "## Preact (MIT)", "", "```", read("node_modules/preact/LICENSE"), "```", "",
    "## uPlot (MIT)", "", "```", read("node_modules/uplot/LICENSE"), "```", "",
    "## IBM Plex Sans (SIL Open Font License 1.1)", "", "```", read("node_modules/@fontsource/ibm-plex-sans/LICENSE"), "```", "",
    "## IBM Plex Sans Condensed (SIL Open Font License 1.1)", "", "```", read("node_modules/@fontsource/ibm-plex-sans-condensed/LICENSE"), "```", "",
    "## IBM Plex Mono (SIL Open Font License 1.1)", "", "```", read("node_modules/@fontsource/ibm-plex-mono/LICENSE"), "```", "",
    "## TweetNaCl.js (Unlicense, public domain)", "", "```", read("node_modules/tweetnacl/LICENSE"), "```", "",
    "## tweetnacl-sealedbox-js (MIT)", "", "```", read("node_modules/tweetnacl-sealedbox-js/LICENSE.txt"), "```", "",
    "## BLAKE2s and BLAKE2b in JavaScript, blakejs (MIT)", "", "```", read("node_modules/blakejs/LICENSE"), "```", "",
  ].join("\n");
}

function page(meta) {
  // Pages that have their own stylesheet, so the router loads it with the page.
  const css = Object.entries(meta.outputs)
    // Route pages only: a lazily loaded part (delivery/more) gets its own copy of shared CSS that the page already has.
    .filter(([, o]) => /^src\/pages\/[^/]+\.tsx$/.test(o.entryPoint || "") && o.cssBundle)
    .map(([, o]) => o.entryPoint.slice("src/pages/".length).replace(/\.tsx$/, ""))
    .sort();
  const main = Object.entries(meta.outputs).find(([, o]) => o.entryPoint === "src/main.tsx");
  const preload = (main?.[1].imports || []).filter((i) => i.kind === "import-statement")
    .map((i) => relative(webRoot, resolve(here, i.path)).replace(/\\/g, "/"));
  let html = readFileSync(join(here, "index.html"), "utf8");
  html = html.replace("<!--PRELOAD-->", preload.map((p) => `<link rel="modulepreload" href="${p}">`).join("\n"));
  html = html.replace("__PAGE_CSS__", css.join(","));
  if (AUTH.relay) html = html.replace("connect-src 'self'", `connect-src 'self' ${new URL(AUTH.relay).origin}`);
  return html;
}

// esbuild also folds CSS reached through import() into main.css, which put every page's styles on the first screen.
// main.css is rebuilt from the stylesheets main.tsx imports statically; each page's own CSS still loads with it.
function firstScreenCss(meta) {
  const seen = new Set(), keep = new Set();
  const walk = (p) => {
    if (seen.has(p)) return;
    seen.add(p);
    for (const i of meta.inputs[p]?.imports || []) {
      if (i.kind === "dynamic-import") continue;
      if (i.path.endsWith(".css") && !p.endsWith(".css")) keep.add(i.path);
      walk(i.path);
    }
  };
  walk("src/main.tsx");
  const main = Object.entries(meta.outputs).find(([k]) => k.endsWith("/main.css") || k === "main.css");
  if (!main) return;
  const order = Object.keys(main[1].inputs).filter((p) => keep.has(p));
  esbuild.buildSync({ absWorkingDir: here, stdin: { contents: order.map((p) => `@import "./${p}";`).join("\n"), resolveDir: here, loader: "css" },
    bundle: true, minify: true, legalComments: "none", target: "es2020", external: ["fonts/*"], outfile: join(out, "main.css"), logLevel: "warning" });
}

function finish(meta) {
  firstScreenCss(meta);
  mkdirSync(join(out, "fonts"), { recursive: true });
  for (const [name, from] of Object.entries(FONTS)) copyFileSync(join(here, "node_modules", from), join(out, "fonts", name));
  // The cube, for the sidebar, the splash and the tab icon.
  mkdirSync(join(out, "brand"), { recursive: true });
  for (const f of readdirSync(join(here, "brand"))) copyFileSync(join(here, "brand", f), join(out, "brand", f));
  writeFileSync(join(out, "LICENSES.md"), licences().replace(/\r\n/g, "\n"));
  for (const [rel, body] of Object.entries(demoFiles())) {
    const target = join(out, "demo", rel);
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(target, body);
  }
  // The docs for Help and the workflow inputs for Settings, loaded only when those pages ask.
  const help = helpFiles(resolve(here, ".."));
  for (const [rel, body] of Object.entries(help)) {
    mkdirSync(dirname(join(out, rel)), { recursive: true });
    writeFileSync(join(out, rel), body);
  }
  if (!watch) console.log(`help: ${helpReport(help)}`);
  writeFileSync(join(webRoot, "index.html"), page(meta).replace(/\r\n/g, "\n"));
}

function clean() {
  // Old hashed chunks never pile up: the folder is rebuilt from scratch.
  if (existsSync(out)) rmSync(out, { recursive: true, force: true });
  mkdirSync(out, { recursive: true });
}

if (watch) {
  clean();
  await esbuild.build(bootOptions);
  const ctx = await esbuild.context({
    ...options,
    plugins: [{ name: "finish", setup(b) { b.onEnd((r) => { if (r.metafile) { finish(r.metafile); console.log("built", new Date().toLocaleTimeString()); } }); } }],
  });
  await ctx.watch();
  console.log("watching web/src for changes");
} else {
  clean();
  await esbuild.build(bootOptions);
  const result = await esbuild.build(options);
  finish(result.metafile);
  console.log(`built into ${relative(process.cwd(), out) || out}`);
}
