// The app's key flows on demo data, end to end in the browser; GitHub is faked wherever a flow asks it something.
import type { Locator, Page } from "@playwright/test";
import { GH_LINK_MAX, expect, fakeGitHub, githubLinks, openApp, settle, test } from "./fixtures";

const TOKEN = "github_pat_11AAAAAAA0abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJ";
test.use({ permissions: ["clipboard-read", "clipboard-write"] });

// Windows hands the clipboard back with CRLF line ends.
const clipboard = async (page: Page) => (await page.evaluate(() => navigator.clipboard.readText())).replace(/\r\n/g, "\n");
const hrefOf = async (l: Locator) => (await l.getAttribute("href")) || "";

// Clicks a link that opens GitHub in a new tab (blocked by the guard) and closes that tab.
async function clickExternal(page: Page, link: Locator): Promise<void> {
  const popup = page.waitForEvent("popup");
  await link.click();
  await (await popup).close();
}

test("Overview: the decision builder makes a prefilled request", async ({ page, problems }) => {
  await openApp(page, { repo: "payments-api" });
  const box = page.locator("#ov-decide");
  await box.scrollIntoViewIfNeeded();
  const what = box.getByLabel("1. What to decide on");
  const options = await what.locator("option").all();
  expect(options.length).toBeGreaterThan(1);
  await what.selectOption({ index: 1 });
  const item = (await options[1]!.textContent())!;

  const verb = box.getByLabel("2. The decision");
  await verb.selectOption({ index: (await verb.locator("option").count()) - 1 });
  const lasts = box.getByRole("radiogroup", { name: "For how long" });
  if (await lasts.count()) {
    await lasts.getByRole("radio", { name: "14 days" }).click();
    await expect(box.locator(".ov-build-sum")).toContainText("until");
  }
  await box.getByPlaceholder("A short reason").fill("Waiting on the upstream fix");
  await expect(box.locator(".ov-what-id")).not.toBeEmpty();
  expect(item.length).toBeGreaterThan(0);

  const gh = box.getByRole("link", { name: "Open the request on GitHub" });
  const url = await hrefOf(gh);
  expect(url).toMatch(/^https:\/\/github\.com\/acme\/payments-api\/issues\/new\?title=/);
  expect(url.length).toBeLessThanOrEqual(GH_LINK_MAX);
  expect(decodeURIComponent(url)).toContain("Waiting on the upstream fix");
  await expect(box.locator(".paste-note")).toHaveCount(0);

  // The other send paths: the comment to paste, and the token path asking for a token (nothing is sent).
  await expect(box.locator(".cmd code")).toContainText("/stackvitals");
  await box.getByRole("button", { name: "Apply now with my token" }).click();
  await expect(box.getByLabel("Fine-grained GitHub token")).toBeVisible();
  expect(problems.errors).toEqual([]);
});

test.describe("CI: Set up in your CI", () => {
  const yaml = (box: Locator) => box.locator(".ci-yaml pre code").textContent();
  const switches = (box: Locator) => box.locator(".ci-feats [role=switch]");
  async function setAll(box: Locator, on: (i: number) => boolean) {
    const n = await switches(box).count();
    expect(n).toBe(6);
    for (let i = 0; i < n; i++) {
      const s = switches(box).nth(i);
      if ((await s.getAttribute("aria-checked")) !== String(on(i))) await s.click();
      await expect(s).toHaveAttribute("aria-checked", String(on(i)));
    }
  }

  test.beforeEach(async ({ page }) => {
    await openApp(page, { repo: "payments-api", route: "ci" });
    await page.getByRole("button", { name: "Set up in your CI" }).click();
    await expect(page.locator(".ci-setup")).toBeInViewport();
  });

  test("the runner switch changes the workflow file", async ({ page, problems }) => {
    const box = page.locator(".ci-setup");
    const runner = box.getByLabel("1. Test runner");
    await runner.selectOption("pytest");
    const before = await yaml(box);
    expect(before).toContain("pytest");
    await runner.selectOption("jest");
    await expect.poll(() => yaml(box)).not.toBe(before);
    expect(await yaml(box)).toContain("jest");
    expect(problems.errors).toEqual([]);
  });

  test("every feature on gives the paste path, with the whole file copied", async ({ page, problems }) => {
    const box = page.locator(".ci-setup");
    await box.getByLabel("1. Test runner").selectOption("pytest");
    await setAll(box, () => true);
    const gh = box.getByRole("link", { name: "Open it on GitHub" });
    const url = await hrefOf(gh);
    expect(url.length).toBeLessThanOrEqual(GH_LINK_MAX);
    expect(url).toMatch(/\/new\/main\?filename=/);
    expect(url).not.toContain("&value=");
    await expect(box.locator(".ci-add-note").first()).toContainText("too long for a GitHub link");
    await clickExternal(page, gh);
    expect(await clipboard(page)).toBe(await yaml(box));
    expect(problems.errors).toEqual([]);
  });

  test("few features give a prefilled link under the cap", async ({ page, problems }) => {
    const box = page.locator(".ci-setup");
    await box.getByLabel("1. Test runner").selectOption("pytest");
    await setAll(box, (i) => i === 5);
    const url = await hrefOf(box.getByRole("link", { name: "Open it on GitHub" }));
    expect(url).toContain("&value=");
    expect(url.length).toBeLessThanOrEqual(GH_LINK_MAX);
    await expect(box.locator(".ci-add-note").first()).not.toContainText("too long");
    // "Copy the file" copies the same file the link carries.
    await box.getByRole("button", { name: "Copy the file" }).click();
    const file = await clipboard(page);
    expect(file).toBe(await yaml(box));
    expect(file.length).toBeGreaterThan(200);
    expect(problems.errors).toEqual([]);
  });
});

test("PRs: checking a planned pull request reads it against merged ones", async ({ page, problems }) => {
  await openApp(page, { repo: "payments-api", route: "prs" });
  const panel = page.locator(".pr-pre");
  await panel.scrollIntoViewIfNeeded();
  await expect(panel).toContainText("Fill in the files and size");
  await panel.getByLabel("Files it changes").fill("src/app.ts\nsrc/handler.ts");
  await panel.getByLabel("Lines added plus removed").fill("5000");
  await expect(panel.locator(".blk-panel-state")).not.toContainText("Fill in the files and size");
  await expect(panel.locator(".blk-panel-state")).toContainText(/to look at|Nothing stands out/);
  await expect(panel.locator(".cmd code")).toContainText("--paths src/app.ts src/handler.ts --lines 5000");
  await expect(panel).toContainText(/Unusually big|Bigger than most|Usual size/);
  expect(problems.errors).toEqual([]);
});

test("Explore: a ready question returns rows", async ({ page, problems }) => {
  await openApp(page, { repo: "payments-api", route: "explore" });
  const qs = page.getByRole("group", { name: "Questions" }).getByRole("button");
  expect(await qs.count()).toBeGreaterThan(1);
  for (const i of [0, 1]) {
    await qs.nth(i).click();
    const result = page.locator(".ex-ask .ex-result");
    await expect(result).toContainText(/[1-9][\d,]* rows? from /);
    expect(await result.locator("tbody tr").count()).toBeGreaterThan(0);
  }
  expect(problems.errors).toEqual([]);
});

test("Portal: the access check reads a faked GitHub", async ({ page, problems }) => {
  const calls = await fakeGitHub(page, [
    [/^\/orgs\/acme\/repos\?/, { body: [{ full_name: "acme/payments-api", private: true, default_branch: "main" }, { full_name: "acme/docs", private: false, default_branch: "main" }] }],
    [/^\/repos\/acme\/payments-api\/contents\/\.github\/CODEOWNERS/, { body: { name: "CODEOWNERS" } }],
    [/^\/repos\/acme\/payments-api\/rules\/branches\/main/, { body: [] }],
    [/^\/orgs\/acme\/teams/, { body: [{ slug: "core" }] }],
    [/^\/orgs\/acme\/properties\/values/, { status: 403, body: { message: "Resource not accessible" } }],
  ]);
  await openApp(page, { repo: "payments-api", route: "portal" });
  const panel = page.locator("section", { has: page.getByRole("heading", { name: "Check a token's access" }) }).last();
  await panel.scrollIntoViewIfNeeded();
  await expect(panel.getByLabel("Org or user")).toHaveValue("acme");
  await panel.getByLabel("Token", { exact: true }).fill(TOKEN);
  await panel.getByRole("button", { name: "Check acme" }).click();
  const out = panel.getByRole("status");
  await expect(out).toContainText("acme with the pasted token");
  await expect(out).toContainText("2 visible (1 private)");
  await expect(out).toContainText("readable (tried acme/payments-api)");
  await expect(out).toContainText("Custom properties");
  await expect(out).toContainText("not available");
  expect(calls.some((c) => c.startsWith("GET /orgs/acme/repos"))).toBe(true);
  expect(calls.every((c) => c.startsWith("GET "))).toBe(true);
  expect(problems.errors).toEqual([]);
});

test.describe("Help: links jump to the part they name", () => {
  for (const [at, page_] of [["ov-decide", "Overview"], ["ci-setup", "CI Health"]] as const) {
    test(at, async ({ page, problems }) => {
      await openApp(page, { repo: "payments-api", route: "help" });
      await page.locator(`a[href*="at=${at}"]`).first().click();
      await settle(page);
      await expect(page.locator(".page-head h1")).toHaveText(page_);
      await expect(page.locator(`#${at}`)).toBeInViewport();
      expect(problems.errors).toEqual([]);
    });
  }
});

test("Connections: brand logos draw, and every connection's sheet opens", async ({ page, problems }) => {
  // 28 sheets open and close in turn; still motion keeps that quick.
  test.setTimeout(120_000);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await openApp(page, { repo: "payments-api", route: "connections" });
  const logos = page.locator("svg.blogo path");
  expect(await logos.count()).toBeGreaterThan(5);
  for (const d of await logos.evaluateAll((ps) => ps.map((p) => p.getAttribute("d") || ""))) expect(d.length).toBeGreaterThan(20);
  const box = await page.locator("svg.blogo").first().boundingBox();
  expect(box!.width).toBeGreaterThan(8);

  // Each sheet: its GitHub links fit, and the connection test says the demo has nothing to test.
  const conns = page.locator("button.conn");
  let tests = 0;
  for (let i = 0; i < (await conns.count()); i++) {
    await conns.nth(i).click();
    const sheet = page.getByRole("dialog");
    await expect(sheet).toBeVisible();
    for (const u of await githubLinks(page)) expect(u.length).toBeLessThanOrEqual(GH_LINK_MAX);
    if (await sheet.getByRole("heading", { name: "Test connection" }).count()) {
      await expect(sheet).toContainText("Demo data: there is nothing to test.");
      tests++;
    }
    await sheet.getByRole("button", { name: "Done" }).click();
    await expect(sheet).toBeHidden();
  }
  expect(tests, "connections with a test").toBeGreaterThan(2);
  expect(problems.errors).toEqual([]);
});
