import { expect, test } from "@playwright/test";

const locales = [
  { name: "English", path: "/", htmlLang: "en" },
  { name: "Chinese", path: "/zh/", htmlLang: "zh-Hans" },
  { name: "Japanese", path: "/ja/", htmlLang: "ja" },
] as const;

test.beforeEach(async ({ page }) => {
  await page.route("https://umami.xingkaixin.me/**", (route) => route.abort());
});

for (const locale of locales) {
  test(`${locale.name} landing page copies the real install commands`, async ({
    context,
    page,
  }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    const response = await page.goto(locale.path);
    expect(response?.ok()).toBe(true);
    await expect(page.locator("html")).toHaveAttribute("lang", locale.htmlLang);

    const install = page.locator("#install");
    for (const [label, command] of [
      ["npm", "npm install -g @agent-dump/cli"],
      [
        "curl",
        "curl -sSfL https://github.com/xingkaixin/agent-dump/releases/latest/download/install.sh | sh",
      ],
      ["Homebrew", "brew install xingkaixin/tap/agent-dump"],
      [
        "Scoop",
        "scoop bucket add xingkaixin https://github.com/xingkaixin/scoop-bucket\nscoop install xingkaixin/agent-dump",
      ],
    ]) {
      const tab = install.getByRole("button", { name: label, exact: true });
      await tab.scrollIntoViewIfNeeded();
      await expect(async () => {
        await tab.click();
        await expect(tab).toHaveAttribute("aria-pressed", "true");
      }).toPass();
      const panel = install.getByRole("region", { name: label, exact: true });
      await panel.getByRole("button").click();
      await expect
        .poll(() => page.evaluate(() => navigator.clipboard.readText()))
        .toBe(command);
    }
  });
}

test("browser language only redirects to translations that exist", async ({
  browser,
}) => {
  const context = await browser.newContext({ locale: "ja-JP" });
  const page = await context.newPage();
  await page.goto("/guides/export-codex-session/");
  await expect(page).toHaveURL("/guides/export-codex-session/");
  await context.close();
});
