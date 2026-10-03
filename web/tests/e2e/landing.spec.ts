import { expect, test } from "@playwright/test";

const locales = [
  {
    name: "English",
    path: "/",
    htmlLang: "en",
    title: "Agent Dump | Find, Read and Export AI Coding Sessions",
    copy: "Copy",
    copied: "Copied",
  },
  {
    name: "Chinese",
    path: "/zh/",
    htmlLang: "zh-Hans",
    title: "Agent Dump | 查找、读取与导出 AI 编码会话",
    copy: "复制",
    copied: "已复制",
  },
  {
    name: "Japanese",
    path: "/ja/",
    htmlLang: "ja",
    title: "Agent Dump | AIコーディング履歴を検索・閲覧・エクスポート",
    copy: "コピー",
    copied: "コピーしました",
  },
] as const;

test.beforeEach(async ({ page }) => {
  await page.route("https://umami.xingkaixin.me/**", (route) => route.abort());
});

for (const locale of locales) {
  test(`${locale.name} landing page fits narrow and expanded viewports`, async ({
    page,
  }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto(locale.path);
    for (const width of [360, 382, 390, 951]) {
      await page.setViewportSize({ width, height: 844 });

      await expect
        .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
        .toBe(width);
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

      const install = page.locator("#install");
      for (const tab of await install.getByRole("tab").all()) {
        await expect(async () => {
          await tab.click();
          await expect(tab).toHaveAttribute("aria-selected", "true");
        }).toPass();
        const commands = await install.locator("code").evaluateAll((elements) =>
          elements.map((element) => ({
            text: element.textContent,
            width: element.clientWidth,
            contentWidth: element.scrollWidth,
            height: element.clientHeight,
            contentHeight: element.scrollHeight,
          })),
        );
        for (const command of commands) {
          expect(command.contentWidth, command.text ?? "").toBeLessThanOrEqual(
            command.width,
          );
          expect(command.contentHeight, command.text ?? "").toBeLessThanOrEqual(
            command.height,
          );
        }
      }
    }
  });

  test(`${locale.name} landing page interactions survive hydration`, async ({
    context,
    page,
  }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await page.setViewportSize({ width: 382, height: 678 });
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
    await expect(page.locator('header a[aria-current="page"]')).toHaveAttribute(
      "href",
      locale.path,
    );

    const analyticsScript = page.locator(
      'head script[src="https://umami.xingkaixin.me/script.js"]',
    );
    await expect(analyticsScript).toHaveCount(1);
    await expect(analyticsScript).toHaveAttribute("defer", "");
    await expect(analyticsScript).toHaveAttribute(
      "data-website-id",
      "7141781d-b011-454b-a16b-8c1e524140c6",
    );

    const install = page.locator("#install");
    const npmTab = install.getByRole("tab", { name: "npm", exact: true });
    await npmTab.scrollIntoViewIfNeeded();
    await expect(async () => {
      await npmTab.click();
      await expect(npmTab).toHaveAttribute("aria-selected", "true");
    }).toPass();

    const npmPanel = install.getByRole("tabpanel", { name: "npm" });
    await expect(
      npmPanel.getByText("npm install -g @agent-dump/cli", { exact: true }),
    ).toBeVisible();
    const copyButton = npmPanel.getByRole("button");
    await expect(copyButton).toHaveAccessibleName(locale.copy);
    for (const viewport of [
      { width: 382, height: 678 },
      { width: 951, height: 669 },
      { width: 382, height: 678 },
    ]) {
      await page.setViewportSize(viewport);
      await expect(npmTab).toHaveAttribute("aria-selected", "true");
      await copyButton.click();
      await expect(copyButton).toHaveAccessibleName(locale.copied);
      await expect
        .poll(() => page.evaluate(() => navigator.clipboard.readText()))
        .toBe("npm install -g @agent-dump/cli");
    }

    for (const [label, command] of [
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
      const tab = install.getByRole("tab", { name: label, exact: true });
      if (label === "Scoop") {
        await install
          .getByRole("tab", { name: "Homebrew", exact: true })
          .focus();
        await page.keyboard.press("ArrowRight");
        await expect(tab).toBeFocused();
        await tab.press("Enter");
      } else {
        await tab.click();
      }
      await expect(tab).toHaveAttribute("aria-selected", "true");
      const panel = install.getByRole("tabpanel", { name: label, exact: true });
      await panel.getByRole("button").click();
      await expect
        .poll(() => page.evaluate(() => navigator.clipboard.readText()))
        .toBe(command);
    }

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
    await expect(updates.locator("article")).toHaveCount(10);
    await expect(
      updates.locator("article").first().getByText("v1.1.1", { exact: true }),
    ).toBeVisible();

    const themeToggle = page.locator("[data-theme-toggle]");
    await themeToggle.click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await expect
      .poll(() => page.evaluate(() => localStorage.getItem("agent-dump-theme")))
      .toBe("dark");
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await expect(page.locator('meta[name="theme-color"]')).toHaveAttribute(
      "content",
      "#0c1011",
    );
  });
}

test("copy fallback does not report success when execCommand rejects it", async ({
  page,
}) => {
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
    await expect(page.locator("html")).toHaveAttribute(
      "data-copy-attempted",
      "true",
    );
  }).toPass();

  expect(await copyButton.getAttribute("aria-label")).toBe("Copy");
});

test("sample explorer searches, switches formats and copies the selected conversation", async ({
  context,
  page,
}) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("/");
  const explorer = page.locator(".session-explorer");
  await explorer.scrollIntoViewIfNeeded();
  const search = explorer.getByRole("searchbox");
  await search.fill("database");
  await expect(
    explorer.getByRole("button", {
      name: "Claude Code Plan the database migration",
    }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(explorer.locator("pre")).toContainText(
    "without dropping existing records",
  );
  await explorer.getByRole("tab", { name: "JSON", exact: true }).click();
  await explorer.getByRole("tabpanel", { name: "JSON", exact: true }).getByRole("button", { name: "Copy", exact: true }).click();
  const output = JSON.parse(
    await page.evaluate(() => navigator.clipboard.readText()),
  );
  expect(output.title).toBe("Plan the database migration");
  expect(output.messages).toHaveLength(2);
  await search.fill("no-such-sample");
  await expect(explorer.getByRole("status")).toContainText(
    "No matching sessions",
  );
  await search.fill("");
  await expect(
    explorer.getByRole("button", { name: /Codex Fix/ }),
  ).toBeVisible();
});

test("mobile navigation is reachable by keyboard and closes on escape or navigation", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/zh/");
  const menu = page.locator(".mobile-menu");
  const trigger = menu.locator("summary");
  await trigger.focus();
  await page.keyboard.press("Enter");
  await expect(menu).toHaveAttribute("open", "");
  await menu.getByRole("link", { name: "使用说明" }).focus();
  await page.keyboard.press("Escape");
  await expect(menu).not.toHaveAttribute("open");
  await expect(trigger).toBeFocused();
  await trigger.click();
  await menu.getByRole("link", { name: "使用说明" }).click();
  await expect(page).toHaveURL("/zh/guides/");
});
