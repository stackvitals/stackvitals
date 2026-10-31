// Every page x demo repo x theme x width: loads clean, fits the width, and shows real text.
import { readFileSync } from "node:fs";
import { DEMOS, expect, openApp, test } from "./fixtures";

// The route ids, read from the app's own list so a new page is swept without editing this file.
const ROUTES = [...readFileSync(new URL("../src/app/routes.ts", import.meta.url), "utf8").matchAll(/\{ id: "([a-z-]+)"/g)].map((m) => m[1]!);
const SIZES = { desktop: { width: 1440, height: 900 }, phone: { width: 375, height: 812 } } as const;
type Size = keyof typeof SIZES;

// Instrument, the only design, in both themes at both widths.
const CASES: { theme: "light" | "dark"; size: Size }[] =
  (["light", "dark"] as const).flatMap((theme) => (["desktop", "phone"] as const).map((size) => ({ theme, size })));

test("the route list is read", () => expect(ROUTES.length).toBeGreaterThan(15));

for (const c of CASES) for (const repo of DEMOS) {
  test.describe(`Instrument ${c.theme} ${c.size} ${repo}`, () => {
    test.use({ viewport: SIZES[c.size] });
    for (const route of ROUTES) {
      test(route, async ({ page, problems }) => {
        await openApp(page, { repo, route, theme: c.theme });
        const root = page.locator("html");
        await expect(root).toHaveAttribute("data-theme", c.theme);
        await expect(root).toHaveAttribute("data-design", "sheet");

        const got = await page.evaluate(() => ({
          over: document.documentElement.scrollWidth - document.documentElement.clientWidth,
          text: (document.querySelector("main") as HTMLElement | null)?.innerText || "",
        }));
        expect(got.over, "no sideways scroll").toBeLessThanOrEqual(1);
        expect(got.text.trim().length, "the page shows real text").toBeGreaterThan(200);
        expect(got.text).not.toMatch(/\bundefined\b|\bNaN\b|\[object Object\]/);
        expect(problems.errors).toEqual([]);
      });
    }
  });
}
