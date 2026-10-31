// The Welcome screen on a first visit: the token check against a fake GitHub, the demo, and opening a public repo by name.
import { expect, fakeGitHub, settle, test } from "./fixtures";

const TOKEN = "github_pat_11AAAAAAA0abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJ";
const ME = { login: "octo", name: "Octo Cat", avatar_url: "https://avatars.githubusercontent.com/u/1" };

test.beforeEach(async ({ page }) => {
  await page.goto("/index.html");
  await settle(page);
  await expect(page.getByRole("heading", { name: "Know how your repo is really doing." })).toBeVisible();
});

test("a fresh visit shows the Welcome screen", async ({ page, problems }) => {
  await expect(page.getByRole("heading", { name: "Connect GitHub" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Try the demo" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Open a public repo" })).toBeVisible();
  expect(problems.errors).toEqual([]);
});

test.describe("token check", () => {
  const field = (p: import("@playwright/test").Page) => p.getByLabel("GitHub token");
  const status = (p: import("@playwright/test").Page) => p.locator("#svw-tok-status");

  test("an empty token asks for one", async ({ page }) => {
    await page.getByRole("button", { name: "Check token" }).click();
    await expect(status(page)).toHaveText("Paste the token first.");
  });

  test("a malformed token says what a token looks like", async ({ page }) => {
    await field(page).fill("hello-not-a-token");
    await page.getByRole("button", { name: "Check token" }).click();
    await expect(status(page)).toContainText("doesn't look like a GitHub token");
  });

  test("a token GitHub refuses says so", async ({ page }) => {
    await fakeGitHub(page, [[/^\/user$/, { status: 401, body: { message: "Bad credentials" } }]]);
    await field(page).fill(TOKEN);
    await expect(status(page)).toContainText("GitHub refused the token");
  });

  test("a valid token connects and lists what it can do", async ({ page, problems }) => {
    const calls = await fakeGitHub(page, [
      [/^\/user$/, { body: ME }],
      [/^\/user\/repos/, { body: [{ full_name: "octo/hello", name: "hello", owner: { login: "octo" }, private: true, default_branch: "main", pushed_at: "2026-10-01T00:00:00Z" }] }],
    ]);
    await field(page).fill(TOKEN);
    await expect(page.getByRole("heading", { name: "Your GitHub" })).toBeVisible();
    await expect(page.getByText("Connected as", { exact: false }).first()).toContainText("octo");
    await expect(page.getByText("1 repo picked.")).toBeVisible();
    expect(calls).toContain("GET /user");
    // The token stays in this tab unless "Remember" was ticked.
    expect(await page.evaluate(() => Object.keys(localStorage).filter((k) => localStorage.getItem(k)?.includes("github_pat_")))).toEqual([]);
    expect(problems.errors).toEqual([]);
  });
});

test("Open the demo shows the demo repos", async ({ page, problems }) => {
  await page.getByRole("link", { name: "Open the demo" }).click();
  await settle(page);
  expect(new URL(page.url()).searchParams.get("demo")).toBe("1");
  await expect(page.locator(".demo-banner")).toContainText("demo data");
  await expect(page.locator(".page-head h1")).toHaveText("Overview");
  expect(problems.errors).toEqual([]);
});

test.describe("open a public repo by name", () => {
  const open = async (page: import("@playwright/test").Page, name: string) => {
    await page.getByLabel("Repository", { exact: true }).fill(name);
    await page.getByRole("button", { name: "Open", exact: true }).click();
  };

  test("a badly typed name says the format", async ({ page }) => {
    await open(page, "not a repo");
    await expect(page.locator("#svw-repo-err")).toContainText("owner/repo");
  });

  test("a repo GitHub doesn't show says it may be private", async ({ page }) => {
    await fakeGitHub(page, []);
    await open(page, "octo/nope");
    await expect(page.getByRole("status").filter({ hasText: "doesn't show" })).toContainText("octo/nope");
  });

  test("a repo without StackVitals offers setup", async ({ page }) => {
    await fakeGitHub(page, [[/^\/repos\/octo\/hello$/, { body: { full_name: "octo/hello", private: false, default_branch: "main" } }]]);
    await open(page, "octo/hello");
    await expect(page.getByText("doesn't run StackVitals yet")).toBeVisible();
    await expect(page.getByRole("button", { name: "Set it up" })).toBeVisible();
  });

  test("a repo with a Pages site opens its dashboard", async ({ page, problems }) => {
    await fakeGitHub(page, [[/^\/repos\/octo\/hello$/, { body: { full_name: "octo/hello", private: false, default_branch: "main" } }]]);
    await page.route("https://octo.github.io/hello/**", (r) => (r.request().url().endsWith("/app.json")
      ? r.fulfill({ contentType: "application/json", headers: { "access-control-allow-origin": "*" }, body: JSON.stringify({ schema: 1, repo: "octo/hello", default_branch: "main", modules: {} }) })
      : r.fulfill({ status: 404, headers: { "access-control-allow-origin": "*" }, body: "" })));
    await open(page, "https://github.com/octo/hello");
    await expect(page.getByRole("heading", { name: "Know how your repo is really doing." })).toBeHidden();
    await settle(page);
    await expect(page.getByText("octo/hello").first()).toBeVisible();
    expect(problems.errors).toEqual([]);
  });
});
