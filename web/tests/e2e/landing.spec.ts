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
  test(`${locale.name} landing page fits a narrow viewport`, async ({ page }) => {
    for (const width of [360, 390]) {
      await page.setViewportSize({ width, height: 844 });
      await page.goto(locale.path);

      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
      const boxes = await page
        .locator(
          "#hero h1, #hero canvas, #capabilities img, #capabilities [role='img'], #install code, #install button",
        )
        .evaluateAll((elements) =>
          elements.map((element) => ({
            left: element.getBoundingClientRect().left,
            right: element.getBoundingClientRect().right,
          })),
        );
      for (const box of boxes) {
        expect(box.left).toBeGreaterThanOrEqual(0);
        expect(box.right).toBeLessThanOrEqual(width);
      }
    }
  });

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

    const updates = page.locator("#updates");
    await expect(updates).toBeVisible();
    await expect(updates.locator("article")).toHaveCount(3);
    await expect(updates.getByText("v0.15.4")).toBeVisible();

    const themeToggle = page.locator("[data-theme-toggle]");
    await themeToggle.click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await expect.poll(() => page.evaluate(() => localStorage.getItem("agent-dump-theme"))).toBe("dark");
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await expect(page.locator('meta[name="theme-color"]')).toHaveAttribute("content", "#0c1011");
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

test("generated artwork and WebGL scene render within budget", async ({ page }) => {
  for (const width of [390, 1280]) {
    await page.setViewportSize({ width, height: 844 });
    await page.goto("/");

    const scene = page.locator("[data-focus-scene]");
    await expect(scene).toHaveAttribute("data-ready", "true");
    await expect(scene).toHaveAttribute("data-webgl", /^(ready|unavailable)$/);
    await expect
      .poll(() => page.locator(".focus-scene__canvas").evaluate((canvas: HTMLCanvasElement) => canvas.width))
      .toBeGreaterThan(0);

    const artwork = page.locator(".convergence-image");
    await expect(artwork).toHaveCount(1);
    await artwork.scrollIntoViewIfNeeded();
    await expect.poll(() => artwork.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(0);
    const source = await artwork.evaluate((image: HTMLImageElement) => image.currentSrc);
    const response = await page.request.get(source);
    expect(response.ok()).toBe(true);
    expect(response.headers()["content-type"]).toContain("image/webp");
    expect((await response.body()).byteLength).toBeLessThan(100 * 1024);
  }
});
