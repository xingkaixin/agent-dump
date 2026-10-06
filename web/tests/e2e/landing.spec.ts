import { expect, test } from "@playwright/test";

const locales = [
  {
    name: "English",
    path: "/",
    htmlLang: "en",
    title: "Export Codex & Claude Code Sessions | Agent Dump",
    copy: "Copy",
    copied: "Copied",
  },
  {
    name: "Chinese",
    path: "/zh/",
    htmlLang: "zh-Hans",
    title: "Codex、Claude Code 会话导出与搜索 | Agent Dump",
    copy: "复制",
    copied: "已复制",
  },
  {
    name: "Japanese",
    path: "/ja/",
    htmlLang: "ja",
    title: "Codex・Claude Codeの会話をエクスポート | Agent Dump",
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
    for (const width of [360, 951]) {
      await page.setViewportSize({ width, height: 844 });

      await expect
        .poll(() => page.evaluate(() => document.documentElement.scrollWidth))
        .toBe(width);
      const boxes = await page
        .locator(
          "#hero h1, #hero .hero-stage, #browse .tui-window, #install code, #install button",
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
      for (const method of await install.locator("button[aria-pressed]").all()) {
        await expect(async () => {
          await method.click();
          await expect(method).toHaveAttribute("aria-pressed", "true");
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

    await expect(page.locator('script[src="https://umami.xingkaixin.me/script.js"]')).toHaveAttribute(
      "data-domains", "agent-dump.xingkaixin.me",
    );

    const install = page.locator("#install");
    const npmTab = install.getByRole("button", { name: "npm", exact: true });
    await npmTab.scrollIntoViewIfNeeded();
    await expect(async () => {
      await npmTab.click();
      await expect(npmTab).toHaveAttribute("aria-pressed", "true");
    }).toPass();

    const npmPanel = install.getByRole("region", { name: "npm" });
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
      await expect(npmTab).toHaveAttribute("aria-pressed", "true");
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
      const tab = install.getByRole("button", { name: label, exact: true });
      if (label === "Scoop") {
        await install
          .getByRole("button", { name: "Homebrew", exact: true })
          .focus();
        await page.keyboard.press("Tab");
        await expect(tab).toBeFocused();
        await tab.press("Enter");
      } else {
        await tab.click();
      }
      await expect(tab).toHaveAttribute("aria-pressed", "true");
      const panel = install.getByRole("region", { name: label, exact: true });
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

    const themeToggle = page.locator("[data-theme-toggle]");
    await themeToggle.click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await expect
      .poll(() => page.evaluate(() => localStorage.getItem("agent-dump-theme")))
      .toBe("dark");
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
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

  const copyButton = page.locator("#install-command").getByRole("button");
  await expect(async () => {
    await copyButton.click();
    await expect(page.locator("html")).toHaveAttribute(
      "data-copy-attempted",
      "true",
    );
  }).toPass();

  expect(await copyButton.getAttribute("aria-label")).toBe("Copy");
});

test("capability tabs switch the sample terminal and stop autoplay", async ({
  page,
}) => {
  await page.goto("/");
  const capabilities = page.locator("#capabilities");
  await capabilities.scrollIntoViewIfNeeded();
  const exportTab = capabilities.getByRole("button", { name: /Export · Reuse with sources/ });
  await expect(async () => {
    await exportTab.click();
    await expect(exportTab).toHaveAttribute("aria-pressed", "true");
  }).toPass();
  await expect(page.locator("#capability-terminal")).toContainText(
    "agent-dump export codex://019a7c2e --format markdown",
  );
  await expect(capabilities.locator(".capability-tab__progress")).toHaveCount(0);
});

test("browse demo answers reader keys like the CLI", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  const demo = page.locator("#browse");
  await demo.scrollIntoViewIfNeeded();
  const terminal = demo.getByRole("application");
  const status = demo.locator(".tui__status");
  await expect(async () => {
    await terminal.click();
    await expect(demo.getByRole("button", { name: "Replay demo" })).toBeVisible();
  }).toPass();

  await terminal.press("j");
  await expect(terminal).toContainText("claude://7f3c91");
  await terminal.press(" ");
  await expect(status).toHaveText(
    "1 selected · e exports selected sessions · Space toggles",
  );
  await terminal.press("e");
  await expect(status).toHaveText("Exporting 1 selected sessions…");

  await terminal.pressSequentially("sauth");
  await expect(status).toContainText("Sessions > auth");
  await terminal.press("Enter");
  await expect(terminal).toContainText("3 sessions · Search (all words): auth");
  await expect(status).toHaveText("3 matching messages · n/N next/previous");
  await terminal.press("x");
  await expect(terminal).toContainText("Excerpt #1–4/6");

  await terminal.press("?");
  await expect(demo.locator(".tui__overlay")).toContainText(
    "s: search sessions in this scope",
  );
  await terminal.press("Escape");
  await expect(demo.locator(".tui__overlay")).toHaveCount(0);

  await demo.getByRole("button", { name: "Replay demo" }).click();
  await expect(demo.getByText("Auto demo · click the terminal to take over")).toBeVisible();
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
