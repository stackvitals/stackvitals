// Every github.com link the app draws stays under the length GitHub accepts, on every page and its sub-pages.
import { readFileSync } from "node:fs";
import { DEMOS, GH_LINK_MAX, expect, githubLinks, openApp, settle, test } from "./fixtures";

const ROUTES = [...readFileSync(new URL("../src/app/routes.ts", import.meta.url), "utf8").matchAll(/\{ id: "([a-z-]+)"/g)].map((m) => m[1]!);
// Sub-pages reached from a page (settings groups, a test's detail, a tab), at most this many per page.
const SUB_PAGES = 15;

for (const repo of DEMOS) {
  test.describe(repo, () => {
    for (const route of ROUTES) {
      test(route, async ({ page, problems }, info) => {
        await openApp(page, { repo, route });
        const seen = new Map<string, string>();
        const take = async (where: string) => { for (const u of await githubLinks(page)) if (!seen.has(u)) seen.set(u, where); };
        await take(route);
        const subs = [...new Set(await page.$$eval(`a[href^="#/${route}/"], a[href^="#/${route}?"]`, (as) => as.map((a) => a.getAttribute("href")!)))].slice(0, SUB_PAGES);
        for (const h of subs) {
          await page.goto(page.url().replace(/#.*$/, "") + h);
          await settle(page);
          await take(h);
        }
        const long = [...seen].filter(([u]) => u.length > GH_LINK_MAX).map(([u, at]) => `${at}: ${u.length} chars, ${u.slice(0, 120)}...`);
        await info.attach("github-links.json", { contentType: "application/json",
          body: JSON.stringify([...seen].map(([u, at]) => ({ at, length: u.length, url: u.slice(0, 200) })), null, 1) });
        expect(long).toEqual([]);
        expect(problems.errors).toEqual([]);
      });
    }
  });
}

test("the Welcome screen's GitHub links", async ({ page }) => {
  await page.goto("/index.html");
  await settle(page);
  const links = await githubLinks(page);
  expect(links.length).toBeGreaterThan(0);
  for (const u of links) expect(u.length).toBeLessThanOrEqual(GH_LINK_MAX);
});
