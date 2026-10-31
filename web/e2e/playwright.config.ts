// Browser end-to-end tests: npm run e2e. Uses the installed Google Chrome (PLAYWRIGHT_CHANNEL= picks bundled Chromium).
import { defineConfig } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

// One free port, chosen once in the main process; workers inherit it through the environment.
process.env.SV_E2E_PORT ||= execFileSync(process.execPath,
  ["-e", "const s=require('net').createServer().listen(0,'127.0.0.1',()=>{process.stdout.write(String(s.address().port));s.close()})"]).toString();
const base = `http://127.0.0.1:${process.env.SV_E2E_PORT}`;
const channel = process.env.PLAYWRIGHT_CHANNEL ?? "chrome";

export default defineConfig({
  testDir: ".",
  testMatch: "*.spec.ts",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: process.env.CI ? 2 : "50%",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  // results.json is what scripts/prelaunch.py reads (with the exit code).
  reporter: [["list"], ["json", { outputFile: fileURLToPath(new URL("results.json", import.meta.url)) }]],
  outputDir: "test-results",
  use: {
    baseURL: base,
    ...(channel ? { channel } : {}),
    headless: true,
    viewport: { width: 1440, height: 900 },
    screenshot: "only-on-failure",
    serviceWorkers: "block",
  },
  webServer: {
    command: `node serve.mjs ${process.env.SV_E2E_PORT}`,
    url: `${base}/index.html`,
    reuseExistingServer: false,
    stdout: "ignore",
  },
});
