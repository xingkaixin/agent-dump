import { expect, test } from "@playwright/test";

const locales = [
  {
    name: "English",
    path: "/",
    htmlLang: "en",
    title: "Agent Dump | Export AI Coding Sessions from CLI",
    copy: "Copy",
    copied: "Copied",
  },
  {
    name: "Chinese",
    path: "/zh/",
    htmlLang: "zh-Hans",
    title: "Agent Dump | AI 编码会话导出工具",
    copy: "复制",
    copied: "已复制",
  },
  {
    name: "Japanese",
    path: "/ja/",
    htmlLang: "ja",
    title: "Agent Dump | AIコーディングセッションをCLIからエクスポート",
    copy: "コピー",
    copied: "コピーしました",
  },
] as const;

test.beforeEach(async ({ page }) => {
  await page.route("https://umami.xingkaixin.me/**", (route) => route.abort());
});

for (const locale of locales) {
  test(`${locale.name} landing page interactions survive hydration`, async ({ context, page }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await page.goto(locale.path);
    await page.evaluate(() => localStorage.removeItem("agent-dump-theme"));
    await page.reload();

    await expect(page.locator("html")).toHaveAttribute("lang", locale.htmlLang);
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await expect(page).toHaveTitle(locale.title);
    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
      "href",
      `https://agent-dump.xingkaixin.me${locale.path}`,
    );
    await expect(page.locator('link[rel="alternate"]')).toHaveCount(4);
    await expect(page.locator('header a[aria-current="page"]')).toHaveAttribute("href", locale.path);

    const analyticsScript = page.locator('head script[src="https://umami.xingkaixin.me/script.js"]');
    await expect(analyticsScript).toHaveCount(1);
    await expect(analyticsScript).toHaveAttribute("defer", "");
    await expect(analyticsScript).toHaveAttribute("data-website-id", "7141781d-b011-454b-a16b-8c1e524140c6");

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

test("copy fallback does not report success when execCommand rejects it", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, "isSecureContext", { value: false });
    Object.defineProperty(document, "execCommand", {
      value: () => {
        document.documentElement.dataset.copyAttempted = "true";
        return false;
      },
    });
  });
  await page.goto("/");

  const copyButton = page.locator("#install").getByRole("button").first();
  await expect(async () => {
    await copyButton.click();
    await expect(page.locator("html")).toHaveAttribute("data-copy-attempted", "true");
  }).toPass();

  expect(await copyButton.getAttribute("aria-label")).toBe("Copy");
});
