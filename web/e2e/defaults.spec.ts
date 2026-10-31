// First-visit defaults (light, Instrument, the only design) and the theme switch that changes live and is remembered.
import { expect, openApp, test } from "./fixtures";

test.describe("a system set to dark", () => {
  test.use({ colorScheme: "dark" });
  test("a fresh visit is light and Instrument", async ({ page, problems }) => {
    await openApp(page);
    const root = page.locator("html");
    await expect(root).toHaveAttribute("data-theme", "light");
    await expect(root).toHaveAttribute("data-design", "sheet");
    expect(await page.evaluate(() => localStorage.getItem("sv:theme"))).toBeNull();
    expect(problems.errors).toEqual([]);
  });
});

test("Settings switches the theme live and it persists; there is no design switch", async ({ page, problems }) => {
  await openApp(page, { route: "settings/appearance" });
  const root = page.locator("html");
  const bg = () => page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  const light = await bg();
  await expect(page.getByRole("radiogroup", { name: "Theme" })).toBeVisible();
  await expect(page.getByRole("radiogroup", { name: "Design" })).toHaveCount(0);

  await page.getByRole("radiogroup", { name: "Theme" }).getByRole("radio", { name: "Dark" }).click();
  await expect(root).toHaveAttribute("data-theme", "dark");
  await expect.poll(bg).not.toBe(light);
  await page.reload();
  await expect(root).toHaveAttribute("data-theme", "dark");
  await expect(root).toHaveAttribute("data-design", "sheet");
  expect(problems.errors).toEqual([]);
});

// Classic was removed: an old saved choice and ?design=classic are both ignored.
test("an old Classic choice or ?design=classic still opens Instrument", async ({ page, problems }) => {
  await page.addInitScript(() => { try { localStorage.setItem("sv:design", JSON.stringify("classic")); } catch { /* storage off */ } });
  await openApp(page, { design: "classic" });
  const root = page.locator("html");
  await expect(root).toHaveAttribute("data-design", "sheet");
  expect(await page.evaluate(() => getComputedStyle(document.body).fontFamily)).toContain("IBM Plex Sans");
  expect(await page.evaluate(() => document.getElementById("sv-sheet"))).toBeNull();
  await openApp(page, { demo: false, design: "classic" });
  await expect(page.getByRole("heading", { name: "Know how your repo is really doing." })).toBeVisible();
  await expect(page.locator(".svw-settings")).toBeVisible();
  await expect(page.getByRole("radiogroup", { name: "Design" })).toHaveCount(0);
  expect(problems.errors).toEqual([]);
});
