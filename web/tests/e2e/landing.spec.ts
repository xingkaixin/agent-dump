import { expect, test } from "@playwright/test";

const locales = [
  { name: "English", path: "/", htmlLang: "en", copy: "Copy", copied: "Copied" },
  { name: "Chinese", path: "/zh/", htmlLang: "zh-Hans", copy: "复制", copied: "已复制" },
] as const;

for (const locale of locales) {
  test(`${locale.name} landing page interactions survive hydration`, async ({ context, page }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await page.goto(locale.path);
    await page.evaluate(() => localStorage.removeItem("agent-dump-theme"));
    await page.reload();

    await expect(page.locator("html")).toHaveAttribute("lang", locale.htmlLang);
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");

    const install = page.locator("#install");
    const npmTab = install.getByRole("tab", { name: "npm", exact: true });
    await npmTab.scrollIntoViewIfNeeded();
    await expect(async () => {
      await npmTab.click();
      await expect(npmTab).toHaveAttribute("aria-selected", "true");
    }).toPass();

    const npmPanel = install.getByRole("tabpanel", { name: "npm" });
    await expect(npmPanel.getByText("npm install -g @agent-dump/cli", { exact: true })).toBeVisible();
    const copyButton = npmPanel.getByRole("button");
    await expect(copyButton).toHaveAccessibleName(locale.copy);
    await copyButton.click();
    await expect(copyButton).toHaveAccessibleName(locale.copied);
    await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(
      "npm install -g @agent-dump/cli",
    );

    const faq = page.locator("#faq");
    const firstQuestion = faq.getByRole("button").first();
    await firstQuestion.scrollIntoViewIfNeeded();
    await expect(async () => {
      await firstQuestion.focus();
      if ((await firstQuestion.getAttribute("aria-expanded")) !== "true") {
        await firstQuestion.press("Enter");
      }
      await expect(firstQuestion).toHaveAttribute("aria-expanded", "true");
    }).toPass();

    const answerId = await firstQuestion.getAttribute("aria-controls");
    expect(answerId).toBeTruthy();
    await expect(page.locator(`#${answerId}`)).toBeVisible();

    const themeToggle = page.locator("[data-theme-toggle]");
    await themeToggle.click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await expect.poll(() => page.evaluate(() => localStorage.getItem("agent-dump-theme"))).toBe("dark");
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await expect(page.locator('meta[name="theme-color"]')).toHaveAttribute("content", "#141109");
  });
}
