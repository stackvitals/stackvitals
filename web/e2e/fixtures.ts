// Shared test setup: no outside network, page and console errors collected, and helpers to open the app and fake GitHub.
import { test as base, expect, type Page, type Route } from "@playwright/test";

export { expect };
export const DEMOS = ["payments-api", "web-app", "mobile"] as const;
export const GH_LINK_MAX = 4000;

// Console errors that are expected, each with its reason (text, then the URL it came from). Anything else fails the test.
const BENIGN: [RegExp, RegExp, string][] = [
  [/^Failed to load resource/, /^https:\/\//, "a refusal the test fakes (a bad token, a missing repo), or an outside host the guard aborts"],
  [/^Failed to load resource: .* 404/, /^http:\/\/127\.0\.0\.1:\d+\/app\.json$/, "the Welcome screen checks whether this folder holds a repo's data"],
];

export interface Problems { errors: string[]; outside: string[] }

// A transparent 1x1 PNG for avatars, so pictures load without the network.
const PIXEL = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=", "base64");

export const test = base.extend<{ problems: Problems }>({
  problems: [async ({ page, context, baseURL }, use) => {
    const p: Problems = { errors: [], outside: [] };
    const own = new URL(baseURL!).host;
    // Every outside request is stopped; tests that need GitHub answers add page routes, which win over this one.
    await context.route((u) => u.host !== own && /^(https?|wss?):$/.test(u.protocol), (route: Route) => {
      const u = new URL(route.request().url());
      p.outside.push(u.href);
      if (u.host === "avatars.githubusercontent.com") return route.fulfill({ status: 200, contentType: "image/png", body: PIXEL });
      return route.abort();
    });
    page.on("pageerror", (e) => p.errors.push(`pageerror: ${e.message}`));
    page.on("console", (m) => {
      if (m.type() !== "error") return;
      const text = m.text(), at = m.location().url;
      if (!BENIGN.some(([re, from]) => re.test(text) && from.test(at))) p.errors.push(`console: ${text} (${at})`);
    });
    await use(p);
  }, { auto: true }],
});

export interface OpenOpts { repo?: string; route?: string; theme?: "light" | "dark"; design?: string; demo?: boolean }

// Opens the app the way a visitor would: storage set before the first script, then the page settled.
export async function openApp(page: Page, o: OpenOpts = {}): Promise<void> {
  const theme = o.theme;
  if (theme) await page.addInitScript((t) => { try { localStorage.setItem("sv:theme", JSON.stringify(t)); } catch { /* storage off */ } }, theme);
  const q = new URLSearchParams();
  if (o.demo !== false) q.set("demo", "1");
  if (o.repo) q.set("repo", o.repo);
  if (o.design) q.set("design", o.design);
  await page.goto(`/index.html${q.size ? "?" + q : ""}#/${o.route && o.route !== "overview" ? o.route : ""}`);
  await settle(page);
}

// Waits until the page's lazy module and data have loaded and the skeletons are gone.
export async function settle(page: Page): Promise<void> {
  await page.waitForLoadState("networkidle");
  await expect(page.locator("#splash")).toBeHidden();
  await expect(page.locator(".skeleton, .sk")).toHaveCount(0);
}

// Every github.com link on the page.
export const githubLinks = (page: Page) => page.$$eval("a[href]", (as) =>
  as.map((a) => (a as HTMLAnchorElement).href).filter((h) => /^https:\/\/([^/]+\.)?github\.com\//.test(h)));

type Answer = { status?: number; body?: unknown; headers?: Record<string, string> };

// A fake api.github.com: each handler matches a path (with its query) and answers; anything else is a 404.
export async function fakeGitHub(page: Page, handlers: [RegExp, Answer | ((u: URL) => Answer)][]): Promise<string[]> {
  const seen: string[] = [];
  await page.route("https://api.github.com/**", (route) => {
    const u = new URL(route.request().url());
    seen.push(`${route.request().method()} ${u.pathname}${u.search}`);
    const hit = handlers.find(([re]) => re.test(u.pathname + u.search));
    const a = hit ? (typeof hit[1] === "function" ? hit[1](u) : hit[1]) : { status: 404, body: { message: "Not Found" } };
    return route.fulfill({ status: a.status ?? 200, contentType: "application/json",
      headers: { "access-control-allow-origin": "*", "access-control-expose-headers": "*", ...a.headers }, body: JSON.stringify(a.body ?? {}) });
  });
  return seen;
}
